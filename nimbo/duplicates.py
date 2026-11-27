"""Detección de duplicados (solo lectura).

1) mismo tamaño -> 2) hash de los primeros 64 KB -> 3) SHA-256 completo.
Los hashes se guardan en la base y se reutilizan mientras el archivo no cambie.
Los archivos solo-en-la-nube (OneDrive) se omiten para no forzar su descarga.
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import Callable

from .pathutil import io_path

HEAD_BYTES = 64 * 1024
CHUNK_BYTES = 1024 * 1024

ProgressFn = Callable[[str, int, int], None]


@dataclass
class DupGroup:
    size: int
    hash: str
    paths: list[str]  # el primero es el "sugerido para conservar"

    @property
    def wasted(self) -> int:
        return self.size * (len(self.paths) - 1)


@dataclass
class HashStats:
    candidates: int = 0
    quick_hashed: int = 0
    full_hashed: int = 0
    errors: int = 0
    notes: list[str] = field(default_factory=list)


def hash_file(path: str, head_only: bool = False) -> str:
    h = hashlib.sha256()
    with open(io_path(path), "rb") as f:
        if head_only:
            h.update(f.read(HEAD_BYTES))
        else:
            while True:
                chunk = f.read(CHUNK_BYTES)
                if not chunk:
                    break
                h.update(chunk)
    return h.hexdigest()


_COPY_RE = re.compile(r"(\(\d+\)$|[\s_-]copia( \(\d+\))?$|^copia de |^copy of |[\s_-]copy( \(\d+\))?$)", re.I)
_TEMPORARY_DIRS = {"downloads", "descargas", "temp", "tmp", "desktop", "escritorio"}


def keep_score(path: str, mtime_ns: int) -> tuple[int, int, int]:
    """Menor = más probable que sea el original. Solo es una sugerencia."""
    p = Path(path)
    score = 0
    if _COPY_RE.search(p.stem):
        score += 10
    if {part.lower() for part in p.parts[:-1]} & _TEMPORARY_DIRS:
        score += 5
    return (score, len(path), mtime_ns)


def _identity(path: str) -> tuple[int, int] | None:
    try:
        st = os.stat(io_path(path))
    except OSError:
        return None
    if getattr(st, "st_nlink", 1) > 1 and st.st_ino:
        return (st.st_dev, st.st_ino)
    return None


def collapse_hardlinks(paths: list[str]) -> list[str]:
    """Dos rutas al mismo archivo físico no son un duplicado: se deja una."""
    seen: set[tuple[int, int]] = set()
    kept: list[str] = []
    for p in paths:
        ident = _identity(p)
        if ident is not None:
            if ident in seen:
                continue
            seen.add(ident)
        kept.append(p)
    return kept


def find_duplicates(
    conn: sqlite3.Connection, min_size: int = 1, progress: ProgressFn | None = None
) -> tuple[list[DupGroup], HashStats]:
    stats = HashStats()
    min_size = max(1, min_size)  # los archivos vacíos nunca cuentan como duplicados

    cands = conn.execute(
        "SELECT path, size, hash_quick FROM files WHERE cloud_only = 0 AND size >= ? "
        "AND size IN (SELECT size FROM files WHERE cloud_only = 0 AND size >= ? "
        "GROUP BY size HAVING COUNT(*) > 1)",
        (min_size, min_size),
    ).fetchall()
    stats.candidates = len(cands)

    todo = [r for r in cands if r["hash_quick"] is None]
    for i, r in enumerate(todo, 1):
        try:
            q = hash_file(r["path"], head_only=True)
        except OSError:
            stats.errors += 1
            continue
        stats.quick_hashed += 1
        # archivo que cabe en la cabecera: el hash rápido ya es el completo
        full = q if r["size"] <= HEAD_BYTES else None
        conn.execute(
            "UPDATE files SET hash_quick=?, hash_full=COALESCE(?, hash_full) WHERE path=?", (q, full, r["path"])
        )
        if progress and i % 50 == 0:
            progress("rápido", i, len(todo))
    conn.commit()

    need_full = conn.execute(
        "SELECT path FROM files WHERE cloud_only = 0 AND size > ? AND hash_full IS NULL "
        "AND hash_quick IS NOT NULL AND (size, hash_quick) IN "
        "(SELECT size, hash_quick FROM files WHERE hash_quick IS NOT NULL AND cloud_only = 0 "
        " GROUP BY size, hash_quick HAVING COUNT(*) > 1)",
        (HEAD_BYTES,),
    ).fetchall()
    for i, r in enumerate(need_full, 1):
        try:
            h = hash_file(r["path"])
        except OSError:
            stats.errors += 1
            continue
        stats.full_hashed += 1
        conn.execute("UPDATE files SET hash_full=? WHERE path=?", (h, r["path"]))
        if progress:
            progress("completo", i, len(need_full))
    conn.commit()
    return duplicate_groups(conn, min_size), stats


def duplicate_groups(conn: sqlite3.Connection, min_size: int = 1) -> list[DupGroup]:
    min_size = max(1, min_size)
    keys = conn.execute(
        "SELECT size, hash_full FROM files WHERE hash_full IS NOT NULL AND cloud_only = 0 "
        "AND size >= ? GROUP BY size, hash_full HAVING COUNT(*) > 1",
        (min_size,),
    ).fetchall()
    groups: list[DupGroup] = []
    for k in keys:
        rows = conn.execute(
            "SELECT path, mtime_ns FROM files WHERE size=? AND hash_full=?", (k["size"], k["hash_full"])
        ).fetchall()
        ordered = [r["path"] for r in sorted(rows, key=lambda r: keep_score(r["path"], r["mtime_ns"]))]
        ordered = collapse_hardlinks(ordered)
        if len(ordered) > 1:
            groups.append(DupGroup(k["size"], k["hash_full"], ordered))
    groups.sort(key=lambda g: g.wasted, reverse=True)
    return groups
