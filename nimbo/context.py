"""Arma layout, carpetas de entrada y protección (compartido por CLI y ventana)."""

from __future__ import annotations

from pathlib import Path

from . import config as cfg
from .classifier import Layout
from .protect import Protection


def make_context(conn, layout_root: str | None = None, inbox: list | None = None, protect: list | None = None):
    if layout_root:
        root = Path(layout_root)
        layout = Layout.from_root(root)
        boxes = [Path(p) for p in inbox] if inbox else [root / "Descargas", root / "Escritorio"]
    else:
        layout = Layout.from_system()
        boxes = [Path(p) for p in inbox] if inbox else cfg.inbox_dirs()
    protection = Protection.from_system(conn, extra=[Path(p) for p in (protect or [])], inbox=boxes)
    return layout, boxes, protection
