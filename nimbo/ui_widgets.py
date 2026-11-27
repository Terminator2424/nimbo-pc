"""Componentes visuales reutilizables (estilo iOS): tarjetas, botones, listas, diálogos."""

from __future__ import annotations

import sys
import tkinter as tk
from collections.abc import Callable
from tkinter import font as tkfont
from typing import Any, Literal

import customtkinter as ctk

from . import theme


class Style:
    """Paleta + fuentes. Se crea después de la ventana principal (las fuentes lo necesitan)."""

    def __init__(self, accent: str):
        self.C = theme.palette(accent)
        fam = theme.pick_font_family(set(tkfont.families()))
        mono = "Cascadia Mono" if "Cascadia Mono" in tkfont.families() else "Consolas"
        self.family = fam
        self.large = ctk.CTkFont(family=fam, size=28, weight="bold")
        self.title = ctk.CTkFont(family=fam, size=17, weight="bold")
        self.headline = ctk.CTkFont(family=fam, size=13, weight="bold")
        self.body = ctk.CTkFont(family=fam, size=13)
        self.small = ctk.CTkFont(family=fam, size=12)
        self.tiny = ctk.CTkFont(family=fam, size=11, weight="bold")
        self.stat = ctk.CTkFont(family=fam, size=30, weight="bold")
        self.glyph = ctk.CTkFont(family=fam, size=16, weight="bold")
        self.mono = ctk.CTkFont(family=mono, size=12)
        self._registered: list = []

    def register(self, widget) -> None:
        self._registered.append(widget)

    def redraw_all(self) -> None:
        """Los widgets dibujados a mano no siguen solos el modo claro/oscuro: se redibujan aquí."""
        for w in list(self._registered):
            try:
                w.redraw()
            except tk.TclError:
                self._registered.remove(w)


def resolve(color) -> str:
    """Par (claro, oscuro) -> el color que toca según el modo actual."""
    if isinstance(color, str):
        return color
    return color[1] if ctk.get_appearance_mode() == "Dark" else color[0]


def ellipsize(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


def button(
    parent, st: Style, text: str, command: Callable, kind: str = "secondary", width: int = 0, **kw
) -> ctk.CTkButton:
    C = st.C
    styles: dict[str, dict[str, Any]] = {
        "primary": {"fg_color": C.ACCENT, "hover_color": C.ACCENT_HOVER, "text_color": "#FFFFFF"},
        "secondary": {"fg_color": C.FILL, "hover_color": C.SEP, "text_color": C.ACCENT},
        "text": {"fg_color": "transparent", "hover_color": C.FILL, "text_color": C.ACCENT},
        "danger": {"fg_color": C.RED_SOFT, "hover_color": C.RED_SOFT, "text_color": C.RED},
        "plain": {"fg_color": "transparent", "hover_color": C.FILL, "text_color": C.TEXT},
    }
    extra = {"width": width} if width else {}
    return ctk.CTkButton(
        parent,
        text=text,
        command=command,
        height=36,
        corner_radius=18,
        font=st.headline,
        border_width=0,
        **styles[kind],
        **extra,
        **kw,
    )


def card(parent, st: Style, **kw) -> ctk.CTkFrame:
    return ctk.CTkFrame(parent, fg_color=st.C.CARD, corner_radius=16, border_width=0, **kw)


def header(parent, st: Style, title: str, subtitle: str = "") -> ctk.CTkFrame:
    """Título grande a la izquierda; devuelve el marco de acciones (derecha)."""
    row = ctk.CTkFrame(parent, fg_color="transparent")
    row.pack(fill="x", pady=(2, 14))
    left = ctk.CTkFrame(row, fg_color="transparent")
    left.pack(side="left", fill="x", expand=True)
    ctk.CTkLabel(left, text=title, font=st.large, text_color=st.C.TEXT, anchor="w").pack(anchor="w")
    if subtitle:
        ctk.CTkLabel(
            left, text=subtitle, font=st.body, text_color=st.C.TEXT2, anchor="w", justify="left", wraplength=620
        ).pack(anchor="w", pady=(2, 0))
    actions = ctk.CTkFrame(row, fg_color="transparent", height=1)  # height=1: un marco vacío mediría 200 px
    actions.pack(side="right", anchor="n")
    return actions


def badge(parent, st: Style, text: str, kind: str = "accent") -> ctk.CTkLabel:
    C = st.C
    fg, tc = {
        "accent": (C.ACCENT_SOFT, C.ACCENT),
        "green": (C.GREEN_SOFT, C.GREEN),
        "red": (C.RED_SOFT, C.RED),
        "orange": (C.ORANGE_SOFT, C.ORANGE),
        "gray": (C.GRAY_SOFT, C.TEXT2),
    }[kind]
    return ctk.CTkLabel(parent, text=f" {text} ", font=st.tiny, text_color=tc, fg_color=fg, corner_radius=10, height=22)


def _wheel_dispatch(event, delta: int | None = None) -> None:
    """Lleva la rueda a la ItemList que está bajo el puntero. Si no hay ninguna, no hace nada.

    Importante: NO usar bind_all/unbind_all por widget. Esos reemplazan o borran el enlace global de la rueda,
    y CustomTkinter lo usa para sus paneles con scroll (Ajustes dejaba de responder al mouse).
    """
    try:
        w = event.widget.winfo_containing(event.x_root, event.y_root) or event.widget
    except (tk.TclError, KeyError):
        return
    while w is not None:
        if isinstance(w, ItemList):
            w._on_wheel(event, delta)
            return
        w = getattr(w, "master", None)


def _install_wheel_dispatch(top) -> None:
    if getattr(top, "_ordena_wheel", False):
        return
    top._ordena_wheel = True
    top.bind_all("<MouseWheel>", _wheel_dispatch, add="+")
    top.bind_all("<Button-4>", lambda e: _wheel_dispatch(e, 120), add="+")
    top.bind_all("<Button-5>", lambda e: _wheel_dispatch(e, -120), add="+")


class ItemList(ctk.CTkFrame):
    """Lista de filas dibujada en UN solo lienzo (rápida y sin parpadeos).

    Antes cada fila eran ~8 widgets; con cientos de filas Windows pintaba cuadros negros mientras cargaba.
    Ahora solo se dibujan las filas visibles (virtualización), y hay estados «vacío» y «cargando» (esqueletos).
    """

    ROW_H, GAP, TILE = 66, 8, 36

    def __init__(self, master, st: Style, empty_title: str = "Todo en orden", empty_text: str = ""):
        super().__init__(master, fg_color="transparent", corner_radius=0)
        self.st = st
        self.rows: dict[str, dict] = {}
        self.items: list[dict] = []
        self._offset = 0.0
        self._mode = "items"  # items | empty | skeleton
        self._empty = (empty_title, empty_text)
        self._phase = 0
        self._job: str | None = None
        self._dirty = False
        self._fonts: dict[str, tkfont.Font] = {}
        self._dpi = 1.0
        self.canvas = tk.Canvas(self, highlightthickness=0, bd=0)
        self.sb = ctk.CTkScrollbar(
            self,
            command=self._yview,
            width=12,
            corner_radius=6,
            fg_color="transparent",
            button_color=st.C.TEXT2,
            button_hover_color=st.C.TEXT,
        )
        self.canvas.pack(side="left", fill="both", expand=True)
        self._sb_shown = False
        self.canvas.bind("<Configure>", lambda _e: self._schedule())
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Destroy>", lambda _e: self._stop_pulse())
        st.register(self)
        _install_wheel_dispatch(self.winfo_toplevel())

    # ----------------------------------------------------------- medidas y fuentes
    def _mk(self) -> None:
        sc = max(self.winfo_fpixels("1i") / 96.0, 0.5)
        if abs(sc - self._dpi) < 0.01 and self._fonts:
            return
        self._dpi = sc
        fam = self.st.family
        spec: dict[str, tuple[int, Literal["normal", "bold"]]] = {
            "title": (17, "bold"),
            "head": (13, "bold"),
            "small": (12, "normal"),
            "tiny": (11, "bold"),
            "glyph": (15, "bold"),
            "big": (34, "bold"),
        }
        self._fonts = {k: tkfont.Font(family=fam, size=-round(v[0] * sc), weight=v[1]) for k, v in spec.items()}

    def _px(self, v: float) -> float:
        return v * self._dpi

    @property
    def _step(self) -> float:
        return self._px(self.ROW_H + self.GAP)

    def _total(self) -> float:
        return max(len(self.items) * self._step - self._px(self.GAP), 0)

    # ------------------------------------------------------------------- API
    def clear(self) -> None:
        self._stop_pulse()
        self.items.clear()
        self.rows.clear()
        self._offset = 0.0
        self._mode = "items"
        self._schedule()

    def show_empty(self, title: str | None = None, text: str | None = None) -> None:
        self._stop_pulse()
        self._empty = (title or self._empty[0], text if text is not None else self._empty[1])
        self._mode = "empty"
        self._schedule()

    def show_skeleton(self) -> None:
        self.clear()
        self._mode = "skeleton"
        self._schedule()
        self._job = self.after(650, self._pulse)

    def add(
        self,
        key: str,
        title: str,
        subtitle: str = "",
        glyph: str = "•",
        tile: str = "#8E8E93",
        badge_text: str | None = None,
        badge_kind: str = "accent",
        check: bool | None = None,
        on_toggle: Callable[[str, bool], None] | None = None,
        on_click: Callable[[str], None] | None = None,
        selected: bool = False,
    ) -> None:
        if self._mode != "items":
            self._stop_pulse()
            self._mode = "items"
        item = {
            "key": key,
            "title": title,
            "subtitle": subtitle,
            "glyph": glyph,
            "tile": tile,
            "badge": badge_text,
            "kind": badge_kind,
            "check": check,
            "on_toggle": on_toggle,
            "on_click": on_click,
            "selected": selected,
        }
        self.items.append(item)
        self.rows[key] = item
        self._schedule()

    def set_checked(self, key: str, value: bool) -> None:
        it = self.rows.get(key)
        if it and it["check"] is not None:
            it["check"] = value
            self._schedule()

    def set_all_checked(self, value: bool) -> None:
        for it in self.items:
            if it["check"] is not None:
                it["check"] = value
        self._schedule()

    def set_selected(self, key: str, value: bool) -> None:
        it = self.rows.get(key)
        if it:
            it["selected"] = value
            self._schedule()

    def redraw(self) -> None:
        self._paint()

    # ------------------------------------------------------------ desplazamiento
    def _view_h(self) -> float:
        return max(self.canvas.winfo_height(), 1)

    def _clamp(self) -> None:
        self._offset = min(max(self._offset, 0.0), max(self._total() - self._view_h(), 0.0))

    def _yview(self, *args) -> None:
        total = max(self._total(), 1)
        if args and args[0] == "moveto":
            self._offset = float(args[1]) * total
        elif args and args[0] == "scroll":
            unit = self._view_h() * 0.9 if args[2] == "pages" else self._step * 0.6
            self._offset += int(args[1]) * unit
        self._clamp()
        self._paint()

    def _on_wheel(self, e, delta: int | None = None) -> None:
        d = delta if delta is not None else e.delta
        self._offset -= (d / 120.0) * self._step * 0.7
        self._clamp()
        self._paint()

    # ----------------------------------------------------------------- eventos
    def _hit(self, y: float) -> int | None:
        yy = y + self._offset
        idx = int(yy // self._step)
        if 0 <= idx < len(self.items) and (yy - idx * self._step) <= self._px(self.ROW_H):
            return idx
        return None

    def _on_motion(self, e) -> None:
        idx = self._hit(e.y) if self._mode == "items" else None
        it = self.items[idx] if idx is not None else None
        self.canvas.configure(cursor="hand2" if it and (it["on_click"] or it["check"] is not None) else "")

    def _on_click(self, e) -> None:
        if self._mode != "items":
            return
        idx = self._hit(e.y)
        if idx is None:
            return
        it = self.items[idx]
        in_check = e.x < self._px(16 + 22 + 10)
        if it["check"] is not None and in_check:
            it["check"] = not it["check"]
            if it["on_toggle"]:
                it["on_toggle"](it["key"], it["check"])
            self._paint()
        elif it["on_click"]:
            it["on_click"](it["key"])

    # ------------------------------------------------------------------ dibujo
    def _schedule(self) -> None:
        if not self._dirty:
            self._dirty = True
            self.after_idle(self._flush)

    def _flush(self) -> None:
        self._dirty = False
        try:
            self._paint()
        except tk.TclError:
            pass  # la ventana se cerró mientras tanto

    def _stop_pulse(self) -> None:
        if self._job:
            try:
                self.after_cancel(self._job)
            except (tk.TclError, ValueError):
                pass
            self._job = None

    def _pulse(self) -> None:
        if self._mode != "skeleton":
            return
        self._phase ^= 1
        C = self.st.C
        self.canvas.itemconfig("skelbar", fill=resolve(C.SEP if self._phase else C.FILL))
        self._job = self.after(650, self._pulse)

    def _rrect(self, x1, y1, x2, y2, r, **kw):
        r = min(r, (x2 - x1) / 2, (y2 - y1) / 2)
        pts = [
            x1 + r,
            y1,
            x2 - r,
            y1,
            x2,
            y1,
            x2,
            y1 + r,
            x2,
            y2 - r,
            x2,
            y2,
            x2 - r,
            y2,
            x1 + r,
            y2,
            x1,
            y2,
            x1,
            y2 - r,
            x1,
            y1 + r,
            x1,
            y1,
        ]
        return self.canvas.create_polygon(pts, smooth=True, **kw)

    def _fit(self, text: str, font: tkfont.Font, maxw: float) -> str:
        if font.measure(text) <= maxw:
            return text
        lo, hi = 0, len(text)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if font.measure(text[:mid] + "…") <= maxw:
                lo = mid
            else:
                hi = mid - 1
        return text[:lo].rstrip() + "…"

    def _badge_colors(self, kind: str):
        C = self.st.C
        return {
            "accent": (C.ACCENT_SOFT, C.ACCENT),
            "green": (C.GREEN_SOFT, C.GREEN),
            "red": (C.RED_SOFT, C.RED),
            "orange": (C.ORANGE_SOFT, C.ORANGE),
            "gray": (C.GRAY_SOFT, C.TEXT2),
        }[kind]

    def _paint(self) -> None:
        self._mk()
        C, c = self.st.C, self.canvas
        c.configure(bg=resolve(C.BG))
        c.delete("all")
        W, H = max(c.winfo_width(), 2), self._view_h()
        px = self._px
        if self._mode == "empty":
            self._set_sb(0, 0, H)
            c.create_text(W / 2, H / 2 - px(54), text="✓", font=self._fonts["big"], fill=resolve(C.GREEN))
            c.create_text(W / 2, H / 2 - px(8), text=self._empty[0], font=self._fonts["title"], fill=resolve(C.TEXT))
            c.create_text(
                W / 2,
                H / 2 + px(24),
                text=self._empty[1],
                font=self._fonts["small"],
                fill=resolve(C.TEXT2),
                width=px(440),
                justify="center",
            )
            return
        if self._mode == "skeleton":
            self._set_sb(0, 0, H)
            n = int(H // self._step) + 1
            bar = resolve(C.SEP if self._phase else C.FILL)
            for i in range(n):
                y0 = i * self._step
                self._rrect(2, y0, W - 2, y0 + px(self.ROW_H), px(14), fill=resolve(C.CARD), outline="")
                self._rrect(
                    px(16), y0 + px(15), px(16 + 36), y0 + px(15 + 36), px(10), fill=bar, outline="", tags="skelbar"
                )
                self._rrect(
                    px(68),
                    y0 + px(17),
                    px(68) + px(150 + (i * 47) % 160),
                    y0 + px(29),
                    px(6),
                    fill=bar,
                    outline="",
                    tags="skelbar",
                )
                self._rrect(
                    px(68),
                    y0 + px(38),
                    px(68) + px(260 + (i * 71) % 220),
                    y0 + px(48),
                    px(5),
                    fill=bar,
                    outline="",
                    tags="skelbar",
                )
            return
        self._clamp()
        self._set_sb(self._offset, self._total(), H)
        step, rh = self._step, px(self.ROW_H)
        first = max(int(self._offset // step), 0)
        last = min(int((self._offset + H) // step) + 1, len(self.items))
        F = self._fonts
        for i in range(first, last):
            it = self.items[i]
            y0 = i * step - self._offset
            y1 = y0 + rh
            mid = (y0 + y1) / 2
            self._rrect(2, y0, W - 2, y1, px(14), fill=resolve(C.ACCENT_SOFT if it["selected"] else C.CARD), outline="")
            x = px(16)
            if it["check"] is not None:
                cx, r = x + px(11), px(11)
                if it["check"]:
                    c.create_oval(cx - r, mid - r, cx + r, mid + r, fill=resolve(C.ACCENT), outline="")
                    c.create_line(
                        [cx - px(5), mid, cx - px(1), mid + px(4), cx + px(6), mid - px(4)],
                        fill="#FFFFFF",
                        width=max(round(px(2.4)), 2),
                        capstyle="round",
                        joinstyle="round",
                    )
                else:
                    c.create_oval(
                        cx - r, mid - r, cx + r, mid + r, outline=resolve(C.TEXT2), width=max(round(px(2)), 1)
                    )
                x += px(22 + 14)
            t = px(self.TILE)
            self._rrect(x, mid - t / 2, x + t, mid + t / 2, px(10), fill=it["tile"], outline="")
            c.create_text(x + t / 2, mid, text=it["glyph"], font=F["glyph"], fill="#FFFFFF")
            x += t + px(14)
            right = W - px(16)
            if it["badge"]:
                bw = F["tiny"].measure(it["badge"]) + px(22)
                fill, fg = self._badge_colors(it["kind"])
                self._rrect(right - bw, mid - px(11), right, mid + px(11), px(11), fill=resolve(fill), outline="")
                c.create_text(right - bw / 2, mid, text=it["badge"], font=F["tiny"], fill=resolve(fg))
                right -= bw + px(12)
            maxw = max(right - x, px(40))
            c.create_text(
                x,
                mid - px(11),
                anchor="w",
                text=self._fit(it["title"], F["head"], maxw),
                font=F["head"],
                fill=resolve(C.TEXT),
            )
            c.create_text(
                x,
                mid + px(11),
                anchor="w",
                text=self._fit(it["subtitle"], F["small"], maxw),
                font=F["small"],
                fill=resolve(C.TEXT2),
            )

    def _set_sb(self, offset: float, total: float, view: float) -> None:
        need = total > view + 1
        if need and not self._sb_shown:
            self.sb.pack(side="right", fill="y", padx=(4, 0))
            self._sb_shown = True
        elif not need and self._sb_shown:
            self.sb.pack_forget()
            self._sb_shown = False
        if need:
            self.sb.set(offset / total, min((offset + view) / total, 1.0))


class IOSSwitch(tk.Canvas):
    """Interruptor estilo iOS dibujado a mano (el de CustomTkinter se recortaba con ciertos escalados de Windows)."""

    def __init__(self, master, st: Style, command: Callable[[], None] | None = None, bg=None, on: bool = False):
        self.st, self.command, self._on = st, command, on
        self._bg = bg or st.C.CARD
        sc = max(master.winfo_fpixels("1i") / 96.0, 0.5)
        self._sw, self._sh = round(51 * sc), round(31 * sc)
        super().__init__(master, width=self._sw + 2, height=self._sh + 2, highlightthickness=0, bd=0, cursor="hand2")
        self._pos = 1.0 if on else 0.0
        self.bind("<Button-1>", self._click)
        st.register(self)
        self._paint()

    def get(self) -> int:
        return 1 if self._on else 0

    def select(self) -> None:
        self._set(True)

    def deselect(self) -> None:
        self._set(False)

    def toggle(self) -> None:
        self._set(not self._on)

    def _set(self, value: bool) -> None:
        self._on = value
        self._pos = 1.0 if value else 0.0
        self._paint()

    def _click(self, _e=None) -> None:
        self._on = not self._on
        self._animate(0)
        if self.command:
            self.command()

    def _animate(self, step: int) -> None:
        target = 1.0 if self._on else 0.0
        self._pos += (target - self._pos) * 0.55
        if abs(target - self._pos) < 0.04 or step > 8:
            self._pos = target
        self._paint()
        if self._pos != target:
            self.after(16, lambda: self._animate(step + 1))

    def redraw(self) -> None:
        self._paint()

    def _paint(self) -> None:
        C = self.st.C
        self.configure(bg=resolve(self._bg))
        self.delete("all")
        w, h = self._sw, self._sh
        r = h / 2
        off, on = resolve(("#D1D1D6", "#39393D")), resolve(C.GREEN)
        track = on if self._pos > 0.5 else off
        x0, y0 = 1, 1
        self.create_oval(x0, y0, x0 + h, y0 + h, fill=track, outline="")
        self.create_oval(x0 + w - h, y0, x0 + w, y0 + h, fill=track, outline="")
        self.create_rectangle(x0 + r, y0, x0 + w - r, y0 + h, fill=track, outline="")
        pad = max(round(h * 0.07), 2)
        d = h - 2 * pad
        kx = x0 + pad + self._pos * (w - h)
        self.create_oval(kx, y0 + pad + 1, kx + d, y0 + pad + d + 1, fill="#C7C7CC", outline="")
        self.create_oval(kx, y0 + pad, kx + d, y0 + pad + d, fill="#FFFFFF", outline="")


class Dialog(ctk.CTkToplevel):
    """Ventana de confirmación estilo iOS: icono, título, mensaje y botones grandes (Enter acepta, Esc cancela)."""

    KINDS = {  # tipo -> (símbolo, color, color suave)
        "question": ("?", "ACCENT", "ACCENT_SOFT"),
        "info": ("i", "ACCENT", "ACCENT_SOFT"),
        "success": ("✓", "GREEN", "GREEN_SOFT"),
        "warning": ("!", "ORANGE", "ORANGE_SOFT"),
        "danger": ("!", "RED", "RED_SOFT"),
    }

    def __init__(
        self,
        master,
        st: Style,
        title: str,
        message: str,
        ok: str = "Continuar",
        cancel: str | None = "Cancelar",
        destructive: bool = False,
        kind: str = "question",
    ):
        C = st.C
        super().__init__(master, fg_color=C.CARD)
        self.result = False
        self.title("")
        self.resizable(False, False)
        self.transient(master)
        kind = "danger" if destructive else kind
        glyph, fg, soft = self.KINDS.get(kind, self.KINDS["question"])
        ctk.CTkLabel(
            self,
            text=glyph,
            width=60,
            height=60,
            corner_radius=30,
            fg_color=getattr(C, soft),
            text_color=getattr(C, fg),
            font=ctk.CTkFont(family=st.family, size=26, weight="bold"),
        ).pack(pady=(30, 14))
        ctk.CTkLabel(
            self,
            text=title,
            font=ctk.CTkFont(family=st.family, size=19, weight="bold"),
            text_color=C.TEXT,
            wraplength=380,
            justify="center",
        ).pack(padx=32)
        ctk.CTkLabel(self, text=message, font=st.body, text_color=C.TEXT2, wraplength=380, justify="center").pack(
            padx=32, pady=(8, 0)
        )
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=28, pady=(26, 28))
        if cancel:
            b = button(row, st, cancel, self._cancel, "secondary")
            b.configure(height=44, corner_radius=22)
            b.pack(side="left", expand=True, fill="x", padx=(0, 6))
        self.ok_btn = button(row, st, ok, self._ok, "danger" if destructive else "primary")
        self.ok_btn.configure(height=44, corner_radius=22)
        self.ok_btn.pack(side="left", expand=True, fill="x", padx=(6 if cancel else 0, 0))
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Return>", lambda _e: self._ok())
        self.bind("<Escape>", lambda _e: self._cancel())
        self.update_idletasks()
        w, h = 460, self.winfo_reqheight()
        x = master.winfo_rootx() + (master.winfo_width() - w) // 2
        y = master.winfo_rooty() + (master.winfo_height() - h) // 3
        self.geometry(f"{w}x{h}+{max(x, 0)}+{max(y, 0)}")
        if sys.platform == "win32":  # aparece con un suave fundido (en otros sistemas se omite)
            self.attributes("-alpha", 0.0)
            self._fade(0.0)
        try:
            self.wait_visibility()
            self.grab_set()
            self.focus_force()
        except tk.TclError:
            pass

    def _fade(self, a: float) -> None:
        try:
            a = min(a + 0.2, 1.0)
            self.attributes("-alpha", a)
            if a < 1.0:
                self.after(18, lambda: self._fade(a))
        except tk.TclError:
            pass

    def _ok(self):
        self.result = True
        self.destroy()

    def _cancel(self):
        self.result = False
        self.destroy()


class Segmented(ctk.CTkFrame):
    """Selector tipo iOS (Sistema | Claro | Oscuro)."""

    def __init__(self, master, st: Style, values: list[str], current: str, command: Callable[[str], None]):
        super().__init__(master, fg_color=st.C.FILL, corner_radius=12, height=1)
        self.st, self.command, self.buttons = st, command, {}
        self.current = current
        for v in values:
            b = ctk.CTkButton(
                self,
                text=v,
                width=92,
                height=30,
                corner_radius=10,
                font=st.body,
                border_width=0,
                command=lambda x=v: self.select(x, True),
            )
            b.pack(side="left", padx=3, pady=3)
            self.buttons[v] = b
        self.select(current, False)

    def select(self, value: str, fire: bool) -> None:
        self.current = value
        C = self.st.C
        for v, b in self.buttons.items():
            on = v == value
            b.configure(
                fg_color=C.CARD if on else "transparent",
                hover_color=C.CARD if on else C.SEP,
                text_color=C.ACCENT if on else C.TEXT,
            )
        if fire:
            self.command(value)
