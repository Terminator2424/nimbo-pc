"""Reúne proyectos en una carpeta (C:\\Users\\TU\\Proyectos) con verificación y reversión automática.

Cómo cambia las cosas (y por qué es seguro):
  1. Solo renombra la carpeta entera en el MISMO disco (operación atómica: no copia ni borra datos).
  2. Antes y después compara un manifiesto (cantidad de archivos, bytes y huella de rutas+tamaños)
     y, si es un repositorio git, el resultado de `git status`. Si algo no coincide, lo devuelve solo.
  3. Cada movimiento queda en el historial (antes/después) y se puede deshacer.
  4. Por defecto NO mueve proyectos con entorno virtual de Python (moverlo lo rompe).
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import subprocess  # nosec B404 - solo comandos fijos (winget, powershell, git); ver docs/SECURITY_MODEL.md
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .journal import _record, unique_path
from .pathutil import io_path, is_under, norm
from .projects import Project, sanitize_name

CONF_RANK = {"media": 0, "alta": 1}


@dataclass
class ProjectMove:
    src: str
    dst: str
    name: str
    size: int = 0
    files: int = 0
    has_git: bool = False
    note: str = ""


@dataclass
class GatherPlan:
    moves: list[ProjectMove] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)


@dataclass
class GatherResult:
    batch_id: int | None = None
    moved: int = 0
    reverted: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)


def _drive(path: str) -> str:
    d = os.path.splitdrive(os.path.abspath(path))[0].upper()
    if d:
        return d
    probe = os.path.abspath(path)
    while not os.path.exists(probe):
        probe = os.path.dirname(probe)
    return str(os.stat(probe).st_dev)


def plan_gather(
    projects: list[Project],
    dest_root: Path,
    protection=None,
    rename: bool = False,
    allow_venv: bool = False,
    min_confidence: str = "alta",
) -> GatherPlan:
    plan = GatherPlan()
    taken: set[str] = set()
    dest_n = norm(str(dest_root))

    def skip(p: Project, why: str) -> None:
        plan.skipped.append({"src": p.path, "reason": why})

    for p in projects:
        if CONF_RANK[p.confidence] < CONF_RANK[min_confidence]:
            skip(p, "pistas débiles: no estoy seguro de que sea un proyecto")
        elif is_under(norm(p.path), dest_n):
            continue  # ya está en su sitio
        elif protection and protection.is_protected_path(p.path):
            skip(p, "zona protegida")
        elif p.venvs and not allow_venv:
            skip(p, f"tiene entorno virtual ({', '.join(p.venvs)}): moverlo lo rompe; recréalo con python -m venv")
        elif _drive(p.path) != _drive(str(dest_root)):
            skip(p, "está en otro disco: se mueve a mano por seguridad (no se copia ni se borra nada)")
        else:
            base = sanitize_name(p.name_guess) if rename else os.path.basename(p.path.rstrip("\\/"))
            dst = unique_path(str(dest_root / (base or "proyecto")))
            n = 2
            while norm(dst) in taken:  # dos proyectos con el mismo nombre en este mismo plan
                dst = unique_path(f"{dest_root / (base or 'proyecto')} ({n})")
                n += 1
            taken.add(norm(dst))
            plan.moves.append(
                ProjectMove(
                    p.path,
                    dst,
                    base,
                    p.size,
                    p.files,
                    p.has_git,
                    "sin entorno virtual" if not p.venvs else "con entorno virtual (lo pediste)",
                )
            )
    return plan


def tree_manifest(path: str) -> tuple[int, int, str]:
    """(archivos, bytes, huella sha256 de 'ruta relativa + tamaño'). No sigue enlaces."""
    rows: list[str] = []
    total = 0
    stack = [path]
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(io_path(cur)) as it:
                for e in it:
                    rel = os.path.relpath(os.path.join(cur, e.name), path)
                    if e.is_symlink():
                        rows.append(f"{rel}\t->")
                    elif e.is_dir(follow_symlinks=False):
                        rows.append(f"{rel}\t/")
                        stack.append(os.path.join(cur, e.name))
                    else:
                        size = e.stat(follow_symlinks=False).st_size
                        total += size
                        rows.append(f"{rel}\t{size}")
        except OSError:
            rows.append(f"{os.path.relpath(cur, path)}\t?")
    rows.sort()
    return len(rows), total, hashlib.sha256("\n".join(rows).encode("utf-8", "replace")).hexdigest()


def git_state(path: str) -> str | None:
    """Salida de `git status --porcelain` (None si no hay git o no es un repo)."""
    exe = shutil.which("git")
    if not exe:
        return None
    try:
        out = subprocess.run(
            [exe, "-C", path, "status", "--porcelain"],
            capture_output=True,  # nosec B603
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


def execute_gather(conn: sqlite3.Connection, plan: GatherPlan, log=print) -> GatherResult:
    res = GatherResult()
    for m in plan.moves:
        before = tree_manifest(m.src)
        git_before = git_state(m.src) if m.has_git else None
        try:
            os.makedirs(io_path(os.path.dirname(m.dst)), exist_ok=True)
            if os.path.lexists(io_path(m.dst)):
                raise FileExistsError(m.dst)
            os.rename(io_path(m.src), io_path(m.dst))  # atómico, mismo disco; falla si algo lo usa
        except OSError as e:
            res.failed.append(f"{m.src}: no se pudo mover ({e}). No cambió nada.")
            continue
        problem = None
        if tree_manifest(m.dst) != before:
            problem = "el contenido no coincide con el original"
        elif m.has_git and git_before is not None and git_state(m.dst) != git_before:
            problem = "git ve cambios distintos tras mover"
        if problem:
            try:
                os.rename(io_path(m.dst), io_path(m.src))
                res.reverted.append(f"{m.src}: {problem}; lo devolví a su lugar.")
            except OSError as e:
                res.failed.append(f"{m.src}: {problem} y NO pude revertir ({e}). Está en {m.dst}")
            continue
        if res.batch_id is None:
            res.batch_id = conn.execute(
                "INSERT INTO batches(ts, kind, note) VALUES (?,?,?)",
                (datetime.now().isoformat(timespec="seconds"), "projects", "reunir proyectos"),
            ).lastrowid
        _record(conn, res.batch_id, m.src, m.dst, "move_dir", m.size, f"proyecto verificado ({m.files} archivos)", 1.0)
        res.moved += 1
        log(f"  OK  {m.src}\n   -> {m.dst}")
    return res
