import json
import os
import unittest
from pathlib import Path
from unittest import mock

from nimbo import cli, projmove
from nimbo.doctor import run_checks
from nimbo.journal import history, undo
from nimbo.projects import classify_dir, discover_projects
from nimbo.projmove import execute_gather, plan_gather, tree_manifest
from tests.test_phase23 import Base


class ProjectBase(Base):
    def proj(self, rel, files):
        for name, data in files.items():
            p = self.root / rel / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data if isinstance(data, bytes) else data.encode())
        return self.root / rel

    def find(self, **kw):
        return discover_projects([self.root], self.prot, **kw)


class DiscoveryTests(ProjectBase):
    def test_finds_projects_by_content_not_name(self):
        self.proj("1234567", {"package.json": json.dumps({"name": "mi-tienda"}), "index.js": "1"})
        self.proj("Universidad/tarea", {"notas.txt": "no es proyecto"})
        self.proj("a/b/c/d/mio", {"pyproject.toml": '[project]\nname = "mi-bot"\n'})
        found = {Path(p.path).name: p for p in self.find()}
        self.assertEqual(set(found), {"1234567", "mio"})
        self.assertEqual(found["1234567"].name_guess, "mi-tienda")
        self.assertTrue(found["1234567"].cryptic)
        self.assertEqual(found["mio"].name_guess, "mi-bot")
        self.assertFalse(found["mio"].cryptic)

    def test_does_not_enter_projects_and_skips_protected(self):
        self.proj("p1", {"package.json": "{}", "sub/package.json": "{}", "node_modules/x/package.json": "{}"})
        self.proj("AppData/Local/algo", {"package.json": "{}"})
        self.proj(".cache/x", {"package.json": "{}"})
        self.assertEqual([Path(p.path).name for p in self.find()], ["p1"])

    def test_weak_needs_code_files_and_venv_detected(self):
        self.proj("w1", {"requirements.txt": "x"})
        self.proj("w2", {"requirements.txt": "x", "a.py": "1", "b.py": "2"})
        self.proj("v", {"pyproject.toml": "", "venv/pyvenv.cfg": "home = x"})
        found = {Path(p.path).name: p for p in self.find()}
        self.assertNotIn("w1", found)
        self.assertEqual(found["w2"].confidence, "media")
        self.assertEqual(found["v"].venvs, ["venv"])

    def test_git_remote_name_and_protected_prefix(self):
        self.proj("123", {".git/config": '[remote "origin"]\n\turl = https://github.com/me/cool-app.git\n'})
        names = {p.name_guess for p in self.find()}
        self.assertEqual(names, {"cool-app"})
        self.prot = __import__("nimbo.protect", fromlist=["Protection"]).Protection([self.root / "123"])
        self.assertEqual(self.find(), [])

    def test_classify_dir(self):
        self.assertEqual(classify_dir({"app.sln"}, [])[1], "alta")
        self.assertIsNone(classify_dir({"readme.md"}, ["a.txt"]))


class GatherTests(ProjectBase):
    def setUp(self):
        super().setUp()
        self.dest = self.root / "Proyectos"
        self.a = self.proj("1234567", {"package.json": json.dumps({"name": "mi-tienda"}), "src/x.js": "abc" * 10})
        self.b = self.proj("Escritorio/b", {"pyproject.toml": '[project]\nname="b"\n', "venv/pyvenv.cfg": "x"})
        self.c = self.proj("Docs/c", {"go.mod": "module github.com/me/ccc\n", "main.go": "1"})
        self.projects = self.find()

    def plan(self, **kw):
        return plan_gather(self.projects, self.dest, self.prot, **kw)

    def test_plan_skips_venv_and_names(self):
        pl = self.plan(rename=True)
        self.assertEqual(sorted(Path(m.dst).name for m in pl.moves), ["ccc", "mi-tienda"])
        self.assertTrue(any("entorno virtual" in s["reason"] for s in pl.skipped))
        self.assertEqual(len(self.plan(allow_venv=True).moves), 3)

    def test_name_collisions_get_suffix(self):
        self.proj("x/app", {"package.json": "{}"})
        self.proj("y/app", {"package.json": "{}"})
        pl = plan_gather(self.find(), self.dest, self.prot)
        names = sorted(Path(m.dst).name for m in pl.moves if m.name == "app")
        self.assertEqual(names, ["app", "app (2)"])

    def test_gather_moves_verifies_and_undo_restores(self):
        before = tree_manifest(str(self.a))
        res = execute_gather(self.conn, self.plan(), log=lambda m: None)
        self.assertEqual((res.moved, res.reverted, res.failed), (2, [], []))
        self.assertFalse(self.a.exists())
        self.assertEqual(tree_manifest(str(self.dest / "1234567")), before)
        self.assertEqual({r["action"] for r in history(self.conn)}, {"move_dir"})
        u = undo(self.conn, batch_id=res.batch_id)
        self.assertEqual(u.restored, 2)
        self.assertEqual(tree_manifest(str(self.a)), before)
        self.assertFalse((self.dest / "1234567").exists())

    def test_auto_revert_when_verification_fails(self):
        real = projmove.tree_manifest
        calls = {"n": 0}

        def flaky(path):
            calls["n"] += 1
            r = real(path)
            return (r[0], r[1], "otra-huella") if calls["n"] == 2 else r  # la 2ª llamada es la de verificación

        with mock.patch.object(projmove, "tree_manifest", flaky):
            res = execute_gather(self.conn, self.plan(), log=lambda m: None)
        self.assertEqual(len(res.reverted), 1)
        self.assertEqual(res.moved, 1)
        self.assertEqual(sum(1 for p in (self.a, self.c) if p.exists()), 1)  # el revertido volvió a su sitio

    def test_failed_rename_changes_nothing(self):
        with mock.patch.object(os, "rename", side_effect=PermissionError("en uso")):
            res = execute_gather(self.conn, self.plan(), log=lambda m: None)
        self.assertEqual((res.moved, len(res.failed)), (0, 2))
        self.assertTrue(self.a.exists() and self.c.exists())
        self.assertEqual(history(self.conn), [])

    def test_already_in_dest_is_ignored(self):
        self.proj("Proyectos/ya", {"package.json": "{}"})
        pl = self.plan()
        self.assertFalse(any("ya" == Path(m.src).name for m in pl.moves))

    def test_cli_gather_dry_run_then_yes(self):
        db = str(self.tmp / "g.db")
        argv = ["gather", "--db", db, "--layout-root", str(self.root), "--root", str(self.root)]
        cli.main(argv)
        self.assertTrue(self.a.exists())
        cli.main(argv + ["--yes"])
        self.assertTrue((self.dest / "1234567").exists())


class AISecurityAndDoctorTests(Base):
    def test_doctor_runs_clean(self):
        res = run_checks(self.conn, self.layout, self.inbox, self.prot)
        self.assertFalse([r for r in res if r[0] == "ERROR"])


if __name__ == "__main__":
    unittest.main()
