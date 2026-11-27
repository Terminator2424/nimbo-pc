import contextlib
import io
import json
import os
import unittest
from unittest import mock

from nimbo import cli, duplicates
from nimbo.duplicates import HEAD_BYTES, find_duplicates
from nimbo.lab import LabError, create_lab
from nimbo.pathutil import fmt_int, fmt_pct, fmt_size, parse_size
from nimbo.programs import (
    ProgramsResult,
    parse_appx_json,
    parse_library_folders,
    parse_vdf,
    parse_winget_export,
    read_steam_games,
    save_programs,
)
from nimbo.report import generate_report
from nimbo.scanner import classify, origin_hint
from tests.helpers import TempCase


class FormatTests(unittest.TestCase):
    def test_fmt(self):
        self.assertEqual(fmt_size(1536), "1,5 KB")
        self.assertEqual(fmt_int(1234567), "1.234.567")
        self.assertEqual(fmt_pct(1, 4), "25,0 %")
        self.assertEqual(parse_size("1,5MB"), int(1.5 * 1024**2))

    def test_classify_and_hints(self):
        self.assertEqual(classify("a.JPG"), (".jpg", "imagenes"))
        self.assertEqual(classify("README"), ("", "sin_extension"))
        self.assertEqual(origin_hint("IMG-20250301-WA0012.jpg"), "whatsapp")
        self.assertEqual(origin_hint("Captura de pantalla 1.png"), "captura")
        self.assertEqual(origin_hint("tarea (1).pdf"), "copia")
        self.assertIsNone(origin_hint("informe.pdf"))


class ScannerTests(TempCase):
    def test_scan_lab_counts_and_protection(self):
        lab = self.make_lab()
        res = self.scan_dir(lab)
        self.assertEqual(res.status, "ok")
        self.assertEqual(res.project_dirs, 1)
        paths = [r["path"] for r in self.conn.execute("SELECT path FROM files")]
        self.assertFalse(any("node_modules" in p or "mi-app" in p for p in paths))
        row = self.conn.execute("SELECT * FROM dirs WHERE kind='project'").fetchone()
        self.assertGreater(row["direct_size"], 0)

    def test_scan_never_modifies_files(self):
        lab = self.make_lab()
        before = {str(p): (p.stat().st_size, p.stat().st_mtime_ns) for p in lab.rglob("*") if p.is_file()}
        self.scan_dir(lab)
        find_duplicates(self.conn)
        after = {str(p): (p.stat().st_size, p.stat().st_mtime_ns) for p in lab.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_rescan_removes_deleted_files(self):
        a = self.write("a.txt", b"1")
        self.write("b.txt", b"2")
        self.scan_dir()
        a.unlink()
        self.scan_dir()
        self.assertEqual([r["name"] for r in self.conn.execute("SELECT name FROM files")], ["b.txt"])

    def test_extra_protected(self):
        self.write("juegos/x.bin", b"123")
        self.write("otros/y.bin", b"1")
        self.scan_dir(extra_protected=[self.work / "juegos"])
        self.assertEqual([r["name"] for r in self.conn.execute("SELECT name FROM files")], ["y.bin"])

    def test_missing_root_warns(self):
        res = self.scan_dir(self.work / "no-existe")
        self.assertTrue(res.warnings)

    @unittest.skipIf(os.name == "nt", "symlinks necesitan permisos en Windows")
    def test_symlinks_skipped(self):
        self.write("real/f.txt", b"x")
        os.symlink(self.work / "real", self.work / "enlace")
        res = self.scan_dir()
        self.assertEqual(res.skipped_links, 1)
        self.assertEqual(res.files, 1)


class DuplicatesTests(TempCase):
    def test_finds_identical_not_same_size(self):
        self.write("a/x.bin", b"A" * 5000)
        self.write("b/y.bin", b"A" * 5000)
        self.write("c/z.bin", b"B" * 5000)
        self.write("d/u.bin", b"C" * 10)
        self.scan_dir()
        groups, _ = find_duplicates(self.conn)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].wasted, 5000)

    def test_empty_not_dupes(self):
        self.write("a/e1.txt", b"")
        self.write("b/e2.txt", b"")
        self.scan_dir()
        self.assertEqual(find_duplicates(self.conn)[0], [])

    def test_same_head_different_tail(self):
        head = b"H" * HEAD_BYTES
        self.write("a/1.bin", head + b"x" * 500)
        self.write("b/2.bin", head + b"y" * 500)
        self.write("c/3.bin", head + b"x" * 500)
        self.scan_dir()
        groups, st = find_duplicates(self.conn)
        self.assertEqual(sorted(os.path.basename(p) for p in groups[0].paths), ["1.bin", "3.bin"])
        self.assertEqual(st.full_hashed, 3)

    def test_cache_and_rehash_on_change(self):
        a = self.write("a/x.bin", b"A" * 5000)
        self.write("b/y.bin", b"A" * 5000)
        self.scan_dir()
        find_duplicates(self.conn)
        with mock.patch.object(duplicates, "hash_file", side_effect=AssertionError("relee")):
            self.assertEqual(len(find_duplicates(self.conn)[0]), 1)
        a.write_bytes(b"Z" * 5000)
        st = a.stat()
        os.utime(a, ns=(st.st_atime_ns, st.st_mtime_ns + 7_000_000_000))
        self.scan_dir()
        self.assertEqual(find_duplicates(self.conn)[0], [])

    def test_hardlinks_not_dupes(self):
        a = self.write("a/o.bin", b"L" * 4000)
        try:
            os.link(a, self.work / "a" / "h.bin")
        except OSError:
            self.skipTest("sin enlaces duros")
        self.scan_dir()
        self.assertEqual(find_duplicates(self.conn)[0], [])

    def test_keep_suggestion_prefers_original(self):
        self.write("Documentos/tarea.pdf", b"P" * 300)
        self.write("Descargas/tarea (1).pdf", b"P" * 300)
        self.scan_dir()
        g = find_duplicates(self.conn)[0][0]
        self.assertTrue(g.paths[0].endswith("tarea.pdf"))


class ProgramsTests(TempCase):
    def test_parsers(self):
        w = json.dumps({"Sources": [{"Packages": [{"PackageIdentifier": "Git.Git"}]}]})
        self.assertEqual(parse_winget_export(w)[0]["name"], "Git.Git")
        self.assertEqual(parse_winget_export("x"), [])
        self.assertEqual(len(parse_appx_json('{"Name":"A"}')), 1)
        lf = '"libraryfolders" { "0" { "path" "C:\\\\Steam" } "1" { "path" "D:\\\\Lib" } }'
        self.assertEqual(parse_library_folders(lf), ["C:\\Steam", "D:\\Lib"])
        self.assertEqual(parse_vdf('"a" { "b" "c" }')["a"]["b"], "c")

    def test_steam_and_save(self):
        steam = self.work / "Steam"
        (steam / "steamapps").mkdir(parents=True)
        (steam / "steamapps" / "appmanifest_730.acf").write_text(
            '"AppState" { "appid" "730" "name" "CS2" "installdir" "cs" "SizeOnDisk" "1000" }'
        )
        games = read_steam_games([steam])
        self.assertEqual(games[0]["name"], "CS2")
        save_programs(
            self.conn,
            ProgramsResult(
                steam_games=games,
                programs=[
                    {
                        "source": "registro",
                        "name": "X",
                        "version": "1",
                        "publisher": None,
                        "install_date": None,
                        "install_location": None,
                        "size_kb": None,
                        "identifier": None,
                    }
                ],
            ),
        )
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM programs").fetchone()[0], 1)


class LabReportCliTests(TempCase):
    def test_lab_refuses_real_folder(self):
        real = self.work / "docs"
        real.mkdir()
        (real / "a.docx").write_text("no tocar")
        with self.assertRaises(LabError):
            create_lab(real, force=True)
        self.assertTrue((real / "a.docx").exists())

    def test_report(self):
        lab = self.make_lab()
        self.scan_dir(lab)
        find_duplicates(self.conn)
        files = generate_report(self.conn, self.tmp / "out")
        md = files["informe"].read_text(encoding="utf-8")
        for h in ("## Resumen", "## Por categoría", "## Zonas protegidas", "## Duplicados"):
            self.assertIn(h, md)
        data = json.loads(files["resumen"].read_text(encoding="utf-8"))
        self.assertGreater(data["duplicates"]["groups"], 0)

    def test_report_empty(self):
        f = generate_report(self.conn, self.tmp / "v")
        self.assertIn("No hay ningún escaneo", f["informe"].read_text(encoding="utf-8"))

    def test_cli_flow(self):
        lab = self.work / "labcli"
        db = str(self.tmp / "c.db")
        out = str(self.tmp / "rep")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(cli.main(["lab", str(lab)]), 0)
            self.assertEqual(cli.main(["scan", "--root", str(lab), "--db", db]), 0)
            self.assertEqual(cli.main(["dupes", "--db", db]), 0)
            self.assertEqual(cli.main(["report", "--db", db, "--out", out]), 0)
        self.assertIn("Grupos de duplicados: 4", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
