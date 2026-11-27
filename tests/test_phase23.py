import hashlib
import os
import time
import unittest
from pathlib import Path

from nimbo import cli
from nimbo.classifier import Layout, Plan, build_plan, date_from_name, decide
from nimbo.journal import apply_plan, history, undo
from nimbo.protect import Protection
from nimbo.watcher import watch
from tests.helpers import TempCase


def snapshot(root: Path) -> dict:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()
    }


class Base(TempCase):
    def setUp(self):
        super().setUp()
        self.root = self.work / "pc"
        self.layout = Layout.from_root(self.root)
        self.inbox = [self.root / "Descargas", self.root / "Escritorio"]
        for d in self.inbox:
            d.mkdir(parents=True)
        self.prot = Protection()

    def put(self, rel, data=b"x", age_days=5):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        t = time.time() - age_days * 86400
        os.utime(p, (t, t))
        return p

    def plan(self, **kw):
        kw.setdefault("settle_seconds", 60)
        return build_plan(self.inbox, self.layout, self.prot, **kw)

    def apply(self, plan):
        return apply_plan(self.conn, plan, self.layout, self.prot, self.inbox)


class ClassifierTests(Base):
    def test_date_from_name(self):
        self.assertEqual(date_from_name("Screenshot_2025-04-02-18.png").month, 4)
        self.assertEqual(date_from_name("IMG-20250301-WA0012.jpg").day, 1)
        self.assertIsNone(date_from_name("foto_99999999.jpg"))

    def test_rules(self):
        d, *_ = decide("Captura de pantalla 2025-03-01.png", 0, self.layout, "downloads")
        self.assertEqual(d, self.layout.pictures / "Capturas" / "2025-03")
        d, *_ = decide("IMG-20250301-WA0012.jpg", 0, self.layout, "downloads")
        self.assertEqual(d, self.layout.pictures / "WhatsApp" / "2025-03")
        d, *_ = decide("setup.exe", 0, self.layout, "downloads")
        self.assertEqual(d, self.layout.downloads / "Instaladores")
        d, why, *_ = decide("juego.exe", 0, self.layout, "desktop")
        self.assertIsNone(d)
        self.assertIsNone(decide("script.py", 0, self.layout, "downloads")[0])
        self.assertIsNone(decide("a.crdownload", 0, self.layout, "downloads")[0])

    def test_plan_skips_recent_projects_and_folders(self):
        self.put("Descargas/a.pdf")
        self.put("Descargas/nuevo.pdf", age_days=0)
        self.put("Descargas/mi-proy/package.json", b"{}")
        self.put("Descargas/mi-proy/doc.pdf")
        self.put("Escritorio/Steam.lnk")
        plan = self.plan(deep=True)
        srcs = [Path(m.src).name for m in plan.moves]
        self.assertEqual(srcs, ["a.pdf"])
        reasons = " ".join(s["reason"] for s in plan.skipped)
        self.assertIn("muy reciente", reasons)

    def test_plan_json_roundtrip(self):
        self.put("Descargas/a.pdf")
        plan = self.plan()
        self.assertEqual(Plan.from_json(plan.to_json()).moves[0].dst, plan.moves[0].dst)

    def test_protected_prefix(self):
        self.put("Descargas/juegos/x.pdf")
        self.prot = Protection([self.root / "Descargas" / "juegos"])
        self.assertEqual(self.plan(deep=True).moves, [])


class JournalTests(Base):
    def populate(self):
        self.put("Descargas/tarea.pdf", b"P" * 500)
        self.put("Descargas/Captura de pantalla 2025-03-01.png", b"S" * 300)
        self.put("Descargas/VSCodeSetup.exe", b"E" * 400)
        self.put("Escritorio/foto.jpg", b"J" * 200)
        self.put("Escritorio/notas.txt", b"N" * 100)

    def test_apply_then_undo_restores_everything(self):
        self.populate()
        before = snapshot(self.root)
        r = self.apply(self.plan())
        self.assertEqual(r.done, 5)
        self.assertTrue((self.root / "Imagenes/Capturas/2025-03/Captura de pantalla 2025-03-01.png").exists())
        self.assertTrue((self.root / "Descargas/Instaladores/VSCodeSetup.exe").exists())
        self.assertFalse((self.root / "Descargas/tarea.pdf").exists())
        self.assertEqual(len(history(self.conn)), 5)
        u = undo(self.conn, batch_id=r.batch_id)
        self.assertEqual(u.restored, 5)
        self.assertEqual(snapshot(self.root), before)

    def test_never_overwrites_different_file(self):
        self.put("Descargas/a.pdf", b"NUEVO")
        year = time.localtime(time.time() - 5 * 86400).tm_year
        existing = self.put(f"Documentos/PDFs/{year}/a.pdf", b"VIEJO-DISTINTO")
        r = self.apply(self.plan())
        self.assertEqual(existing.read_bytes(), b"VIEJO-DISTINTO")
        self.assertTrue((existing.parent / "a (2).pdf").exists())
        self.assertEqual(r.done, 1)

    def test_identical_copy_goes_to_quarantine_not_deleted(self):
        year = time.localtime(time.time() - 5 * 86400).tm_year
        self.put(f"Documentos/PDFs/{year}/tarea.pdf", b"IGUAL" * 50)
        self.put("Descargas/tarea (1).pdf", b"IGUAL" * 50)
        r = self.apply(self.plan())
        self.assertEqual(r.quarantined, 1)
        q = list((self.root / "_Cuarentena").rglob("tarea (1).pdf"))
        self.assertEqual(len(q), 1)
        undo(self.conn, batch_id=r.batch_id)
        self.assertTrue((self.root / "Descargas/tarea (1).pdf").exists())

    def test_undo_does_not_overwrite_occupied_origin(self):
        self.put("Descargas/a.pdf", b"AAA")
        r = self.apply(self.plan())
        (self.root / "Descargas/a.pdf").write_bytes(b"otro archivo nuevo")
        undo(self.conn, batch_id=r.batch_id)
        self.assertEqual((self.root / "Descargas/a.pdf").read_bytes(), b"otro archivo nuevo")
        self.assertTrue((self.root / "Descargas/a (restaurado).pdf").exists())

    def test_file_changed_after_plan_is_skipped(self):
        p = self.put("Descargas/a.pdf", b"123")
        plan = self.plan()
        p.write_bytes(b"123456")
        r = self.apply(plan)
        self.assertEqual(r.done, 0)
        self.assertTrue(r.skipped)

    def test_undo_all_and_missing(self):
        self.put("Descargas/a.pdf", b"1")
        self.put("Descargas/b.pdf", b"22")
        self.apply(self.plan())
        moved = [Path(row["dst"]) for row in history(self.conn)]
        moved[0].unlink()  # el usuario borró uno a mano
        u = undo(self.conn, everything=True)
        self.assertEqual((u.restored, len(u.missing)), (1, 1))


class WatcherAndCliTests(Base):
    def test_watcher_simulation_does_not_move_and_apply_does(self):
        p = self.put("Descargas/a.pdf", b"1")
        logs = []
        watch(self.conn, self.inbox, self.layout, self.prot, apply=False, settle=60, max_cycles=1, log=logs.append)
        self.assertTrue(p.exists())
        self.assertIn("simulación", " ".join(logs).lower())
        watch(
            self.conn,
            self.inbox,
            self.layout,
            self.prot,
            apply=True,
            settle=60,
            max_cycles=2,
            log=logs.append,
            sleep=lambda s: None,
        )
        self.assertFalse(p.exists())
        self.assertEqual(len(history(self.conn)), 1)  # el segundo ciclo no repite nada

    def test_cli_plan_apply_undo(self):
        self.put("Descargas/a.pdf", b"1")
        db = str(self.tmp / "cli.db")
        base = ["--db", db]
        self.assertEqual(
            cli.main(["plan", *base, "--layout-root", str(self.root), "--out", str(self.tmp / "p.json")]), 0
        )
        self.assertTrue((self.root / "Descargas/a.pdf").exists())
        cli.main(["apply", *base, "--layout-root", str(self.root)])  # sin --yes: simula
        self.assertTrue((self.root / "Descargas/a.pdf").exists())
        cli.main(["apply", *base, "--layout-root", str(self.root), "--yes"])
        self.assertFalse((self.root / "Descargas/a.pdf").exists())
        cli.main(["undo", "--db", db, "--last"])
        self.assertTrue((self.root / "Descargas/a.pdf").exists())


if __name__ == "__main__":
    unittest.main()


class WatcherQuietTests(Base):
    def test_simulation_does_not_repeat_each_cycle(self):
        self.put("Descargas/a.pdf", b"1")
        logs = []
        watch(
            self.conn,
            self.inbox,
            self.layout,
            self.prot,
            apply=False,
            settle=60,
            max_cycles=4,
            log=logs.append,
            sleep=lambda s: None,
        )
        self.assertEqual(sum("Revisé las carpetas" in line for line in logs), 1)
        self.assertEqual(sum("(simulación)" in line for line in logs), 1)
        self.assertIn("SOLO SIMULACIÓN", logs[0])


class LinkAndSummaryTests(unittest.TestCase):
    def test_only_symlinks_and_junctions_are_links(self):
        from nimbo.scanner import _is_link

        class St:
            def __init__(self, attrs, tag):
                self.st_file_attributes, self.st_reparse_tag = attrs, tag

        class Entry:
            def __init__(self, st, symlink=False):
                self._st, self._sym = st, symlink

            def is_symlink(self):
                return self._sym

            def stat(self, follow_symlinks=False):
                return self._st

        self.assertTrue(_is_link(Entry(St(0, 0), symlink=True)))
        self.assertTrue(_is_link(Entry(St(0x400, 0xA000000C))))  # symlink de Windows
        self.assertTrue(_is_link(Entry(St(0x400, 0xA0000003))))  # junction
        self.assertFalse(_is_link(Entry(St(0x400, 0x9000601A))))  # archivo de OneDrive: es un archivo normal
        self.assertFalse(_is_link(Entry(St(0x20, 0))))

    def test_skipped_summary_groups_reasons(self):
        from nimbo.ui import skipped_summary

        text = skipped_summary(
            [
                {"src": "/d/a.html", "reason": "sin regla clara (codigo): se revisa a mano"},
                {"src": "/d/b.html", "reason": "sin regla clara (codigo): se revisa a mano"},
                {"src": "/d/c.zip", "reason": "muy reciente: puede estar descargándose o en uso"},
            ]
        )
        self.assertIn("2 × sin regla clara", text)
        self.assertIn("a.html, b.html", text)
        self.assertIn("carpetas no se mueven", text)
        self.assertIn("No hay archivos", skipped_summary([]))
