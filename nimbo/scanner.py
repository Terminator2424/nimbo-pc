"""Escáner de solo lectura: guarda un inventario en SQLite.

NUNCA modifica, mueve ni borra nada dentro de las carpetas escaneadas.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from collections.abc import Sequence
from collections.abc import Callable

from . import config as cfg
from .pathutil import clean_path, io_path, is_under, norm

_REPARSE_POINT = 0x400
_LINK_TAGS = {0xA000000C, 0xA0000003}  # IO_REPARSE_TAG_SYMLINK, IO_REPARSE_TAG_MOUNT_POINT (junction)
# OneDrive "solo en la nube": leerlo lo descargaría, así que no se hashea.
_CLOUD_MASK = 0x1000 | 0x40000 | 0x400000
_BATCH = 2000

ProgressFn = Callable[[int, int], None]

_HINT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "whatsapp",
        re.compile(r"^(IMG|VID|AUD|PTT|DOC|STK)-\d{8}-WA\d+|^WhatsApp (Image|Video|Audio|Ptt|Document)", re.I),
    ),
    ("captura", re.compile(r"^(Screenshot|Screen Shot|Captura de pantalla|Captura)", re.I)),
    ("camara", re.compile(r"^(IMG|DSC|DSCN|DSCF|PXL|MVIMG|MVI|VID|MOV)[_-]?\d{4,}", re.I)),
    ("copia", re.compile(r"(\(\d+\)$|[\s_-]copia( \(\d+\))?$|^copia de |^copy of |[\s_-]copy( \(\d+\))?$)", re.I)),
]


def classify(name: str) -> tuple[str, str]:
    """(extensión en minúsculas, categoría)."""
    ext = os.path.splitext(name)[1].lower()
    if not ext:
        return "", "sin_extension"
    return ext, cfg.CATEGORY_BY_EXT.get(ext, "otros")


def origin_hint(name: str) -> str | None:
    stem = os.path.splitext(name)[0]
    for label, pattern in _HINT_PATTERNS:
        if pattern.search(stem if label == "copia" else name):
            return label
    return None


def normalize_roots(roots: Sequence[Path | str]) -> list[Path]:
    """Absolutas, sin repetidas y sin carpetas contenidas en otra raíz."""
    unique: dict[str, Path] = {}
    for r in roots:
        p = Path(os.path.abspath(str(r)))
        unique[norm(str(p))] = p
    kept: list[str] = []
    result: list[Path] = []
    for key in sorted(unique, key=len):
        if any(is_under(key, k) for k in kept):
            continue
        kept.append(key)
        result.append(unique[key])
    return result


@dataclass
class ScanOptions:
    roots: list[Path]
    extra_protected: list[Path] = field(default_factory=list)
    exclude_dirs: list[Path] = field(default_factory=list)
    exclude_files: list[Path] = field(default_factory=list)
    measure_protected: bool = True


@dataclass
class ScanResult:
    scan_id: int
    files: int = 0
    bytes: int = 0
    dirs: int = 0
    protected_dirs: int = 0
    project_dirs: int = 0
    skipped_links: int = 0
    cloud_only: int = 0
    errors: int = 0
    seconds: float = 0.0
    status: str = "running"
    warnings: list[str] = field(default_factory=list)


def _is_link(entry: os.DirEntry) -> bool:
    """True solo para enlaces simbólicos y uniones (junctions).

    Otros puntos de reanálisis de Windows (archivos de OneDrive, deduplicación...) son archivos normales
    y NO se omiten: antes se trataban todos como enlaces y se saltaban en silencio.
    """
    try:
        if entry.is_symlink():
            return True
        is_junction = getattr(entry, "is_junction", None)  # Python 3.12+
        if is_junction is not None and is_junction():
            return True
        st = entry.stat(follow_symlinks=False)
        if getattr(st, "st_file_attributes", 0) & _REPARSE_POINT:
            return getattr(st, "st_reparse_tag", 0) in _LINK_TAGS
        return False
    except OSError:
        return False


def _measure(path: str) -> tuple[int, int]:
    """(bytes, archivos) de un árbol, sin guardar archivos. Ignora enlaces y errores."""
    total = count = 0
    stack = [path]
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(io_path(cur)) as it:
                for e in it:
                    try:
                        if _is_link(e):
                            continue
                        if e.is_dir(follow_symlinks=False):
                            stack.append(os.path.join(cur, e.name))
                        elif e.is_file(follow_symlinks=False):
                            total += e.stat(follow_symlinks=False).st_size
                            count += 1
                    except OSError:
                        continue
        except OSError:
            continue
    return total, count


_UPSERT = """
INSERT INTO files(path, root, parent, name, ext, size, mtime_ns, created_ns,
                  category, hint, cloud_only, last_seen_scan)
VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(path) DO UPDATE SET
  root=excluded.root, parent=excluded.parent, name=excluded.name, ext=excluded.ext,
  hash_quick = CASE WHEN files.size=excluded.size AND files.mtime_ns=excluded.mtime_ns
                    THEN files.hash_quick END,
  hash_full  = CASE WHEN files.size=excluded.size AND files.mtime_ns=excluded.mtime_ns
                    THEN files.hash_full END,
  size=excluded.size, mtime_ns=excluded.mtime_ns, created_ns=excluded.created_ns,
  category=excluded.category, hint=excluded.hint, cloud_only=excluded.cloud_only,
  last_seen_scan=excluded.last_seen_scan
"""


def scan(conn: sqlite3.Connection, options: ScanOptions, progress: ProgressFn | None = None) -> ScanResult:
    t0 = time.time()
    roots = normalize_roots(options.roots)
    cur = conn.execute(
        "INSERT INTO scans(started_at, roots, status) VALUES (?,?, 'running')",
        (datetime.now().isoformat(timespec="seconds"), json.dumps([str(r) for r in roots])),
    )
    scan_id = int(cur.lastrowid or 0)
    conn.commit()
    res = ScanResult(scan_id=scan_id)

    extra = [norm(str(p)) for p in options.extra_protected]
    ex_dirs = [norm(str(p)) for p in options.exclude_dirs]
    ex_files = {norm(str(p)) for p in options.exclude_files}

    dirstats: dict[str, dict] = {}
    batch: list[tuple] = []
    scanned_roots: list[str] = []

    def flush() -> None:
        if batch:
            conn.executemany(_UPSERT, batch)
            batch.clear()

    def log_error(path: str, err: Exception) -> None:
        res.errors += 1
        conn.execute(
            "INSERT INTO scan_errors(scan_id, path, error) VALUES (?,?,?)",
            (scan_id, clean_path(path), f"{type(err).__name__}: {err}"),
        )

    def opaque_reason(path: str, name: str) -> str | None:
        if name.lower() in cfg.PROTECTED_DIR_NAMES:
            return f"carpeta protegida ({name})"
        n = norm(path)
        if any(is_under(n, e) for e in extra):
            return "protegida por ti (config)"
        return None

    def add_dir(
        path: str, root: str, parent: str | None, depth: int, kind: str = "normal", reason: str | None = None
    ) -> dict:
        d = {
            "root": root,
            "parent": parent,
            "depth": depth,
            "kind": kind,
            "reason": reason,
            "measured": 1,
            "direct_size": 0,
            "direct_files": 0,
        }
        dirstats[path] = d
        res.dirs += 1
        if kind == "protected":
            res.protected_dirs += 1
        elif kind == "project":
            res.project_dirs += 1
        return d

    def set_opaque(path: str, d: dict) -> None:
        if options.measure_protected:
            d["direct_size"], d["direct_files"] = _measure(path)
        else:
            d["measured"] = 0

    try:
        for root_path in roots:
            root = str(root_path)
            if not root_path.is_dir():
                res.warnings.append(f"No existe o no es carpeta: {root}")
                continue
            scanned_roots.append(root)
            add_dir(root, root, None, 0)
            stack: list[tuple[str, int]] = [(root, 0)]
            while stack:
                path, depth = stack.pop()
                d = dirstats[path]
                try:
                    with os.scandir(io_path(path)) as it:
                        entries = list(it)
                except OSError as exc:
                    log_error(path, exc)
                    continue
                if depth > 0:
                    names = {e.name.lower() for e in entries}
                    marker = (names & cfg.PROJECT_MARKER_FILES) or {
                        n for n in names if n.endswith(cfg.PROJECT_MARKER_SUFFIXES)
                    }
                    if marker:
                        d["kind"], d["reason"] = "project", f"proyecto ({sorted(marker)[0]})"
                        res.project_dirs += 1
                        set_opaque(path, d)
                        continue
                for e in entries:
                    full = os.path.join(path, e.name)
                    try:
                        if _is_link(e):
                            res.skipped_links += 1
                            continue
                        if e.is_dir(follow_symlinks=False):
                            n = norm(full)
                            if any(is_under(n, x) for x in ex_dirs):
                                continue
                            why = opaque_reason(full, e.name)
                            if why:
                                sub = add_dir(full, root, path, depth + 1, "protected", why)
                                set_opaque(full, sub)
                            else:
                                add_dir(full, root, path, depth + 1)
                                stack.append((full, depth + 1))
                        elif e.is_file(follow_symlinks=False):
                            if norm(full) in ex_files:
                                continue
                            st = e.stat(follow_symlinks=False)
                            attrs = getattr(st, "st_file_attributes", 0)
                            cloud = 1 if attrs & _CLOUD_MASK else 0
                            ext, cat = classify(e.name)
                            batch.append(
                                (
                                    clean_path(full),
                                    root,
                                    clean_path(path),
                                    e.name,
                                    ext,
                                    st.st_size,
                                    st.st_mtime_ns,
                                    st.st_ctime_ns,
                                    cat,
                                    origin_hint(e.name),
                                    cloud,
                                    scan_id,
                                )
                            )
                            d["direct_size"] += st.st_size
                            d["direct_files"] += 1
                            res.files += 1
                            res.bytes += st.st_size
                            res.cloud_only += cloud
                            if len(batch) >= _BATCH:
                                flush()
                                if progress:
                                    progress(res.files, res.dirs)
                    except OSError as err:
                        log_error(full, err)
        flush()
        res.status = "ok"
    except KeyboardInterrupt:
        flush()
        res.status = "interrupted"

    # totales acumulados hacia las carpetas padre
    totals = {p: [v["direct_size"], v["direct_files"]] for p, v in dirstats.items()}
    for p in sorted(dirstats, key=lambda x: dirstats[x]["depth"], reverse=True):
        par = dirstats[p]["parent"]
        if par in totals:
            totals[par][0] += totals[p][0]
            totals[par][1] += totals[p][1]
    conn.executemany(
        "INSERT OR REPLACE INTO dirs(path, root, parent, depth, kind, reason, measured, "
        "direct_size, direct_files, total_size, total_files, last_seen_scan) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                clean_path(p),
                v["root"],
                v["parent"],
                v["depth"],
                v["kind"],
                v["reason"],
                v["measured"],
                v["direct_size"],
                v["direct_files"],
                totals[p][0],
                totals[p][1],
                scan_id,
            )
            for p, v in dirstats.items()
        ],
    )
    if res.status == "ok" and scanned_roots:
        marks = ",".join("?" * len(scanned_roots))
        for table in ("files", "dirs"):  # borra del inventario lo que ya no existe
            conn.execute(
                f"DELETE FROM {table} WHERE root IN ({marks}) AND last_seen_scan != ?",  # nosec B608 - tabla fija, valores parametrizados
                (*scanned_roots, scan_id),
            )
    res.seconds = time.time() - t0
    conn.execute(
        "UPDATE scans SET finished_at=?, files=?, bytes=?, dirs=?, errors=?, seconds=?, status=? WHERE id=?",
        (
            datetime.now().isoformat(timespec="seconds"),
            res.files,
            res.bytes,
            res.dirs,
            res.errors,
            res.seconds,
            res.status,
            scan_id,
        ),
    )
    conn.commit()
    return res
