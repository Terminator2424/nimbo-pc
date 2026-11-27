"""Utilidades de rutas y de formato (solo biblioteca estándar)."""

from __future__ import annotations

import os

_LONG_PREFIX = "\\\\?\\"
_LONG_THRESHOLD = 240


def io_path(path: str) -> str:
    """Ruta lista para llamadas al sistema (prefijo \\\\?\\ si es muy larga en Windows)."""
    if os.name != "nt":
        return path
    if path.startswith("\\\\"):
        return path
    if len(path) >= _LONG_THRESHOLD:
        return _LONG_PREFIX + os.path.abspath(path)
    return path


def clean_path(path: str) -> str:
    if os.name == "nt" and path.startswith(_LONG_PREFIX) and not path.startswith(_LONG_PREFIX + "UNC\\"):
        return path[len(_LONG_PREFIX) :]
    return path


def norm(path: str) -> str:
    """Ruta absoluta y normalizada para comparar (sin mayúsculas en Windows)."""
    return os.path.normcase(os.path.abspath(str(path)))


def is_under(path_norm: str, prefix_norm: str) -> bool:
    if path_norm == prefix_norm:
        return True
    return path_norm.startswith(prefix_norm.rstrip(os.sep) + os.sep)


_UNITS = ["B", "KB", "MB", "GB", "TB", "PB"]


def fmt_size(n: int | float) -> str:
    x = float(n)
    i = 0
    while x >= 1024 and i < len(_UNITS) - 1:
        x /= 1024
        i += 1
    if i == 0:
        return f"{int(x)} B"
    return f"{x:.1f} {_UNITS[i]}".replace(".", ",")


def fmt_int(n: int) -> str:
    return f"{int(n):,}".replace(",", ".")


def fmt_pct(part: float, total: float) -> str:
    if not total:
        return "0,0 %"
    return f"{100.0 * part / total:.1f} %".replace(".", ",")


def parse_size(text: str) -> int:
    s = text.strip().upper().replace(",", ".")
    mult = 1
    for suffix, m in (("TB", 1024**4), ("GB", 1024**3), ("MB", 1024**2), ("KB", 1024), ("B", 1)):
        if s.endswith(suffix):
            s = s[: -len(suffix)].strip()
            mult = m
            break
    return int(float(s) * mult)
