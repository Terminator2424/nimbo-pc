import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

from nimbo import ai as ailib
from nimbo.journal import history
from nimbo.learning import add_rule, detect_corrections, load_rules, match_rule
from tests.test_phase23 import Base


class LearningTests(Base):
    def test_manual_rule_overrides_default(self):
        add_rule(self.conn, ".pdf", str(self.root / "Documentos" / "Facturas"))
        self.put("Descargas/a.pdf")
        plan = self.plan(rules=load_rules(self.conn))
        self.assertEqual(Path(plan.moves[0].dst), self.root / "Documentos" / "Facturas" / "a.pdf")

    def test_hint_rule_beats_generic_rule(self):
        rules = [{"ext": ".png", "hint": "", "dest_dir": "G"}, {"ext": ".png", "hint": "captura", "dest_dir": "C"}]
        self.assertEqual(match_rule(rules, "Captura de pantalla 1.png"), "C")
        self.assertEqual(match_rule(rules, "foto.png"), "G")
        self.assertIsNone(match_rule(rules, "foto.jpg"))

    def test_learns_from_user_correction(self):
        self.put("Descargas/Captura de pantalla 2025-03-01.png", b"S" * 99)
        self.apply(self.plan())
        row = history(self.conn)[0]
        target = self.root / "Imagenes" / "Trabajo"
        target.mkdir(parents=True)
        os.rename(row["dst"], target / Path(row["dst"]).name)  # el usuario lo cambia de carpeta
        msgs = detect_corrections(self.conn, [self.root / "Imagenes"], self.inbox)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(load_rules(self.conn)[0]["dest_dir"], str(target))
        self.assertEqual(load_rules(self.conn)[0]["hint"], "captura")
        self.put("Descargas/Captura de pantalla 2025-04-09.png", b"T" * 50)
        plan = self.plan(rules=load_rules(self.conn))
        self.assertEqual(Path(plan.moves[0].dst).parent, target)

    def test_moving_back_to_inbox_creates_no_rule(self):
        self.put("Descargas/a.pdf", b"1" * 10)
        self.apply(self.plan())
        row = history(self.conn)[0]
        os.rename(row["dst"], self.root / "Descargas" / "a.pdf")
        detect_corrections(self.conn, [self.root / "Documentos", self.root / "Descargas"], self.inbox)
        self.assertEqual(load_rules(self.conn), [])


class FakeLLM(BaseHTTPRequestHandler):
    reply = ""

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        body = json.dumps({"choices": [{"message": {"content": FakeLLM.reply}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class AITests(Base):
    def setUp(self):
        super().setUp()
        self.srv = HTTPServer(("127.0.0.1", 0), FakeLLM)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        self.conf = {"url": f"http://127.0.0.1:{self.srv.server_port}", "model": "x", "timeout": 5}
        (self.root / "Documentos" / "Universidad").mkdir(parents=True)

    def test_suggest_valid_invalid_and_new(self):
        f = self.put("Descargas/apuntes.txt", b"calculo integral limites")
        FakeLLM.reply = 'Claro: {"carpeta": "Universidad", "confianza": 0.9, "motivo": "apuntes"}'
        s = ailib.suggest_folder(self.conf, str(f), ["Universidad"])
        self.assertEqual((s["label"], s["confidence"]), ("Universidad", 0.9))
        FakeLLM.reply = '{"carpeta": "Inventada", "confianza": 0.99}'
        self.assertIsNone(ailib.suggest_folder(self.conf, str(f), ["Universidad"]))
        FakeLLM.reply = '{"carpeta": "NUEVA:Recetas/../x", "confianza": 0.95}'
        s = ailib.suggest_folder(self.conf, str(f), ["Universidad"])
        self.assertLessEqual(s["confidence"], 0.7)
        self.assertNotIn("/", s["label"])
        FakeLLM.reply = "no es json"
        self.assertIsNone(ailib.suggest_folder(self.conf, str(f), ["Universidad"]))

    def test_unreachable_server_raises_friendly_error(self):
        f = self.put("Descargas/a.txt")
        with self.assertRaises(ailib.AIError):
            ailib.suggest_folder({"url": "http://127.0.0.1:1", "model": "x", "timeout": 1}, str(f), [])

    def test_accept_moves_with_history_and_reject_does_not(self):
        a = self.put("Descargas/apuntes.dat", b"datos")
        b = self.put("Descargas/otra.dat", b"otros")
        FakeLLM.reply = '{"carpeta": "Universidad", "confianza": 0.85, "motivo": "m"}'
        plan = self.plan()
        ids = ailib.make_suggestions(self.conn, ailib.collect_candidates(plan), self.layout, self.conf)
        self.assertEqual(len(ids), 2)
        ailib.resolve(self.conn, [ids[0]], False, self.layout, self.prot, self.inbox)
        ailib.resolve(self.conn, [ids[1]], True, self.layout, self.prot, self.inbox)
        moved = [p for p in (a, b) if not p.exists()]
        self.assertEqual(len(moved), 1)
        self.assertEqual(len(history(self.conn)), 1)
        self.assertEqual(ailib.pending(self.conn), [])
        again = ailib.make_suggestions(self.conn, ailib.collect_candidates(self.plan()), self.layout, self.conf)
        self.assertEqual(again, [])  # lo rechazado no se vuelve a sugerir


@unittest.skipUnless(sys.platform == "win32" or os.environ.get("DISPLAY"), "necesita pantalla (xvfb)")
class UISmokeTests(Base):
    def test_window_plan_move_undo(self):
        from nimbo.lab import create_lab
        from nimbo import ui

        lab = self.tmp / "lab"
        create_lab(lab)
        with mock.patch.dict(os.environ, {"NIMBO_HOME": str(self.tmp / "home")}):
            app = ui.App(layout_root=str(lab), db=str(self.tmp / "ui.db"))
            try:
                app.watch_switch.deselect()
                app.toggle_watch()
                app.update()
                app.plan = __import__("nimbo.classifier", fromlist=["build_plan"]).build_plan(
                    app.inbox, app.layout, app.protection, settle_seconds=0
                )
                self.assertGreater(len(app.plan.moves), 5)
                app.refresh_plan(sync=True)
                app.update()
                app._ask = lambda *a, **k: True
                app._info = lambda *a, **k: None
                app.plan = __import__("nimbo.classifier", fromlist=["build_plan"]).build_plan(
                    app.inbox, app.layout, app.protection, settle_seconds=0
                )
                n = len(app.plan.moves)
                app.unchecked = {"0"}
                app.move_checked()
                app.refresh_history()
                self.assertEqual(len(history(app.conn)), n - 1 if n else 0)
                self.assertEqual(len(app.hist_list.rows), n - 1)
                app.undo_all()
                self.assertEqual(len(history(app.conn, 500)), (n - 1) * 2)
            finally:
                app.quit_app()
        # Guardia anti-cuelgue: tras cerrar la ventana no debe quedar ningún hilo que impida terminar el proceso
        # (un hilo de bandeja no-daemon dejó los trabajos de Ubuntu del CI colgados 6 horas).
        import threading

        stragglers = [th.name for th in threading.enumerate() if th is not threading.main_thread() and not th.daemon]
        self.assertEqual(stragglers, [], "quedaron hilos que impiden terminar el proceso")


if __name__ == "__main__":
    unittest.main()
