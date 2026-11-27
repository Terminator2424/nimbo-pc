"""Fase 5a: reglas propias y aprendizaje de tus correcciones.

Si Nimbo movió algo y tú lo cambias de carpeta, lo detecta (mismo nombre y tamaño en otro sitio)
y crea una regla: "los archivos como este van a esa carpeta". Las reglas ganan sobre las de fábrica.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path

from . import config as cfg
from .pathutil import io_path, is_under, norm
from .scanner import classify, origin_hint


def load_rules(conn: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM rules ORDER BY id")]


def add_rule(conn: sqlite3.Connection, ext: str, dest_dir: str, hint: str = "", source: str = "manual") -> int:
    ext = ext.lower() if ext.startswith(".") or not ext else "." + ext.lower()
    conn.execute(
        "INSERT INTO rules(ext, hint, dest_dir, source, created) VALUES (?,?,?,?,?) "
        "ON CONFLICT(ext, hint) DO UPDATE SET dest_dir=excluded.dest_dir, source=excluded.source",
        (ext, hint or "", str(dest_dir), source, datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    return conn.execute("SELECT id FROM rules WHERE ext=? AND hint=?", (ext, hint or "")).fetchone()[0]


def delete_rule(conn: sqlite3.Connection, rule_id: int) -> bool:
    n = conn.execute("DELETE FROM rules WHERE id=?", (rule_id,)).rowcount
    conn.commit()
    return bool(n)


def match_rule(rules: list[dict], name: str) -> str | None:
    ext, _ = classify(name)
    hint = origin_hint(name) or ""
    best = None
    for r in rules:
        if r["ext"] != ext:
            continue
        if r["hint"] == hint and hint:
            return r["dest_dir"]
        if r["hint"] == "":
            best = r["dest_dir"]
    return best


def detect_corrections(conn: sqlite3.Connection, search_roots: list[Path], inbox: list[Path]) -> list[str]:
    """Busca archivos movidos por Nimbo que tú recolocaste. Devuelve mensajes de lo aprendido."""
    rows = conn.execute("SELECT * FROM moves WHERE status='done' AND action='move'").fetchall()
    gone = [r for r in rows if not os.path.lexists(io_path(r["dst"]))]
    if not gone:
        return []
    wanted: dict[str, list] = {}
    for r in gone:
        wanted.setdefault(os.path.basename(r["dst"]).lower(), []).append(r)
    found: dict[tuple[str, int], str] = {}
    skip_names = {n.lower() for n in cfg.PROTECTED_DIR_NAMES}
    for root in search_roots:
        for dirpath, dirnames, filenames in os.walk(str(root)):
            dirnames[:] = [d for d in dirnames if d.lower() not in skip_names and not d.startswith("_Cuarentena")]
            for fn in filenames:
                if fn.lower() in wanted:
                    full = os.path.join(dirpath, fn)
                    try:
                        found[(fn.lower(), os.path.getsize(io_path(full)))] = full
                    except OSError:
                        pass
    inbox_n = [norm(str(i)) for i in inbox]
    learned: list[str] = []
    for r in gone:
        loc = found.get((os.path.basename(r["dst"]).lower(), r["size"]))
        if not loc:
            continue
        new_dir = os.path.dirname(loc)
        conn.execute("UPDATE moves SET status='corrected' WHERE id=?", (r["id"],))
        if any(is_under(norm(new_dir), i) for i in inbox_n):
            continue  # lo devolviste a Descargas/Escritorio: no es un destino para una regla
        name = os.path.basename(r["dst"])
        ext, _ = classify(name)
        if not ext:
            continue
        hint = origin_hint(name) or ""
        add_rule(conn, ext, new_dir, hint, source="learned")
        learned.append(f"Aprendí: archivos {ext}{' (' + hint + ')' if hint else ''} -> {new_dir}")
    conn.commit()
    return learned
