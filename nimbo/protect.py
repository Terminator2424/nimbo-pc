"""Zonas protegidas: qué NO se puede mover jamás."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from . import config as cfg
from .pathutil import is_under, norm


class Protection:
    def __init__(self, paths: list[Path | str] | None = None):
        self.prefixes = [norm(str(p)) for p in (paths or [])]
        self._project_cache: dict[str, str | None] = {}

    def _project_marker(self, directory: str) -> str | None:
        if directory in self._project_cache:
            return self._project_cache[directory]
        found = None
        try:
            names = {n.lower() for n in os.listdir(directory)}
            hit = (names & cfg.PROJECT_MARKER_FILES) or {n for n in names if n.endswith(cfg.PROJECT_MARKER_SUFFIXES)}
            if hit:
                found = sorted(hit)[0]
        except OSError:
            pass
        self._project_cache[directory] = found
        return found

    def is_protected_path(self, path: str) -> bool:
        n = norm(path)
        return any(is_under(n, pre) for pre in self.prefixes)

    def blocked_reason(self, path: str, stop_at: str) -> str | None:
        """Motivo por el que no se debe mover `path`, o None si es seguro.

        stop_at = carpeta de entrada (Descargas/Escritorio); ella misma no cuenta como proyecto.
        """
        n = norm(path)
        for pre in self.prefixes:
            if is_under(n, pre):
                return "zona protegida (juegos/programas/config)"
        stop = norm(stop_at)
        rel_parts = Path(os.path.relpath(path, stop_at)).parts[:-1] if is_under(n, stop) else ()
        for part in rel_parts:
            if part.lower() in cfg.PROTECTED_DIR_NAMES:
                return f"carpeta protegida ({part})"
        cur = os.path.dirname(os.path.abspath(path))
        while is_under(norm(cur), stop) and norm(cur) != stop:
            marker = self._project_marker(cur)
            if marker:
                return f"dentro de un proyecto ({marker})"
            cur = os.path.dirname(cur)
        return None

    @classmethod
    def from_system(
        cls,
        conn: sqlite3.Connection | None = None,
        extra: list | None = None,
        inbox: list[Path] | None = None,
        steam_dirs: list[Path] | None = None,
    ) -> Protection:
        from .programs import read_steam_games

        paths: list[Path | str] = list(extra or [])
        paths += [Path(p) for p in cfg.load_user_config().get("extra_protected") or []]
        for g in read_steam_games(steam_dirs):
            lib = Path(g["library"])
            paths += [lib / "steamapps"]
        if conn is not None:
            inbox_n = [norm(str(i)) for i in (inbox or [])]
            for r in conn.execute(
                "SELECT DISTINCT install_location FROM programs "
                "WHERE install_location IS NOT NULL AND install_location != ''"
            ):
                loc = r[0].strip('"')
                if len(loc) < 4:
                    continue
                ln = norm(loc)
                if any(is_under(i, ln) for i in inbox_n):  # un programa "instalado" en un ancestro de Descargas
                    continue
                paths.append(loc)
        if os.name == "nt":
            for env in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData"):
                if os.environ.get(env):
                    paths.append(os.environ[env])
        return cls(paths)
