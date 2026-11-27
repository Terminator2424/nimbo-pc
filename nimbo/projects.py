"""Descubre proyectos de código en todo el PC (solo lectura), aunque tengan nombres como 1234567.

Se reconocen por su CONTENIDO (git, package.json, pyproject.toml, .sln...), no por el nombre de la carpeta.
Confianza 'alta' = marcador fuerte; 'media' = pistas débiles (varios archivos de código + requirements/index.html...).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from collections.abc import Callable

from . import config as cfg
from .pathutil import io_path
from .protect import Protection
from .scanner import _is_link, _measure

STRONG_FILES = {
    ".git": "git",
    "package.json": "node",
    "pyproject.toml": "python",
    "setup.py": "python",
    "cargo.toml": "rust",
    "go.mod": "go",
    "pom.xml": "java",
    "build.gradle": "java",
    "build.gradle.kts": "java",
    "composer.json": "php",
    "cmakelists.txt": "c/c++",
    "gemfile": "ruby",
    "pubspec.yaml": "dart",
    "project.godot": "godot",
}
STRONG_SUFFIXES = {".sln": ".net", ".csproj": ".net", ".uproject": "unreal", ".ino": "arduino"}
WEAK_FILES = {"requirements.txt", "makefile", "index.html", "main.py", "app.py", "main.js"}
CODE_EXTS = {".py", ".js", ".ts", ".java", ".c", ".cpp", ".h", ".cs", ".go", ".rs", ".html", ".css", ".ipynb", ".php"}
VENV_NAMES = {".venv", "venv", "env"}
_CRYPTIC = re.compile(r"^[\d\W_]+$|^(new folder|nueva carpeta)( \(\d+\))?$", re.I)
MAX_DEPTH = 8


@dataclass
class Project:
    path: str
    kinds: list[str]
    confidence: str  # alta | media
    name_guess: str
    cryptic: bool
    size: int = 0
    files: int = 0
    newest_mtime: float = 0.0
    has_git: bool = False
    venvs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def fixed_drives() -> list[Path]:
    """Discos fijos de Windows (no USB ni red). En otros sistemas, lista vacía."""
    if os.name != "nt":
        return []
    import ctypes
    import string

    kernel = ctypes.windll.kernel32
    mask = kernel.GetLogicalDrives()
    out = []
    for i, letter in enumerate(string.ascii_uppercase):
        root = f"{letter}:\\"
        if mask & (1 << i) and kernel.GetDriveTypeW(root) == 3:  # 3 = DRIVE_FIXED
            out.append(Path(root))
    return out


def _read(path: str, limit: int = 65536) -> str:
    try:
        with open(io_path(path), encoding="utf-8", errors="replace") as f:
            return f.read(limit)
    except OSError:
        return ""


def sanitize_name(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name).strip(" .")[:60]


def guess_name(path: str, lower_names: set[str]) -> str:
    """Nombre legible a partir del contenido (package.json, pyproject, remoto git, README)."""
    g = ""
    if "package.json" in lower_names:
        try:
            g = str(json.loads(_read(os.path.join(path, "package.json"))).get("name", ""))
        except ValueError:
            pass
    if not g and "pyproject.toml" in lower_names:
        m = re.search(r'^name\s*=\s*"([^"]+)"', _read(os.path.join(path, "pyproject.toml")), re.M)
        g = m.group(1) if m else ""
    if not g and "cargo.toml" in lower_names:
        m = re.search(r'^name\s*=\s*"([^"]+)"', _read(os.path.join(path, "Cargo.toml")), re.M)
        g = m.group(1) if m else ""
    if not g and "go.mod" in lower_names:
        m = re.search(r"^module\s+(\S+)", _read(os.path.join(path, "go.mod")), re.M)
        g = m.group(1).rsplit("/", 1)[-1] if m else ""
    if not g and "pom.xml" in lower_names:
        m = re.search(r"<artifactId>([^<]+)</artifactId>", _read(os.path.join(path, "pom.xml")))
        g = m.group(1) if m else ""
    if not g and ".git" in lower_names:
        m = re.search(r"url\s*=\s*(\S+)", _read(os.path.join(path, ".git", "config")))
        g = re.sub(r"\.git$", "", m.group(1).rstrip("/")).rsplit("/", 1)[-1] if m else ""
    if not g:
        for n in ("README.md", "readme.md", "README.txt"):
            m = re.search(r"^#\s+(.+)$", _read(os.path.join(path, n), 4096), re.M)
            if m:
                g = m.group(1)
                break
    g = sanitize_name(g.split("/")[-1])
    return g or sanitize_name(os.path.basename(path))


def classify_dir(names_lower: set[str], files: list[str]) -> tuple[list[str], str] | None:
    kinds = {v for k, v in STRONG_FILES.items() if k in names_lower}
    kinds |= {v for n in names_lower for s, v in STRONG_SUFFIXES.items() if n.endswith(s)}
    if kinds:
        return sorted(kinds), "alta"
    weak = names_lower & WEAK_FILES
    code = sum(1 for f in files if os.path.splitext(f)[1].lower() in CODE_EXTS)
    if weak and code >= 2:
        return ["código (pistas débiles)"], "media"
    return None


def discover_projects(
    roots: list[Path],
    protection: Protection | None = None,
    max_depth: int = MAX_DEPTH,
    measure: bool = True,
    progress: Callable[[int, int], None] | None = None,
) -> list[Project]:
    found: list[Project] = []
    seen_dirs = 0
    skip = {n.lower() for n in cfg.PROTECTED_DIR_NAMES} | {"onedrivetemp", "$windows.~bt"}
    for root in roots:
        stack: list[tuple[str, int]] = [(str(root), 0)]
        while stack:
            cur, depth = stack.pop()
            try:
                entries = list(os.scandir(io_path(cur)))
            except OSError:
                continue
            seen_dirs += 1
            if progress and seen_dirs % 200 == 0:
                progress(seen_dirs, len(found))
            names_lower = {e.name.lower() for e in entries}
            files = [e.name for e in entries if e.is_file(follow_symlinks=False)]
            hit = classify_dir(names_lower, files)
            if hit and not (protection and protection.is_protected_path(cur)):
                kinds, conf = hit
                p = Project(
                    cur,
                    kinds,
                    conf,
                    guess_name(cur, names_lower),
                    bool(_CRYPTIC.match(os.path.basename(cur.rstrip("\\/")) or "x")),
                    has_git=".git" in names_lower,
                )
                for e in entries:
                    try:
                        if (
                            e.is_dir(follow_symlinks=False)
                            and not _is_link(e)
                            and (
                                e.name.lower() in VENV_NAMES or os.path.exists(os.path.join(cur, e.name, "pyvenv.cfg"))
                            )
                        ):
                            p.venvs.append(e.name)
                        p.newest_mtime = max(p.newest_mtime, e.stat(follow_symlinks=False).st_mtime)
                    except OSError:
                        continue
                if measure:
                    p.size, p.files = _measure(cur)
                found.append(p)
                continue  # no se entra a un proyecto: lo de adentro es parte de él
            if depth >= max_depth:
                continue
            for e in entries:
                try:
                    if (
                        e.is_dir(follow_symlinks=False)
                        and not _is_link(e)
                        and e.name.lower() not in skip
                        and not e.name.startswith(".")
                    ):
                        stack.append((os.path.join(cur, e.name), depth + 1))
                except OSError:
                    continue
    found.sort(key=lambda p: p.newest_mtime, reverse=True)
    return found
