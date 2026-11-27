import contextlib
import io
import json
import unittest
from unittest import mock

from nimbo import cli
from tests.test_phase23 import Base


class CliMoreTests(Base):
    def run_cli(self, *argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cli.main([*argv])
        return rc, buf.getvalue()

    def setUp(self):
        super().setUp()
        self.db = str(self.tmp / "m.db")
        self.lr = ["--layout-root", str(self.root)]

    def test_doctor_and_games(self):
        rc, out = self.run_cli("doctor", "--db", self.db, *self.lr)
        self.assertEqual(rc, 0)
        self.assertIn("integridad: ok", out)
        rc, out = self.run_cli("games")
        self.assertEqual(rc, 0)

    def test_teach_rules_history_search(self):
        self.put("Descargas/factura.pdf", b"1" * 20)
        self.assertEqual(self.run_cli("teach", "--db", self.db, "--ext", ".pdf", "--dest", str(self.root / "F"))[0], 0)
        self.assertIn(".pdf", self.run_cli("rules", "--db", self.db)[1])
        self.run_cli("apply", "--db", self.db, *self.lr, "--settle", "0", "--yes")
        self.assertTrue((self.root / "F" / "factura.pdf").exists())
        self.assertIn("factura.pdf", self.run_cli("history", "--db", self.db, "--search", "factura")[1])
        self.assertIn("Borrada", self.run_cli("rules", "--db", self.db, "--delete", "1")[1])

    def test_projects_json_and_report(self):
        (self.root / "p1").mkdir()
        (self.root / "p1" / "package.json").write_text("{}")
        out_json = self.tmp / "p.json"
        rc, out = self.run_cli("projects", "--db", self.db, *self.lr, "--root", str(self.root), "--json", str(out_json))
        self.assertEqual(rc, 0)
        self.assertEqual(len(json.loads(out_json.read_text())), 1)
        self.run_cli("scan", "--db", self.db, "--root", str(self.root))
        rc, out = self.run_cli("report", "--db", self.db, "--out", str(self.tmp / "rep"))
        self.assertEqual(rc, 0)

    def test_undo_requires_choice_and_watch_one_cycle(self):
        self.assertEqual(self.run_cli("undo", "--db", self.db)[0], 1)
        self.put("Descargas/a.pdf", b"1")
        with mock.patch("nimbo.cli.watch", return_value=1) as w:
            self.run_cli("watch", "--db", self.db, *self.lr)
        self.assertTrue(w.called)

    def test_ai_suggest_without_config_explains(self):
        rc, out = self.run_cli("ai-suggest", "--db", self.db, *self.lr)
        self.assertEqual(rc, 1)
        self.assertIn("ai-config", out)

    def test_output_never_crashes_on_a_narrow_encoding(self):
        """Regresión Windows: con la salida redirigida (cp1252/ascii) un carácter como «·» o «✓» tumbaba el comando."""
        import sys

        raw = io.BytesIO()
        narrow = io.TextIOWrapper(raw, encoding="ascii", errors="strict")
        with mock.patch.object(sys, "stdout", narrow):
            rc = cli.main(["theme"])  # imprime «·» y acentos
            narrow.flush()
        self.assertEqual(rc, 0)
        self.assertIn(b"Color actual", raw.getvalue())

    def test_autostart_status_non_windows(self):
        rc, out = self.run_cli("autostart", "status")
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
