"""Sistema de diseño (estilo iOS): colores, fuentes y presets.

Se personaliza sin tocar código:   python -m nimbo theme --preset rose --mode dark
Los colores son pares (claro, oscuro): la ventana cambia sola con el modo del sistema.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import config as cfg

DEFAULT_ACCENT = "#007AFF"
MODES = ("system", "light", "dark")
PRESETS = {
    "ios": "#007AFF",  # azul iOS
    "rose": "#FF2D55",  # rosa
    "mint": "#00B8A9",  # menta
    "sunset": "#FF9500",  # naranja
    "violet": "#AF52DE",  # violeta
    "graphite": "#636366",  # grafito
}
FONT_PREFERENCE = ("SF Pro Text", "SF Pro Display", "Segoe UI Variable Text", "Segoe UI", "Inter", "Helvetica Neue")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def valid_hex(value: str) -> bool:
    return bool(_HEX.match(value or ""))


def mix(a: str, b: str, weight_b: float) -> str:
    """Mezcla dos colores #RRGGBB; weight_b=0 -> a, 1 -> b."""
    ca = [int(a[i : i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i : i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x * (1 - weight_b) + y * weight_b):02X}" for x, y in zip(ca, cb, strict=True))


def load() -> dict:
    t = cfg.load_user_config().get("theme") or {}
    accent = t.get("accent") if valid_hex(t.get("accent", "")) else DEFAULT_ACCENT
    mode = t.get("mode") if t.get("mode") in MODES else "system"
    return {"accent": accent, "mode": mode}


def save(accent: str | None = None, mode: str | None = None, reset: bool = False) -> dict:
    cur = {"accent": DEFAULT_ACCENT, "mode": "system"} if reset else load()
    if accent is not None:
        if not valid_hex(accent):
            raise ValueError("El color debe ser #RRGGBB, por ejemplo #FF2D55")
        cur["accent"] = accent.upper()
    if mode is not None:
        if mode not in MODES:
            raise ValueError(f"El modo debe ser uno de: {', '.join(MODES)}")
        cur["mode"] = mode
    cfg.save_user_config({"theme": cur})
    return cur


@dataclass(frozen=True)
class Palette:
    """Cada color es (claro, oscuro), el formato que entiende CustomTkinter."""

    BG: tuple[str, str]
    SIDEBAR: tuple[str, str]
    CARD: tuple[str, str]
    FILL: tuple[str, str]
    SEP: tuple[str, str]
    TEXT: tuple[str, str]
    TEXT2: tuple[str, str]
    ACCENT: tuple[str, str]
    ACCENT_HOVER: tuple[str, str]
    ACCENT_SOFT: tuple[str, str]
    GREEN: tuple[str, str]
    GREEN_SOFT: tuple[str, str]
    RED: tuple[str, str]
    RED_SOFT: tuple[str, str]
    ORANGE: tuple[str, str]
    ORANGE_SOFT: tuple[str, str]
    GRAY_SOFT: tuple[str, str]
    TOAST: tuple[str, str]
    TOAST_TEXT: tuple[str, str]


def palette(accent: str = DEFAULT_ACCENT) -> Palette:
    return Palette(
        BG=("#F2F2F7", "#000000"),
        SIDEBAR=("#E8E8ED", "#121214"),
        CARD=("#FFFFFF", "#1C1C1E"),
        FILL=("#E9E9EE", "#2C2C2E"),
        SEP=("#E1E1E6", "#38383A"),
        TEXT=("#1C1C1E", "#FFFFFF"),
        TEXT2=("#8A8A8E", "#98989D"),
        ACCENT=(accent, accent),
        ACCENT_HOVER=(mix(accent, "#000000", 0.14), mix(accent, "#FFFFFF", 0.14)),
        ACCENT_SOFT=(mix(accent, "#FFFFFF", 0.86), mix(accent, "#1C1C1E", 0.76)),
        GREEN=("#34C759", "#30D158"),
        GREEN_SOFT=("#DDF5E3", "#16301F"),
        RED=("#FF3B30", "#FF453A"),
        RED_SOFT=("#FFE3E1", "#3A1B19"),
        ORANGE=("#FF9500", "#FF9F0A"),
        ORANGE_SOFT=("#FFEBCF", "#3A2B12"),
        GRAY_SOFT=("#E9E9EE", "#2C2C2E"),
        TOAST=("#1C1C1E", "#F2F2F7"),
        TOAST_TEXT=("#FFFFFF", "#1C1C1E"),
    )


# categoría -> (símbolo, color del icono), como los iconos de Ajustes de iOS
CATEGORY_STYLE = {
    "imagenes": ("▣", "#FF2D55"),
    "videos": ("▶", "#AF52DE"),
    "musica": ("♪", "#FF3B30"),
    "documentos": ("▤", "#007AFF"),
    "hojas_de_calculo": ("▦", "#34C759"),
    "presentaciones": ("◧", "#FF9500"),
    "comprimidos": ("▥", "#A2845E"),
    "ejecutables": ("⚙", "#636366"),
    "ia": ("✦", "#AF52DE"),
    "proyecto": ("◆", "#5856D6"),
}


def category_style(category: str) -> tuple[str, str]:
    return CATEGORY_STYLE.get(category, ("•", "#8E8E93"))


def pick_font_family(available: set[str]) -> str:
    for name in FONT_PREFERENCE:
        if name in available:
            return name
    return "TkDefaultFont"
