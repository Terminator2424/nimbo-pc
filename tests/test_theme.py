import contextlib
import io
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

from nimbo import cli, theme


class ThemeTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.dict(os.environ, {"NIMBO_HOME": self.tmp.name})
        p.start()
        self.addCleanup(p.stop)

    def run_cli(self, *argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cli.main([*argv])
        return rc, buf.getvalue()

    def test_valid_hex_and_mix(self):
        self.assertTrue(theme.valid_hex("#FF2D55"))
        for bad in ("FF2D55", "#FFF", "#GG0000", "", "#FF2D555"):
            self.assertFalse(theme.valid_hex(bad))
        self.assertEqual(theme.mix("#000000", "#FFFFFF", 0.5), "#808080")
        self.assertEqual(theme.mix("#FF0000", "#FF0000", 0.9), "#FF0000")

    def test_defaults_save_and_reset(self):
        self.assertEqual(theme.load(), {"accent": theme.DEFAULT_ACCENT, "mode": "system"})
        theme.save(accent="#ff2d55", mode="dark")
        self.assertEqual(theme.load(), {"accent": "#FF2D55", "mode": "dark"})
        theme.save(reset=True)
        self.assertEqual(theme.load()["mode"], "system")

    def test_invalid_values_are_rejected(self):
        with self.assertRaises(ValueError):
            theme.save(accent="rojo")
        with self.assertRaises(ValueError):
            theme.save(mode="neon")

    def test_corrupt_config_falls_back_to_defaults(self):
        with mock.patch.object(theme.cfg, "load_user_config", return_value={"theme": {"accent": "x", "mode": 5}}):
            self.assertEqual(theme.load(), {"accent": theme.DEFAULT_ACCENT, "mode": "system"})

    def test_palette_pairs_light_dark(self):
        pal = theme.palette("#FF2D55")
        for field in pal.__dataclass_fields__:
            light, dark = getattr(pal, field)
            self.assertTrue(theme.valid_hex(light) and theme.valid_hex(dark), field)

    def test_cli_theme(self):
        self.assertIn("rose", self.run_cli("theme")[1])
        rc, out = self.run_cli("theme", "--preset", "rose", "--mode", "dark")
        self.assertEqual(rc, 0)
        self.assertEqual(theme.load(), {"accent": "#FF2D55", "mode": "dark"})
        self.assertEqual(self.run_cli("theme", "--accent", "nope")[0], 1)
        self.run_cli("theme", "--reset")
        self.assertEqual(theme.load()["accent"], theme.DEFAULT_ACCENT)

    def test_category_style_fallback(self):
        self.assertEqual(theme.category_style("imagenes")[0], "▣")
        self.assertEqual(theme.category_style("desconocida")[0], "•")


@unittest.skipUnless(sys.platform == "win32" or os.environ.get("DISPLAY"), "necesita pantalla (xvfb)")
class DialogTests(unittest.TestCase):
    def test_dialog_ok_and_cancel(self):
        import customtkinter as ctk

        from nimbo.ui_widgets import Dialog, Style

        root = ctk.CTk()
        self.addCleanup(root.destroy)
        root.geometry("600x400+0+0")
        st = Style("#007AFF")
        for press, expected in ((lambda d: d._ok(), True), (lambda d: d._cancel(), False)):
            d = Dialog(root, st, "¿Seguro?", "Mensaje de prueba")
            root.after(100, lambda d=d, f=press: f(d))
            root.wait_window(d)
            self.assertEqual(d.result, expected)


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(sys.platform == "win32" or os.environ.get("DISPLAY"), "necesita pantalla (xvfb)")
class CanvasWidgetTests(unittest.TestCase):
    def setUp(self):
        import customtkinter as ctk

        from nimbo.ui_widgets import Style

        self.root = ctk.CTk()
        self.addCleanup(self.root.destroy)
        self.root.geometry("700x500+0+0")
        self.st = Style("#007AFF")

    def make_list(self):
        from nimbo.ui_widgets import ItemList

        lst = ItemList(self.root, self.st)
        lst.pack(fill="both", expand=True)
        self.root.update()
        return lst

    def test_virtual_list_draws_only_visible_rows(self):
        lst = self.make_list()
        for i in range(5000):
            lst.add(str(i), f"archivo {i}.pdf", "Descargas → PDFs", "▤", "#007AFF", "90%", "green", check=True)
        self.root.update()
        self.assertLess(len(lst.canvas.find_all()), 400)  # no 5000 filas × 10 piezas
        self.assertEqual(len(lst.rows), 5000)
        lst._yview("moveto", 1.0)
        self.assertGreater(lst._offset, 0)
        lst._yview("moveto", 5.0)  # fuera de rango: se limita
        self.assertLessEqual(lst._offset, lst._total())
        lst._yview("scroll", -100000, "units")
        self.assertEqual(lst._offset, 0)

    def test_click_toggles_checkbox_and_selects_row(self):
        lst = self.make_list()
        seen, clicked = [], []
        lst.add("a", "uno", check=True, on_toggle=lambda k, v: seen.append((k, v)))
        lst.add("b", "dos", on_click=clicked.append)
        self.root.update()

        class Ev:
            def __init__(self, x, y):
                self.x, self.y = x, y

        lst._on_click(Ev(20, 20))  # sobre la casilla de la fila 1
        self.assertEqual(seen, [("a", False)])
        lst._on_click(Ev(300, 20 + lst._step))  # fila 2, fuera de casilla
        self.assertEqual(clicked, ["b"])
        lst.set_selected("b", True)
        lst.set_all_checked(True)
        self.assertTrue(lst.rows["a"]["check"])

    def test_empty_and_skeleton_states(self):
        lst = self.make_list()
        lst.show_skeleton()
        self.root.update()
        self.assertEqual(lst._mode, "skeleton")
        self.assertTrue(lst.canvas.find_withtag("skelbar"))
        lst.add("x", "ya cargó")
        self.assertEqual(lst._mode, "items")
        self.assertIsNone(lst._job)
        lst.clear()
        lst.show_empty("Nada", "no hay nada")
        self.root.update()
        self.assertEqual(lst._mode, "empty")

    def test_ios_switch_state_and_command(self):
        from nimbo.ui_widgets import IOSSwitch

        calls = []
        sw = IOSSwitch(self.root, self.st, command=lambda: calls.append(sw.get()))
        sw.pack()
        self.root.update()
        self.assertEqual(sw.get(), 0)
        sw.select()
        self.assertEqual(sw.get(), 1)
        sw.deselect()
        sw.toggle()
        self.assertEqual((sw.get(), calls), (1, []))  # cambios por programa no disparan el comando
        sw._click()
        self.assertEqual((sw.get(), calls), (0, [0]))
        self.st.redraw_all()  # cambio claro/oscuro no rompe nada


@unittest.skipUnless(sys.platform == "win32" or os.environ.get("DISPLAY"), "necesita pantalla (xvfb)")
class WheelScrollTests(unittest.TestCase):
    """Regresión: pasar el mouse por una ItemList dejaba sin rueda a los demás paneles con scroll (p. ej. Ajustes)."""

    def setUp(self):
        import customtkinter as ctk

        from nimbo.ui_widgets import ItemList, Style

        self.root = ctk.CTk()
        self.addCleanup(self.root.destroy)
        self.root.geometry("700x600+0+0")
        st = Style("#007AFF")
        self.sf = ctk.CTkScrollableFrame(self.root, height=200)
        self.sf.pack(fill="x")
        self.labels = [ctk.CTkLabel(self.sf, text=f"fila {i}") for i in range(60)]
        for lb in self.labels:
            lb.pack()
        self.lst = ItemList(self.root, st)
        self.lst.pack(fill="both", expand=True)
        for i in range(200):
            self.lst.add(str(i), f"archivo {i}")
        self.root.update()

    def wheel(self, widget, down=True):
        pos = {"rootx": widget.winfo_rootx() + 5, "rooty": widget.winfo_rooty() + 5}
        widget.event_generate("<MouseWheel>", delta=-120 if down else 120, **pos)  # Windows y CustomTkinter 5.2
        if sys.platform != "win32":  # Linux real: botones 4 (arriba) y 5 (abajo); CustomTkinter 6 los usa
            widget.event_generate("<Button-5>" if down else "<Button-4>", **pos)
        self.root.update()

    def test_scrollable_frame_still_scrolls_after_pointer_visited_the_list(self):
        self.lst.canvas.event_generate("<Enter>")
        self.root.update()
        self.lst.canvas.event_generate("<Leave>")
        self.root.update()
        self.wheel(self.labels[5])
        self.assertGreater(self.sf._parent_canvas.yview()[0], 0, "el panel de Ajustes dejó de responder a la rueda")

    def test_list_scrolls_with_wheel_and_does_not_scroll_the_panel(self):
        self.wheel(self.lst.canvas)
        self.assertGreater(self.lst._offset, 0)
        self.assertEqual(self.sf._parent_canvas.yview()[0], 0)


class LegacyMigrationTests(unittest.TestCase):
    """Actualizar desde el nombre anterior no debe perder historial, reglas ni configuración."""

    def setUp(self):
        import tempfile

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        env = mock.patch.dict(os.environ, {}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("NIMBO_HOME", None)
        home = mock.patch.object(Path, "home", return_value=self.home)
        home.start()
        self.addCleanup(home.stop)
        if os.name == "nt":  # Windows: %LOCALAPPDATA%\Nimbo (antes ...\OrdenaPC)
            base = self.home / "AppData" / "Local"
            base.mkdir(parents=True)
            os.environ["LOCALAPPDATA"] = str(base)
            self.old, self.new = base / "OrdenaPC", base / "Nimbo"
        else:  # Linux/macOS: ~/.nimbo (antes ~/.ordenapc)
            self.old, self.new = self.home / ".ordenapc", self.home / ".nimbo"

    def make_old(self):
        import sqlite3
        from contextlib import closing

        self.old.mkdir()
        (self.old / "config.json").write_text('{"theme": {"mode": "dark"}}', encoding="utf-8")
        (self.old / "cuarentena").mkdir()
        with closing(sqlite3.connect(str(self.old / "ordenapc.db"))) as c:
            c.execute("CREATE TABLE moves (id INTEGER PRIMARY KEY, dst TEXT)")
            c.execute("INSERT INTO moves(dst) VALUES (?)", (str(self.old / "cuarentena" / "a.pdf"),))
            c.execute("INSERT INTO moves(dst) VALUES (?)", ("/otra/ruta/b.pdf",))
            c.commit()

    def test_moves_data_and_fixes_quarantine_paths(self):
        from nimbo import config

        self.make_old()
        self.assertTrue(config.migrate_legacy_data())
        self.assertFalse(self.old.exists())
        self.assertEqual((self.new / "config.json").read_text(encoding="utf-8"), '{"theme": {"mode": "dark"}}')
        import sqlite3
        from contextlib import closing

        with closing(sqlite3.connect(str(self.new / "nimbo.db"))) as c:
            rows = [r[0] for r in c.execute("SELECT dst FROM moves ORDER BY id")]
        self.assertEqual(
            rows, [str(self.new / "cuarentena" / "a.pdf"), "/otra/ruta/b.pdf"]
        )  # solo se corrige lo propio
        self.assertFalse(config.migrate_legacy_data())  # no repite

    def test_never_overwrites_existing_new_data(self):
        from nimbo import config

        self.make_old()
        self.new.mkdir()
        (self.new / "config.json").write_text("{}", encoding="utf-8")
        self.assertFalse(config.migrate_legacy_data())
        self.assertTrue(self.old.exists())
        self.assertEqual((self.new / "config.json").read_text(encoding="utf-8"), "{}")

    def test_empty_new_folder_does_not_block_migration(self):
        from nimbo import config

        self.make_old()
        self.new.mkdir()
        self.assertTrue(config.migrate_legacy_data())
        self.assertTrue((self.new / "nimbo.db").exists())

    def test_nothing_to_do_and_explicit_home_is_respected(self):
        from nimbo import config

        self.assertFalse(config.migrate_legacy_data())  # no hay datos viejos
        self.make_old()
        with mock.patch.dict(os.environ, {"NIMBO_HOME": str(self.home / "otra")}):
            self.assertFalse(config.migrate_legacy_data())
        self.assertTrue(self.old.exists())
