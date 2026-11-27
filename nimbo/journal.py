"""Fase 3: ejecuta un plan moviendo con diario de cambios (SQLite) y permite deshacer.

Garantías: nunca sobrescribe, nunca borra (duplicados exactos van a cuarentena),
cada movimiento queda registrado con origen y destino, y todo se puede deshacer.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .classifier import Layout, Plan
from .duplicates import hash_file
from .pathutil import io_path
from .protect import Protection


@dataclass
class ApplyResult:
    batch_id: int | None = None
    done: int = 0
    quarantined: int = 0
    skipped: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def unique_path(path: str) -> str:
    if not os.path.lexists(io_path(path)):
        return path
    base, ext = os.path.splitext(path)
    n = 2
    while os.path.lexists(io_path(f"{base} ({n}){ext}")):
        n += 1
    return f"{base} ({n}){ext}"


def find_identical(directory: str, src: str, size: int) -> str | None:
    """Archivo idéntico (mismo tamaño y SHA-256) en la carpeta destino, si existe."""
    try:
        entries = list(os.scandir(io_path(directory)))
    except OSError:
        return None
    src_hash = None
    for e in entries:
        try:
            if e.is_file(follow_symlinks=False) and e.stat().st_size == size:
                src_hash = src_hash or hash_file(src)
                if hash_file(os.path.join(directory, e.name)) == src_hash:
                    return os.path.join(directory, e.name)
        except OSError:
            continue
    return None


def _move_file(src: str, dst: str, size: int) -> None:
    os.makedirs(io_path(os.path.dirname(dst)), exist_ok=True)
    if os.path.lexists(io_path(dst)):
        raise FileExistsError(dst)
    shutil.move(io_path(src), io_path(dst))  # entre discos: copia y luego quita el original
    if os.path.getsize(io_path(dst)) != size:
        raise OSError("el tamaño del destino no coincide; revisa el diario")


def _record(conn, batch_id, src, dst, action, size, reason, conf, status="done") -> None:
    conn.execute(
        "INSERT INTO moves(batch_id, ts, src, dst, action, size, reason, confidence, status) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (batch_id, _now(), src, dst, action, size, reason, conf, status),
    )
    conn.commit()


def apply_plan(
    conn: sqlite3.Connection,
    plan: Plan,
    layout: Layout,
    protection: Protection,
    inbox: list[Path],
    *,
    kind: str = "manual",
    note: str = "",
) -> ApplyResult:
    res = ApplyResult()
    batch_id: int | None = None
    for m in plan.moves:
        # revalidar justo antes de mover: el mundo pudo cambiar desde que se hizo el plan
        try:
            st = os.stat(io_path(m.src))
        except OSError:
            res.skipped.append(f"{m.src}: ya no existe")
            continue
        if st.st_size != m.size:
            res.skipped.append(f"{m.src}: cambió de tamaño desde el plan")
            continue
        box = next((b for b in inbox if str(Path(m.src).resolve()).startswith(str(b.resolve()))), None)
        if box is not None and protection.blocked_reason(m.src, str(box)):
            res.skipped.append(f"{m.src}: protegido")
            continue
        dst, action, reason = m.dst, "move", m.reason
        dst_dir = os.path.dirname(dst)
        twin = find_identical(dst_dir, m.src, m.size) if os.path.isdir(io_path(dst_dir)) else None
        if twin:
            action, reason = "quarantine", f"copia idéntica de {twin}"
            qdir = layout.quarantine / datetime.now().strftime("%Y-%m-%d") / "Duplicados"
            dst = str(qdir / os.path.basename(m.src))
        dst = unique_path(dst)
        try:
            _move_file(m.src, dst, m.size)
        except OSError as e:  # bloqueado, sin permiso, disco lleno...
            res.failed.append(f"{m.src}: {e}")
            continue
        if batch_id is None:
            batch_id = conn.execute(
                "INSERT INTO batches(ts, kind, note) VALUES (?,?,?)", (_now(), kind, note)
            ).lastrowid
            res.batch_id = batch_id
        _record(conn, batch_id, m.src, dst, action, m.size, reason, m.confidence)
        if action == "quarantine":
            res.quarantined += 1
        else:
            res.done += 1
    return res


@dataclass
class UndoResult:
    restored: int = 0
    missing: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)


def undo(conn: sqlite3.Connection, batch_id: int | None = None, everything: bool = False) -> UndoResult:
    """Devuelve cada archivo a su lugar original. Sin batch_id deshace el último lote."""
    res = UndoResult()
    if everything:
        rows = conn.execute("SELECT * FROM moves WHERE status='done' ORDER BY id DESC").fetchall()
    else:
        if batch_id is None:
            r = conn.execute("SELECT MAX(batch_id) FROM moves WHERE status='done'").fetchone()
            batch_id = r[0]
        if batch_id is None:
            return res
        rows = conn.execute(
            "SELECT * FROM moves WHERE status='done' AND batch_id=? ORDER BY id DESC", (batch_id,)
        ).fetchall()
    if not rows:
        return res
    ub = conn.execute(
        "INSERT INTO batches(ts, kind, note) VALUES (?, 'undo', ?)",
        (_now(), "todo" if everything else f"lote {batch_id}"),
    ).lastrowid
    for r in rows:
        if not os.path.lexists(io_path(r["dst"])):
            conn.execute("UPDATE moves SET status='missing' WHERE id=?", (r["id"],))
            res.missing.append(r["dst"])
            continue
        target = r["src"]
        if os.path.lexists(io_path(target)):  # su lugar original fue ocupado: no se pisa
            base, ext = os.path.splitext(target)
            target = unique_path(f"{base} (restaurado){ext}")
        try:
            if r["action"] == "move_dir":
                os.makedirs(io_path(os.path.dirname(target)), exist_ok=True)
                os.rename(io_path(r["dst"]), io_path(target))
            else:
                _move_file(r["dst"], target, os.path.getsize(io_path(r["dst"])))
        except OSError as e:
            res.failed.append(f"{r['dst']}: {e}")
            continue
        conn.execute("UPDATE moves SET status='undone', undone_ts=? WHERE id=?", (_now(), r["id"]))
        _record(conn, ub, r["dst"], target, "undo", r["size"], f"deshace movimiento #{r['id']}", None)
        res.restored += 1
    conn.commit()
    return res


def history(conn: sqlite3.Connection, limit: int = 30, text: str | None = None) -> list[sqlite3.Row]:
    sql, params = "SELECT * FROM moves", []
    if text:
        sql += " WHERE src LIKE ? OR dst LIKE ?"
        params += [f"%{text}%"] * 2
    return conn.execute(sql + " ORDER BY id DESC LIMIT ?", (*params, limit)).fetchall()
