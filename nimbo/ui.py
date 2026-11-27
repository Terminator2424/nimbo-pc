"""Ventana de Nimbo (CustomTkinter) con estética iOS, vigilante en segundo plano y bandeja.

Diseño: nimbo/theme.py (colores/fuentes) y nimbo/ui_widgets.py (componentes). Esta clase solo arma las pantallas.
"""

from __future__ import annotations

import logging
import os
import queue
import socket
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog
from typing import Any

import customtkinter as ctk

from . import ai as ailib
from . import autostart, keystore
from . import config as cfg
from . import db as database
from . import theme
from .classifier import Plan, build_plan
from .context import make_context
from .journal import apply_plan, history, undo
from .learning import load_rules
from .pathutil import fmt_int, fmt_size
from .projects import discover_projects, fixed_drives
from .projmove import execute_gather, plan_gather
from .ui_widgets import Dialog, IOSSwitch, ItemList, Segmented, Style, button, card, ellipsize, header
from .watcher import watch

LOCK_PORT = 47863
log = logging.getLogger(__name__)

NAV = [
    ("plan", "Plan", "⇆", "#007AFF"),
    ("historial", "Historial", "↺", "#FF9500"),
    ("proyectos", "Proyectos", "▤", "#AF52DE"),
    ("ia", "Sugerencias", "✦", "#FF2D55"),
    ("vigilante", "Vigilante", "◉", "#34C759"),
    ("ajustes", "Ajustes", "⚙", "#8E8E93"),
]
ACTION_STYLE = {
    "move": ("→", "#007AFF"),
    "quarantine": ("▢", "#FF9500"),
    "undo": ("↺", "#8E8E93"),
    "move_dir": ("▤", "#5856D6"),
}
STATUS_BADGE = {
    "done": ("Hecho", "green"),
    "undone": ("Deshecho", "gray"),
    "missing": ("No estaba", "orange"),
    "corrected": ("Corregido", "accent"),
}


def skipped_summary(skipped: list[dict], max_groups: int = 8) -> str:
    """Explica en lenguaje simple por qué ciertos archivos no se mueven."""
    groups: dict[str, list[str]] = {}
    for item in skipped:
        groups.setdefault(item["reason"], []).append(os.path.basename(item["src"]))
    lines = []
    for reason, names in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:max_groups]:
        ejemplos = ", ".join(names[:3]) + ("…" if len(names) > 3 else "")
        lines.append(f"• {len(names)} × {reason}\n   {ejemplos}")
    if not lines:
        lines.append("No hay archivos sueltos que se queden quietos.")
    lines.append("Las carpetas no se mueven (los proyectos se reúnen en la pestaña Proyectos).")
    return "\n\n".join(lines)


def tail(path: str, parts: int = 2) -> str:
    p = Path(path)
    return "/".join(p.parts[-parts:]) if len(p.parts) > 1 else str(p)


def where(src: str, dst: str) -> str:
    return f"{tail(str(Path(src).parent), 1)}  →  {tail(str(Path(dst).parent), 2)}"


class ListEditor(ctk.CTkFrame):
    """Lista de carpetas guardada en config.json (protegidas / de entrada)."""

    def __init__(self, master, st: Style, key: str, title: str, hint: str, on_change):
        super().__init__(master, fg_color=st.C.CARD, corner_radius=16)
        self.st, self.key, self.on_change = st, key, on_change
        ctk.CTkLabel(self, text=title, font=st.headline, text_color=st.C.TEXT, anchor="w").pack(
            fill="x", padx=18, pady=(14, 0)
        )
        ctk.CTkLabel(
            self, text=hint, font=st.small, text_color=st.C.TEXT2, anchor="w", justify="left", wraplength=560
        ).pack(fill="x", padx=18, pady=(0, 6))
        self.rows = ctk.CTkFrame(self, fg_color="transparent", height=1)
        self.rows.pack(fill="x", padx=14)
        button(self, st, "＋  Agregar carpeta…", self.add, "text").pack(anchor="w", padx=10, pady=(2, 10))
        self.render()

    def values(self) -> list[str]:
        return list(cfg.load_user_config().get(self.key) or [])

    def render(self) -> None:
        for w in self.rows.winfo_children():
            w.destroy()
        for path in self.values():
            r = ctk.CTkFrame(self.rows, fg_color=self.st.C.FILL, corner_radius=10)
            r.pack(fill="x", pady=2)
            ctk.CTkLabel(r, text=ellipsize(path, 80), font=self.st.small, text_color=self.st.C.TEXT, anchor="w").pack(
                side="left", padx=12, pady=7
            )
            ctk.CTkButton(
                r,
                text="✕",
                width=30,
                height=26,
                corner_radius=13,
                fg_color="transparent",
                hover_color=self.st.C.SEP,
                text_color=self.st.C.TEXT2,
                command=lambda p=path: self.remove(p),
            ).pack(side="right", padx=6)

    def add(self) -> None:
        d = filedialog.askdirectory()
        if d:
            vals = self.values()
            vals.append(str(Path(d)))
            cfg.save_user_config({self.key: vals})
            self.render()
            self.on_change()

    def remove(self, path: str) -> None:
        cfg.save_user_config({self.key: [p for p in self.values() if p != path]})
        self.render()
        self.on_change()


class App(ctk.CTk):
    def __init__(self, start_hidden: bool = False, layout_root: str | None = None, db: str | None = None):
        super().__init__()
        self.withdraw()  # se muestra cuando todo está armado (evita ver piezas a medio dibujar)
        self.th = theme.load()
        ctk.set_appearance_mode(self.th["mode"])
        self.title("Nimbo")
        self.geometry("1160x760")
        self.minsize(960, 640)
        self.layout_root = layout_root
        self.db_path = Path(db) if db else cfg.default_db_path()
        self.conn = database.connect(self.db_path)
        self.stop_event = threading.Event()
        self.watch_thread: threading.Thread | None = None
        self.log_q: queue.Queue = queue.Queue()
        self.cmd_q: queue.Queue = queue.Queue()
        self.plan = Plan()
        self.unchecked: set[str] = set()
        self.proj_unchecked: set[str] = set()
        self.projects: list = []
        self.hist_batch: dict[str, int] = {}
        self.hist_selected: str | None = None
        self.ai_selected: set[int] = set()
        self._plan_token = 0
        self.current = "plan"
        self.tray: Any = None
        self._toast_job: str | None = None
        self.reload_context()
        self.st = Style(self.th["accent"])
        self._build_all()

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self._start_tray()
        self.update_idletasks()
        if not (start_hidden and self.tray):
            self.deiconify()
        if cfg.load_user_config().get("watch_on_start", True):
            self.watch_switch.select()
            self.toggle_watch()
        self.after(400, self._poll)

    # ---------------------------------------------------------------- armado
    def _build_all(self) -> None:
        C = self.st.C
        self.configure(fg_color=C.BG)
        self.side = ctk.CTkFrame(self, width=232, corner_radius=0, fg_color=C.SIDEBAR)
        self.side.pack(side="left", fill="y")
        self.side.pack_propagate(False)
        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.pack(side="left", fill="both", expand=True, padx=(26, 26), pady=(22, 18))
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)
        self._build_sidebar()
        self.pages: dict[str, ctk.CTkFrame] = {}
        builders = {
            "plan": self._page_plan,
            "historial": self._page_history,
            "proyectos": self._page_projects,
            "ia": self._page_ai,
            "vigilante": self._page_watch,
            "ajustes": self._page_settings,
        }
        for key, fn in builders.items():
            frame = ctk.CTkFrame(self.content, fg_color="transparent")
            frame.grid(row=0, column=0, sticky="nsew")  # apiladas: cambiar de pestaña solo sube una al frente
            fn(frame)
            self.pages[key] = frame
        self.toast_box = ctk.CTkFrame(self, fg_color=C.TOAST, corner_radius=18)
        self.toast_icon = ctk.CTkLabel(
            self.toast_box,
            text="✓",
            width=26,
            height=26,
            corner_radius=13,
            fg_color=C.GREEN,
            text_color="#FFFFFF",
            font=self.st.headline,
        )
        self.toast_icon.pack(side="left", padx=(14, 0), pady=11)
        self.toast_label = ctk.CTkLabel(
            self.toast_box, text="", font=self.st.headline, text_color=C.TOAST_TEXT, wraplength=520, justify="left"
        )
        self.toast_label.pack(side="left", padx=(12, 20), pady=12)
        self.show(self.current)
        self.refresh_plan()

    def _build_sidebar(self) -> None:
        st, C = self.st, self.st.C
        top = ctk.CTkFrame(self.side, fg_color="transparent")
        top.pack(fill="x", padx=18, pady=(24, 18))
        ctk.CTkLabel(
            top, text="✓", width=38, height=38, corner_radius=11, fg_color=C.ACCENT, text_color="#FFFFFF", font=st.glyph
        ).pack(side="left")
        col = ctk.CTkFrame(top, fg_color="transparent")
        col.pack(side="left", padx=11)
        ctk.CTkLabel(col, text="Nimbo", font=st.title, text_color=C.TEXT, anchor="w").pack(anchor="w")
        ctk.CTkLabel(col, text="Tu PC en orden", font=st.small, text_color=C.TEXT2, anchor="w").pack(anchor="w")
        self.nav_items: dict[str, tuple[ctk.CTkFrame, ctk.CTkLabel]] = {}
        for key, label, glyph, color in NAV:
            row = ctk.CTkFrame(self.side, fg_color="transparent", corner_radius=12, height=42)
            row.pack(fill="x", padx=12, pady=1)
            row.pack_propagate(False)
            tile = ctk.CTkLabel(
                row,
                text=glyph,
                width=28,
                height=28,
                corner_radius=8,
                fg_color=color,
                text_color="#FFFFFF",
                font=st.headline,
            )
            tile.pack(side="left", padx=(10, 12), pady=7)
            lab = ctk.CTkLabel(row, text=label, font=st.body, text_color=C.TEXT, anchor="w")
            lab.pack(side="left", fill="x", expand=True)
            for w in (row, tile, lab):
                w.bind("<Button-1>", lambda _e, k=key: self.show(k))
                w.configure(cursor="hand2")
            self.nav_items[key] = (row, lab)
        spacer = ctk.CTkFrame(self.side, fg_color="transparent")
        spacer.pack(fill="both", expand=True)
        self.side_status = ctk.CTkLabel(self.side, text="● En pausa", font=st.small, text_color=C.TEXT2, anchor="w")
        self.side_status.pack(fill="x", padx=24, pady=(0, 20))

    def show(self, key: str) -> None:
        self.current = key
        self.pages[key].tkraise()
        for k, (row, lab) in self.nav_items.items():
            on = k == key
            row.configure(fg_color=self.st.C.ACCENT_SOFT if on else "transparent")
            lab.configure(text_color=self.st.C.ACCENT if on else self.st.C.TEXT)
        if key == "historial":  # los datos se cargan al entrar, no todos al abrir la app
            self.refresh_history()
        elif key == "ia":
            self.refresh_ai()

    def rebuild(self) -> None:
        """Reconstruye la ventana (cambio de color de acento)."""
        for w in (self.side, self.content, self.toast_box):
            w.destroy()
        self.st = Style(self.th["accent"])
        self._build_all()
        running = bool(self.watch_thread and self.watch_thread.is_alive() and not self.stop_event.is_set())
        if running:
            self.watch_switch.select()
            self._paint_watch_status(True)

    # ------------------------------------------------------------- utilidades
    def reload_context(self) -> None:
        self.layout, self.inbox, self.protection = make_context(self.conn, self.layout_root)

    def _ask(
        self,
        title: str,
        msg: str,
        ok: str = "Continuar",
        destructive: bool = False,
        kind: str = "question",
        cancel: str | None = "Cancelar",
    ) -> bool:
        d = Dialog(self, self.st, title, msg, ok=ok, cancel=cancel, destructive=destructive, kind=kind)
        self.wait_window(d)
        return d.result

    def _info(self, title: str, msg: str, kind: str = "success") -> None:
        self.toast(f"{title}\n{msg}" if msg else title, kind=kind)

    def toast(self, text: str, ms: int = 4200, kind: str = "info") -> None:
        C = self.st.C
        glyph, color = {"success": ("✓", C.GREEN), "warning": ("!", C.ORANGE), "info": ("i", C.ACCENT)}[kind]
        self.toast_icon.configure(text=glyph, fg_color=color)
        self.toast_label.configure(text=text)
        self.toast_box.place(relx=0.5, rely=0.965, anchor="s")
        self.toast_box.lift()
        if self._toast_job:
            self.after_cancel(self._toast_job)
        self._toast_job = self.after(ms, self.toast_box.place_forget)

    def _stat(self, parent, title: str, col: int, color) -> ctk.CTkLabel:
        c = card(parent, self.st)
        c.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 8, 0))
        parent.grid_columnconfigure(col, weight=1, uniform="stat")
        ctk.CTkLabel(c, text=title, font=self.st.small, text_color=self.st.C.TEXT2, anchor="w").pack(
            anchor="w", padx=18, pady=(14, 0)
        )
        v = ctk.CTkLabel(c, text="0", font=self.st.stat, text_color=color, anchor="w")
        v.pack(anchor="w", padx=18, pady=(0, 12))
        return v

    # ------------------------------------------------------------------- plan
    def _page_plan(self, page) -> None:
        st, C = self.st, self.st.C
        act = header(page, st, "Plan", "Esto es lo que ordenaré. Nada se mueve hasta que lo confirmes.")
        button(act, st, "Actualizar", self.refresh_plan, "secondary", 110).pack(side="right")
        button(act, st, "¿Por qué no mueve el resto?", self.show_skipped, "text", 210).pack(side="right", padx=(0, 6))
        stats = ctk.CTkFrame(page, fg_color="transparent")
        stats.pack(fill="x", pady=(0, 12))
        self.stat_move = self._stat(stats, "Para mover", 0, C.ACCENT)
        self.stat_stay = self._stat(stats, "Se quedan quietos", 1, C.TEXT)
        self.stat_size = self._stat(stats, "Tamaño a mover", 2, C.TEXT)
        bar = ctk.CTkFrame(page, fg_color="transparent")
        bar.pack(side="bottom", fill="x", pady=(10, 0))
        button(bar, st, "Todo", lambda: self.mark_all(True), "text", 70).pack(side="left")
        button(bar, st, "Ninguno", lambda: self.mark_all(False), "text", 90).pack(side="left")
        self.btn_move = button(bar, st, "Mover", self.move_checked, "primary", 220)
        self.btn_move.pack(side="right")
        self.plan_list = ItemList(page, st, "Todo en orden", "No hay nada que ordenar ahora mismo.")
        self.plan_list.pack(fill="both", expand=True)

    def refresh_plan(self, sync: bool = False) -> None:
        """Recalcula el plan. Por defecto en segundo plano mostrando esqueletos (la ventana no se congela)."""
        self._plan_token += 1
        token = self._plan_token
        self.plan_list.show_skeleton()
        self.btn_move.configure(state="disabled")

        def compute():
            conn = database.connect(self.db_path)  # cada hilo su propia conexión
            try:
                layout, inbox, prot = make_context(conn, self.layout_root)
                plan = build_plan(inbox, layout, prot, settle_seconds=60, rules=load_rules(conn))
            finally:
                conn.close()
            return token, plan, layout, inbox, prot

        if sync:
            self._apply_plan_result(compute())
            return

        def work():
            try:
                self.cmd_q.put(("plan_done", compute()))
            except Exception as e:  # noqa: BLE001 - se informa en pantalla
                self.cmd_q.put(("plan_error", str(e)))

        threading.Thread(target=work, daemon=True).start()

    def _apply_plan_result(self, result) -> None:
        token, plan, layout, inbox, prot = result
        if token != self._plan_token:
            return  # llegó un resultado viejo: ya se pidió otro
        self.layout, self.inbox, self.protection = layout, inbox, prot
        self.plan = plan
        self.unchecked.clear()
        self.plan_list.clear()
        if not plan.moves:
            self.plan_list.show_empty()
        for i, m in enumerate(plan.moves):
            glyph, color = theme.category_style(m.category)
            self.plan_list.add(
                str(i),
                os.path.basename(m.src),
                f"{where(m.src, m.dst)}   ·   {m.reason}",
                glyph,
                color,
                f"{m.confidence:.0%}",
                "green" if m.confidence >= 0.85 else "orange",
                check=True,
                on_toggle=self._plan_toggled,
            )
        self.stat_stay.configure(text=fmt_int(len(plan.skipped)))
        self._update_plan_counts()

    def _plan_toggled(self, key: str, value: bool) -> None:
        if value:
            self.unchecked.discard(key)
        else:
            self.unchecked.add(key)
        self._update_plan_counts()

    def show_skipped(self) -> None:
        d = Dialog(
            self, self.st, "Lo que se queda quieto", skipped_summary(self.plan.skipped), ok="Entendido", cancel=None
        )
        self.wait_window(d)

    def _update_plan_counts(self) -> None:
        chosen = [m for i, m in enumerate(self.plan.moves) if str(i) not in self.unchecked]
        self.stat_move.configure(text=fmt_int(len(chosen)))
        self.stat_size.configure(text=fmt_size(sum(m.size for m in chosen)))
        self.btn_move.configure(
            text=f"Mover {len(chosen)} archivo{'s' if len(chosen) != 1 else ''}",
            state="normal" if chosen else "disabled",
        )

    def mark_all(self, on: bool) -> None:
        self.unchecked = set() if on else {str(i) for i in range(len(self.plan.moves))}
        self.plan_list.set_all_checked(on)
        self._update_plan_counts()

    def move_checked(self) -> None:
        moves = [m for i, m in enumerate(self.plan.moves) if str(i) not in self.unchecked]
        if not moves:
            self._info("No hay nada marcado.", "")
            return
        if not self._ask(
            f"¿Mover {len(moves)} archivos?",
            "Quedan guardados en el Historial y puedes deshacerlo cuando quieras.",
            ok="Mover",
        ):
            return
        res = apply_plan(
            self.conn,
            Plan(moves, [], dry_run=False),
            self.layout,
            self.protection,
            self.inbox,
            kind="manual",
            note="ventana",
        )
        self._info(
            f"Listo: {res.done} movidos",
            f"{res.quarantined} duplicados a cuarentena · {len(res.skipped)} omitidos · {len(res.failed)} con error",
        )
        self.refresh_plan()
        self.refresh_history()

    # -------------------------------------------------------------- historial
    def _page_history(self, page) -> None:
        st, C = self.st, self.st.C
        act = header(page, st, "Historial", "De dónde a dónde se movió cada cosa. Todo se puede deshacer.")
        button(act, st, "Deshacer todo", self.undo_all, "danger", 130).pack(side="right", padx=(8, 0))
        button(act, st, "Último lote", self.undo_last, "secondary", 110).pack(side="right", padx=(8, 0))
        self.btn_undo_sel = button(act, st, "Deshacer selección", self.undo_selected, "secondary", 160)
        self.btn_undo_sel.pack(side="right")
        self.search_var = tk.StringVar()
        e = ctk.CTkEntry(
            page,
            textvariable=self.search_var,
            placeholder_text="🔍  Buscar por nombre…",
            placeholder_text_color=C.TEXT2,
            height=38,
            corner_radius=19,
            fg_color=C.FILL,
            border_width=0,
            font=st.body,
            text_color=C.TEXT,
        )
        e.pack(fill="x", pady=(0, 10))
        e.bind("<KeyRelease>", lambda _e: self.refresh_history())
        self.hist_list = ItemList(page, st, "Aún no hay movimientos", "Cuando Nimbo mueva algo, lo verás aquí.")
        self.hist_list.pack(fill="both", expand=True)

    def refresh_history(self) -> None:
        self.hist_list.clear()
        self.hist_batch.clear()
        self.hist_selected = None
        rows = history(self.conn, 120, self.search_var.get().strip() or None)
        if not rows:
            self.hist_list.show_empty()
            return
        for r in rows:
            key = str(r["id"])
            self.hist_batch[key] = r["batch_id"]
            glyph, color = ACTION_STYLE.get(r["action"], ("•", "#8E8E93"))
            label, kind = STATUS_BADGE.get(r["status"], (r["status"], "gray"))
            self.hist_list.add(
                key,
                os.path.basename(r["dst"]),
                f"{where(r['src'], r['dst'])}   ·   lote {r['batch_id']}   ·   {r['ts'].replace('T', ' ')[:16]}",
                glyph,
                color,
                label,
                kind,
                on_click=self._hist_click,
            )

    def _hist_click(self, key: str) -> None:
        if self.hist_selected:
            self.hist_list.set_selected(self.hist_selected, False)
        self.hist_selected = None if self.hist_selected == key else key
        if self.hist_selected:
            self.hist_list.set_selected(key, True)

    def _undo(self, **kw) -> None:
        r = undo(self.conn, **kw)
        self._info(f"Restaurados: {r.restored}", f"{len(r.missing)} ya no estaban · {len(r.failed)} con error")
        self.refresh_history()
        self.refresh_plan()

    def undo_selected(self) -> None:
        if not self.hist_selected:
            self._info("Toca un movimiento", "Selecciona uno de la lista para deshacer todo su lote.")
            return
        batch = self.hist_batch[self.hist_selected]
        if self._ask(f"¿Deshacer el lote {batch}?", "Cada archivo vuelve a donde estaba.", ok="Deshacer"):
            self._undo(batch_id=batch)

    def undo_last(self) -> None:
        if self._ask("¿Deshacer el último lote?", "Cada archivo vuelve a donde estaba.", ok="Deshacer"):
            self._undo()

    def undo_all(self) -> None:
        if self._ask(
            "¿Devolver TODO a su lugar?",
            "Se deshacen todos los movimientos del historial.",
            ok="Deshacer todo",
            destructive=True,
        ):
            self._undo(everything=True)

    # -------------------------------------------------------------- proyectos
    def _page_projects(self, page) -> None:
        st = self.st
        act = header(
            page,
            st,
            "Proyectos",
            "Los encuentro por su contenido (git, package.json…), aunque se llamen 1234567. Nada se mueve sin confirmar.",
        )
        button(act, st, "Todos los discos", lambda: self.find_projects(True), "secondary", 150).pack(
            side="right", padx=(8, 0)
        )
        button(act, st, "Buscar en mi usuario", lambda: self.find_projects(False), "primary", 180).pack(side="right")
        bar = ctk.CTkFrame(page, fg_color="transparent")
        bar.pack(side="bottom", fill="x", pady=(10, 0))
        rn = ctk.CTkFrame(bar, fg_color="transparent")
        rn.pack(side="left")
        self.proj_rename = IOSSwitch(rn, st, bg=st.C.BG)
        self.proj_rename.pack(side="left")
        ctk.CTkLabel(rn, text="Nombrar según el contenido", font=st.body, text_color=st.C.TEXT).pack(
            side="left", padx=10
        )
        self.btn_gather = button(bar, st, "Reunir en Proyectos", self.gather_checked, "primary", 220)
        self.btn_gather.pack(side="right")
        self.proj_list = ItemList(page, st, "Busca tus proyectos", "Pulsa «Buscar en mi usuario» para empezar.")
        self.proj_list.pack(fill="both", expand=True)
        self.proj_list.show_empty("Busca tus proyectos", "Pulsa «Buscar en mi usuario» para empezar.")

    def find_projects(self, all_drives: bool) -> None:
        self.toast("Buscando proyectos… puede tardar en discos grandes.")
        self.proj_list.show_skeleton()

        def work():
            conn = database.connect(self.db_path)
            try:
                _, _boxes, prot = make_context(conn, self.layout_root)
                roots = (fixed_drives() or [Path.home()]) if all_drives else [Path.home()]
                if self.layout_root:
                    roots = [Path(self.layout_root)]
                found = discover_projects(roots, prot)
            finally:
                conn.close()
            self.cmd_q.put(("projects_done", found))

        threading.Thread(target=work, daemon=True).start()

    def show_projects(self, found) -> None:
        self.projects = found
        self.proj_unchecked.clear()
        self.proj_list.clear()
        if not found:
            self.proj_list.show_empty("No encontré proyectos", "Prueba con «Todos los discos».")
        glyph, color = theme.category_style("proyecto")
        for i, p in enumerate(found):
            warn = (
                "tiene entorno virtual: no se moverá"
                if p.venvs
                else ("pistas débiles: no se moverá" if p.confidence != "alta" else "")
            )
            sub = f"{ellipsize(p.path, 70)}   ·   {', '.join(p.kinds)}   ·   {fmt_size(p.size)}"
            self.proj_list.add(
                str(i),
                p.name_guess + ("   (nombre confuso)" if p.cryptic else ""),
                sub,
                glyph,
                color,
                warn or None,
                "orange",
                check=True,
                on_toggle=self._proj_toggled,
            )
        self._update_gather()
        self.toast(f"{len(found)} proyectos encontrados.")

    def _proj_toggled(self, key: str, value: bool) -> None:
        self.proj_unchecked.discard(key) if value else self.proj_unchecked.add(key)
        self._update_gather()

    def _update_gather(self) -> None:
        n = len(self.projects) - len(self.proj_unchecked)
        self.btn_gather.configure(text=f"Reunir {max(n, 0)} en Proyectos", state="normal" if n > 0 else "disabled")

    def gather_checked(self) -> None:
        chosen = [p for i, p in enumerate(self.projects) if str(i) not in self.proj_unchecked]
        plan = plan_gather(chosen, self.layout.projects, self.protection, rename=bool(self.proj_rename.get()))
        if not plan.moves:
            self._info("Nada que mover", "Los marcados ya están en su sitio, protegidos u omitidos.")
            return
        if not self._ask(
            f"¿Reunir {len(plan.moves)} proyectos?",
            f"Van a {self.layout.projects}. Cada carpeta se renombra entera en el mismo disco, sin copiar ni borrar. "
            "Verifico que el contenido y git queden idénticos y, si algo falla, lo devuelvo solo.",
            ok="Reunir",
        ):
            return
        res = execute_gather(self.conn, plan, log=lambda m: None)
        self._info(
            f"Listo: {res.moved} verificados",
            f"{len(res.reverted)} revertidos solos · {len(res.failed)} fallidos (sin cambios)",
        )
        self.refresh_history()

    # --------------------------------------------------------------------- IA
    def _page_ai(self, page) -> None:
        st = self.st
        act = header(
            page, st, "Sugerencias", "La IA local solo sugiere para lo ambiguo. Nada se mueve sin tu aprobación."
        )
        button(act, st, "Pedir sugerencias", self.ask_ai, "primary", 170).pack(side="right")
        bar = ctk.CTkFrame(page, fg_color="transparent")
        bar.pack(side="bottom", fill="x", pady=(10, 0))
        button(bar, st, "Rechazar", lambda: self.resolve_ai(False), "secondary", 130).pack(side="left")
        button(bar, st, "Aceptar y mover", lambda: self.resolve_ai(True), "primary", 190).pack(side="right")
        self.ai_list = ItemList(page, st, "Sin sugerencias pendientes", "Pulsa «Pedir sugerencias» cuando quieras.")
        self.ai_list.pack(fill="both", expand=True)

    def refresh_ai(self) -> None:
        self.ai_list.clear()
        self.ai_selected.clear()
        rows = ailib.pending(self.conn)
        if not rows:
            self.ai_list.show_empty()
            return
        glyph, color = theme.category_style("ia")
        for r in rows:
            self.ai_list.add(
                str(r["id"]),
                os.path.basename(r["src"]),
                f"→ {r['label']}   ·   {r['reason'] or ''}",
                glyph,
                color,
                f"{(r['confidence'] or 0):.0%}",
                "green" if (r["confidence"] or 0) >= 0.8 else "orange",
                on_click=self._ai_click,
            )

    def _ai_click(self, key: str) -> None:
        i = int(key)
        sel = i in self.ai_selected
        self.ai_selected.discard(i) if sel else self.ai_selected.add(i)
        self.ai_list.set_selected(key, not sel)

    def ask_ai(self) -> None:
        conf, problem = ailib.ai_status()
        if not conf:
            if self._ask("La IA no está lista", f"{problem}", ok="Ir a Ajustes", kind="warning"):
                self.show("ajustes")
            return
        self.toast("Consultando a la IA… puede tardar unos segundos.")
        self.ai_list.show_skeleton()

        def work():
            conn = database.connect(self.db_path)
            errors: list[str] = []
            try:
                layout, inbox, prot = make_context(conn, self.layout_root)
                plan = build_plan(inbox, layout, prot, rules=load_rules(conn))
                ailib.make_suggestions(conn, ailib.collect_candidates(plan), layout, conf, errors=errors)
            finally:
                conn.close()
            self.cmd_q.put(("ai_error" if errors else "ai_done", errors[0] if errors else None))

        threading.Thread(target=work, daemon=True).start()

    def resolve_ai(self, accept: bool) -> None:
        ids = sorted(self.ai_selected)
        if not ids:
            self._info("Toca las sugerencias", "Selecciona una o varias de la lista.")
            return
        ailib.resolve(self.conn, ids, accept, self.layout, self.protection, self.inbox)
        self.refresh_ai()
        self.refresh_history()

    # -------------------------------------------------------------- vigilante
    def _page_watch(self, page) -> None:
        st, C = self.st, self.st.C
        header(page, st, "Vigilante", "Ordena solo lo nuevo que llegue a Descargas y Escritorio.")
        c1 = card(page, st)
        c1.pack(fill="x", pady=(0, 10))
        r1 = ctk.CTkFrame(c1, fg_color="transparent")
        r1.pack(fill="x", padx=20, pady=16)
        t = ctk.CTkFrame(r1, fg_color="transparent")
        t.pack(side="left")
        ctk.CTkLabel(t, text="Vigilar mis carpetas", font=st.headline, text_color=C.TEXT, anchor="w").pack(anchor="w")
        self.watch_status = ctk.CTkLabel(t, text="● En pausa", font=st.small, text_color=C.TEXT2, anchor="w")
        self.watch_status.pack(anchor="w")
        self.watch_switch = IOSSwitch(r1, st, command=self.toggle_watch)
        self.watch_switch.pack(side="right")
        c2 = card(page, st)
        c2.pack(fill="x", pady=(0, 10))
        r2 = ctk.CTkFrame(c2, fg_color="transparent")
        r2.pack(fill="x", padx=20, pady=16)
        t2 = ctk.CTkFrame(r2, fg_color="transparent")
        t2.pack(side="left")
        ctk.CTkLabel(t2, text="Mover de verdad", font=st.headline, text_color=C.TEXT, anchor="w").pack(anchor="w")
        ctk.CTkLabel(
            t2,
            text="Apagado: solo simula y te cuenta lo que haría. Encendido: mueve y lo guarda en el Historial.",
            font=st.small,
            text_color=C.TEXT2,
            anchor="w",
            wraplength=520,
            justify="left",
        ).pack(anchor="w")
        self.apply_switch = IOSSwitch(r2, st, command=self.save_apply)
        self.apply_switch.pack(side="right")
        if cfg.load_user_config().get("watch_apply", False):
            self.apply_switch.select()
        ctk.CTkLabel(page, text="Actividad", font=st.headline, text_color=C.TEXT2, anchor="w").pack(
            anchor="w", pady=(6, 4)
        )
        self.log_box = ctk.CTkTextbox(
            page, state="disabled", fg_color=C.CARD, corner_radius=16, font=st.mono, text_color=C.TEXT, border_width=0
        )
        self.log_box.pack(fill="both", expand=True)

    def _paint_watch_status(self, on: bool) -> None:
        C = self.st.C
        real = bool(self.apply_switch.get())
        if not on:
            text, color = "● En pausa", C.TEXT2
        elif real:
            text, color = "● Vigilando · moviendo", C.GREEN
        else:
            text, color = "● Vigilando · solo simula", C.ORANGE
        for lab in (self.watch_status, self.side_status):
            lab.configure(text=text, text_color=color)

    def save_apply(self) -> None:
        cfg.save_user_config({"watch_apply": bool(self.apply_switch.get())})
        self.log("Modo: " + ("MOVIENDO de verdad" if self.apply_switch.get() else "solo simulación"))
        self.toast("Moviendo de verdad: todo queda en el Historial." if self.apply_switch.get() else "Solo simulación.")
        self._paint_watch_status(
            bool(self.watch_thread and self.watch_thread.is_alive() and not self.stop_event.is_set())
        )

    def log(self, text: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def toggle_watch(self) -> None:
        if self.watch_switch.get():
            if self.watch_thread and self.watch_thread.is_alive():
                return
            self.stop_event.clear()
            self.watch_thread = threading.Thread(target=self._watch_worker, daemon=True)
            self.watch_thread.start()
            self.log("Vigilante iniciado.")
            self._paint_watch_status(True)
        else:
            self.stop_event.set()
            self.log("Vigilante detenido.")
            self._paint_watch_status(False)

    def _sleep(self, seconds: float) -> None:
        self.stop_event.wait(seconds)

    def _watch_worker(self) -> None:
        conn = database.connect(self.db_path)  # cada hilo su propia conexión
        try:
            layout, inbox, prot = make_context(conn, self.layout_root)
            watch(
                conn,
                inbox,
                layout,
                prot,
                apply=lambda: bool(cfg.load_user_config().get("watch_apply", False)),
                interval=float(cfg.load_user_config().get("interval", 30)),
                settle=float(cfg.load_user_config().get("settle", 60)),
                log=self.log_q.put,
                should_stop=self.stop_event.is_set,
                notify=lambda m: self.cmd_q.put(("notify", m)),
                sleep=self._sleep,
            )
        finally:
            conn.close()

    # --------------------------------------------------------------- ajustes
    def _page_settings(self, page) -> None:
        st, C = self.st, self.st.C
        header(page, st, "Ajustes", "Apariencia, carpetas y servicios.")
        scroll = ctk.CTkScrollableFrame(page, fg_color="transparent", corner_radius=0)
        scroll.pack(fill="both", expand=True)
        self.settings_scroll = scroll

        ap = card(scroll, st)
        ap.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(ap, text="Apariencia", font=st.headline, text_color=C.TEXT, anchor="w").pack(
            anchor="w", padx=18, pady=(14, 6)
        )
        seg = Segmented(
            ap,
            st,
            ["Sistema", "Claro", "Oscuro"],
            {"system": "Sistema", "light": "Claro", "dark": "Oscuro"}[self.th["mode"]],
            self._set_mode,
        )
        seg.pack(anchor="w", padx=18)
        ctk.CTkLabel(ap, text="Color de acento", font=st.small, text_color=C.TEXT2, anchor="w").pack(
            anchor="w", padx=18, pady=(12, 4)
        )
        sw = ctk.CTkFrame(ap, fg_color="transparent")
        sw.pack(anchor="w", padx=14, pady=(0, 16))
        for hexv in theme.PRESETS.values():
            on = hexv.upper() == self.th["accent"].upper()
            ctk.CTkButton(
                sw,
                text="✓" if on else "",
                width=32,
                height=32,
                corner_radius=16,
                fg_color=hexv,
                hover_color=hexv,
                text_color="#FFFFFF",
                font=st.headline,
                border_width=0,
                command=lambda h=hexv: self._set_accent(h),
            ).pack(side="left", padx=4)

        self.prot_editor = ListEditor(
            scroll,
            st,
            "extra_protected",
            "Carpetas protegidas",
            "Nunca se tocan. Steam, proyectos y carpetas del sistema ya están protegidos.",
            self.reload_context,
        )
        self.prot_editor.pack(fill="x", pady=(0, 12))
        self.inbox_editor = ListEditor(
            scroll,
            st,
            "inbox",
            "Carpetas que vigilo",
            "Si no agregas ninguna, uso Descargas y Escritorio.",
            self.reload_context,
        )
        self.inbox_editor.pack(fill="x", pady=(0, 12))

        sv = card(scroll, st)
        sv.pack(fill="x", pady=(0, 12))
        r = ctk.CTkFrame(sv, fg_color="transparent")
        r.pack(fill="x", padx=18, pady=14)
        ctk.CTkLabel(r, text="Iniciar con Windows", font=st.headline, text_color=C.TEXT).pack(side="left")
        self.auto_switch = IOSSwitch(r, st, command=self.save_autostart)
        self.auto_switch.pack(side="right")
        if autostart.is_enabled():
            self.auto_switch.select()

        self._build_ai_card(scroll)

    def _set_mode(self, label: str) -> None:
        mode = {"Sistema": "system", "Claro": "light", "Oscuro": "dark"}[label]
        self.th = theme.save(mode=mode)
        ctk.set_appearance_mode(mode)
        self.update_idletasks()
        self.st.redraw_all()

    def _set_accent(self, hexv: str) -> None:
        self.th = theme.save(accent=hexv)
        self.current = "ajustes"
        self.rebuild()

    def save_autostart(self) -> None:
        if not autostart.set_enabled(bool(self.auto_switch.get())):
            self._info("Inicio con Windows", "No se pudo cambiar (solo funciona en Windows).", kind="warning")
            self.auto_switch.deselect()

    # ------------------------------------------------------------ tarjeta de IA
    PROV_LABELS = {"Gemini (API)": "gemini", "Local": "local"}

    def _entry(self, parent, placeholder: str, width: int, show: str | None = None) -> ctk.CTkEntry:
        C = self.st.C
        return ctk.CTkEntry(
            parent,
            width=width,
            height=40,
            corner_radius=12,
            fg_color=C.FILL,
            border_width=0,
            placeholder_text=placeholder,
            placeholder_text_color=C.TEXT2,
            font=self.st.body,
            text_color=C.TEXT,
            show=show or "",
        )

    def _build_ai_card(self, scroll) -> None:
        st, C = self.st, self.st.C
        saved = cfg.load_user_config().get("ai") or {}
        self.ai_prov: str = (
            "local"
            if saved.get("provider") == "local" or (saved.get("url") and not saved.get("provider"))
            else "gemini"
        )
        ai = card(scroll, st)
        ai.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(
            ai, text="Inteligencia artificial (opcional)", font=st.headline, text_color=C.TEXT, anchor="w"
        ).pack(anchor="w", padx=18, pady=(14, 0))
        ctk.CTkLabel(
            ai,
            text="Sugiere en qué carpeta va lo que no sé ubicar. Tú apruebas cada movimiento.",
            font=st.small,
            text_color=C.TEXT2,
            anchor="w",
            wraplength=600,
            justify="left",
        ).pack(anchor="w", padx=18, pady=(0, 10))
        inv = {v: k for k, v in self.PROV_LABELS.items()}
        self.ai_provider = Segmented(ai, st, list(self.PROV_LABELS), inv[self.ai_prov], self._ai_provider_changed)
        self.ai_provider.pack(anchor="w", padx=18)
        self.ai_hint = ctk.CTkLabel(
            ai, text="", font=st.small, text_color=C.TEXT2, anchor="w", wraplength=620, justify="left"
        )
        self.ai_hint.pack(anchor="w", padx=18, pady=(8, 6))
        self.ai_fields = ctk.CTkFrame(ai, fg_color="transparent", height=1)
        self.ai_fields.pack(fill="x", padx=18)
        self.ai_key = self._entry(self.ai_fields, "Pega tu API key de Gemini", 420, show="•")
        self.ai_url = self._entry(self.ai_fields, "http://localhost:11434/v1", 420)
        self.ai_model = self._entry(self.ai_fields, "modelo (ej. llama3.1)", 420)
        self.ai_mode_row = ctk.CTkFrame(ai, fg_color="transparent")
        ctk.CTkLabel(self.ai_mode_row, text="Qué se envía", font=st.small, text_color=C.TEXT2).pack(
            side="left", padx=(0, 12)
        )
        cur = "Nombres + contenido" if saved.get("mode") == "content" else "Solo nombres"
        self.ai_privacy = Segmented(self.ai_mode_row, st, ["Solo nombres", "Nombres + contenido"], cur, lambda _v: None)
        self.ai_privacy.pack(side="left")
        row = ctk.CTkFrame(ai, fg_color="transparent")
        row.pack(fill="x", padx=18, pady=(14, 6))
        self.ai_main_btn = button(row, st, "Conectar", self.ai_primary, "primary", 130)
        self.ai_main_btn.pack(side="left")
        self.ai_test_btn = button(row, st, "Probar conexión", self.test_ai, "secondary", 160)
        self.ai_msg = ctk.CTkLabel(
            ai, text="", font=st.small, text_color=C.TEXT2, anchor="w", wraplength=620, justify="left"
        )
        self.ai_msg.pack(anchor="w", padx=18, pady=(0, 14))
        if saved.get("url") and self.ai_prov == "local":
            self.ai_url.insert(0, saved["url"])
        if saved.get("model") and self.ai_prov == "local":
            self.ai_model.insert(0, saved["model"])
        self._ai_layout()
        self._ai_show_status()

    def _ai_layout(self) -> None:
        for w in (self.ai_key, self.ai_url, self.ai_model):
            w.pack_forget()
        self.ai_mode_row.pack_forget()
        if self.ai_prov == "gemini":
            self.ai_key.configure(
                placeholder_text="••••••••  clave guardada (escribe otra para cambiarla)"
                if keystore.has_key()
                else "Pega tu API key de Gemini"
            )
            self.ai_key.pack(anchor="w", pady=(0, 6))
            self.ai_mode_row.pack(fill="x", padx=18, pady=(8, 0), after=self.ai_fields)
            self.ai_hint.configure(
                text="Pega tu API key (la creas en Google AI Studio) y pulsa Conectar: se valida sola "
                "y elige el modelo. Se guarda cifrada con Windows."
            )
            self.ai_main_btn.configure(text="Conectar")
            self.ai_test_btn.pack_forget()
        else:
            self.ai_url.pack(anchor="w", pady=(0, 6))
            self.ai_model.pack(anchor="w", pady=(0, 6))
            self.ai_hint.configure(text="Servidor en tu propio PC (Ollama, LM Studio). Nada sale de tu equipo.")
            self.ai_main_btn.configure(text="Guardar")
            self.ai_test_btn.pack(side="left", padx=8)

    def _ai_provider_changed(self, label: str) -> None:
        self.ai_prov = self.PROV_LABELS[label]
        self._ai_layout()
        self._ai_show_status()

    def _ai_show_status(self) -> None:
        conf, problem = ailib.ai_status()
        C = self.st.C
        if conf and conf["provider"] == self.ai_prov:
            where_ = "en tu PC" if not conf["remote"] else "con Google"
            self.ai_msg.configure(text=f"✓ Lista: {conf['model']} {where_}", text_color=C.GREEN)
        else:
            self.ai_msg.configure(text="", text_color=C.TEXT2)

    def ai_primary(self) -> None:
        if self.ai_prov == "gemini":
            self.connect_gemini()
        else:
            self.save_local_ai()

    def connect_gemini(self) -> None:
        typed = self.ai_key.get().strip()
        key = typed or keystore.get_key() or ""
        if not key:
            self.ai_msg.configure(text="Pega primero tu API key de Gemini.", text_color=self.st.C.ORANGE)
            return
        mode = "content" if self.ai_privacy.current == "Nombres + contenido" else "names"
        saved = cfg.load_user_config().get("ai") or {}
        if not (saved.get("consent") and saved.get("provider") == "gemini"):
            sends = (
                "el NOMBRE de los archivos que no sé ubicar"
                if mode == "names"
                else "el nombre y el inicio del contenido (hasta 1200 caracteres) de los archivos que no sé ubicar"
            )
            if not self._ask(
                "¿Permitir el envío a Gemini?",
                f"Para sugerir carpetas enviaré {sends} a Google por internet.\n\n"
                "Los archivos con nombres sensibles (contraseñas, claves, documentos de identidad) "
                "nunca se envían. Puedes retirar el permiso cuando quieras.",
                ok="Permitir y conectar",
                kind="warning",
            ):
                return
        self.ai_msg.configure(text="Validando tu clave…", text_color=self.st.C.TEXT2)
        self.ai_main_btn.configure(state="disabled")

        def work():
            try:
                model = ailib.connect(key)
                self.cmd_q.put(("ai_connected", (key if typed else None, model, mode)))
            except ailib.AIError as e:
                self.cmd_q.put(("ai_test", (False, str(e))))

        threading.Thread(target=work, daemon=True).start()

    def _gemini_connected(self, payload) -> None:
        typed_key, model, mode = payload
        ai = dict(cfg.load_user_config().get("ai") or {})
        ai.update({"provider": "gemini", "model": model, "mode": mode, "consent": True})
        ai.pop("url", None)
        cfg.save_user_config({"ai": ai})
        if typed_key:
            if keystore.set_key(typed_key):
                self.ai_key.delete(0, "end")
            else:
                self._info(
                    "Clave no guardada",
                    "Este sistema no puede cifrarla: usa la variable NIMBO_API_KEY.",
                    kind="warning",
                )
        self.ai_main_btn.configure(state="normal")
        self._ai_layout()
        self.ai_msg.configure(text=f"✓ Conectada con Gemini (modelo {model})", text_color=self.st.C.GREEN)
        self.toast("Gemini conectada. Ya puedes pedir sugerencias.", kind="success")

    def save_local_ai(self) -> None:
        ai = dict(cfg.load_user_config().get("ai") or {})
        ai.update({"provider": "local", "url": self.ai_url.get().strip() or ailib.PROVIDERS["local"]["url"],
                   "model": self.ai_model.get().strip(), "mode": "content"})  # fmt: skip
        ai.pop("consent", None)
        cfg.save_user_config({"ai": ai})
        self._ai_show_status()
        self.toast("Servidor local guardado.", kind="success")

    def test_ai(self) -> None:
        conf, problem = ailib.ai_status()
        if not conf:
            self.ai_msg.configure(text=problem or "", text_color=self.st.C.ORANGE)
            return
        self.ai_msg.configure(text="Probando conexión…", text_color=self.st.C.TEXT2)

        def work():
            try:
                reply = ailib.test_connection(conf)
                self.cmd_q.put(("ai_test", (True, f"✓ Conectado. La IA respondió: {reply}")))
            except ailib.AIError as e:
                self.cmd_q.put(("ai_test", (False, str(e))))

        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------- bandeja y cierre
    def _start_tray(self) -> None:
        if sys.platform != "win32":  # el ícono de bandeja es una función de Windows; en otros sistemas no se crea
            self.tray = None
            return
        try:
            import pystray
            from PIL import Image, ImageDraw

            img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            acc = self.th["accent"]
            d.rounded_rectangle((2, 2, 62, 62), 16, fill=acc)
            d.line((18, 33, 28, 43, 46, 22), fill="white", width=7)
            menu = pystray.Menu(
                pystray.MenuItem("Abrir Nimbo", lambda: self.cmd_q.put(("show", None)), default=True),
                pystray.MenuItem(
                    "Vigilando",
                    lambda: self.cmd_q.put(("toggle", None)),
                    checked=lambda item: bool(
                        self.watch_thread and self.watch_thread.is_alive() and not self.stop_event.is_set()
                    ),
                ),
                pystray.MenuItem("Salir", lambda: self.cmd_q.put(("quit", None))),
            )
            self.tray = pystray.Icon("Nimbo", img, "Nimbo", menu)
            # hilo daemon: si la bandeja se atasca, nunca impide que el proceso termine
            threading.Thread(target=self.tray.run, name="nimbo-tray", daemon=True).start()
        except Exception:  # sin pystray/Pillow (o sin entorno gráfico): sigue sin bandeja
            self.tray = None

    def _poll(self) -> None:
        while True:
            try:
                self.log(self.log_q.get_nowait())
            except queue.Empty:
                break
        while True:
            try:
                cmd, payload = self.cmd_q.get_nowait()
            except queue.Empty:
                break
            if cmd == "show":
                self.deiconify()
                self.lift()
            elif cmd == "toggle":
                self.watch_switch.toggle()
                self.toggle_watch()
            elif cmd == "quit":
                self.quit_app()
                return
            elif cmd == "notify":
                if self.tray:
                    try:
                        self.tray.notify(payload, "Nimbo")
                    except Exception:  # la notificación es opcional
                        log.debug("no se pudo mostrar la notificación", exc_info=True)
                self.refresh_history()
            elif cmd == "plan_done":
                self._apply_plan_result(payload)
            elif cmd == "plan_error":
                self.plan_list.show_empty("No pude revisar las carpetas", str(payload))
            elif cmd == "projects_done":
                self.show_projects(payload)
            elif cmd == "ai_connected":
                self._gemini_connected(payload)
            elif cmd == "ai_test":
                self.ai_main_btn.configure(state="normal")
                ok, text = payload
                self.ai_msg.configure(text=text, text_color=self.st.C.GREEN if ok else self.st.C.RED)
            elif cmd == "ai_error":
                self.refresh_ai()
                self._info("La IA no respondió", str(payload), kind="warning")
            elif cmd == "ai_done":
                self.refresh_ai()
                self.toast("Sugerencias listas. Revísalas y aprueba.")
        self.after(500, self._poll)

    def on_close(self) -> None:
        if self.tray:
            self.withdraw()  # sigue vigilando en la bandeja
        else:
            self.quit_app()

    def quit_app(self) -> None:
        self.stop_event.set()
        if self.tray:
            try:
                self.tray.stop()
            except Exception:
                log.debug("error al cerrar la bandeja", exc_info=True)
        self.conn.close()
        self.destroy()


def run(start_hidden: bool = False, layout_root: str | None = None, db: str | None = None) -> int:
    cfg.migrate_legacy_data()
    lock = socket.socket()
    try:
        lock.bind(("127.0.0.1", LOCK_PORT))  # una sola copia a la vez
    except OSError:
        print("Nimbo ya está abierto (mira la bandeja del sistema).")
        return 1
    App(start_hidden=start_hidden, layout_root=layout_root, db=db).mainloop()
    return 0
