"""`nimbo doctor`: autodiagnóstico para auditoría (no modifica nada)."""

from __future__ import annotations

import os
import platform
import shutil
import sqlite3
import sys

from . import __version__
from . import ai as ailib
from . import config as cfg

OK, WARN, ERR = "OK", "AVISO", "ERROR"


def run_checks(conn: sqlite3.Connection, layout, inbox, protection) -> list[tuple[str, str, str]]:
    r: list[tuple[str, str, str]] = []
    r.append((OK, "versión", f"Nimbo {__version__} · Python {sys.version.split()[0]} · {platform.platform()}"))
    ok = conn.execute("PRAGMA integrity_check").fetchone()[0]
    r.append((OK if ok == "ok" else ERR, "base de datos", f"integridad: {ok}"))
    n_moves = conn.execute("SELECT COUNT(*) FROM moves WHERE status='done'").fetchone()[0]
    gone = [row for row in conn.execute("SELECT dst FROM moves WHERE status='done'") if not os.path.lexists(row[0])]
    r.append(
        (
            OK if not gone else WARN,
            "historial",
            f"{n_moves} movimientos vigentes; {len(gone)} ya no están en su destino"
            + (" (los movió alguien más; `learn` los analiza)" if gone else ""),
        )
    )
    cfgd = cfg.load_user_config()
    r.append((OK, "config.json", f"{cfg.user_config_path()} ({len(cfgd)} claves)" if cfgd else "sin personalizar"))
    _, problem = ailib.ai_status()
    if cfgd.get("ai"):
        r.append((OK if not problem else ERR, "IA local", problem or "servidor local válido"))
    else:
        r.append((OK, "IA local", "no configurada (opcional)"))
    missing = [str(p) for p in inbox if not p.is_dir()]
    r.append(
        (
            OK if not missing else WARN,
            "carpetas de entrada",
            ", ".join(str(p) for p in inbox) if not missing else f"no existen: {missing}",
        )
    )
    r.append((OK, "zonas protegidas", f"{len(protection.prefixes)} rutas protegidas además de los nombres reservados"))
    r.append(
        (
            OK if shutil.which("git") else WARN,
            "git",
            "disponible"
            if shutil.which("git")
            else "no encontrado: no se podrá verificar repos con `git status` al mover proyectos",
        )
    )
    r.append((OK, "datos", str(cfg.data_dir())))
    return r
