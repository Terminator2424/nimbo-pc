"""Configuración, categorías y reglas de protección."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path

APP_NAME = "Nimbo"
SCHEMA_VERSION = 1


def data_dir() -> Path:
    """Carpeta de la base de datos e informes (fuera de lo escaneado)."""
    override = os.environ.get("NIMBO_HOME")
    if override:
        return Path(override)
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / APP_NAME
    return Path.home() / ".nimbo"


LEGACY_NAME = "OrdenaPC"  # nombre anterior del proyecto (Nimbo se llamaba así)


def migrate_legacy_data() -> bool:
    """Si quedaron datos del nombre anterior (historial, reglas, configuración), los mueve a la carpeta nueva.

    Así actualizar no hace perder el «deshacer». No hace nada si NIMBO_HOME está definida o si ya hay datos nuevos.
    """
    if os.environ.get("NIMBO_HOME"):
        return False
    new = data_dir()
    old = new.parent / LEGACY_NAME if os.name == "nt" else Path.home() / ".ordenapc"
    if not old.is_dir():
        return False
    try:
        if new.exists():
            if any(new.iterdir()):
                return False  # ya hay datos nuevos: no se pisan
            new.rmdir()  # carpeta vacía creada por una apertura previa
        old.rename(new)
        for suffix in ("", "-wal", "-shm"):
            legacy = new / f"ordenapc.db{suffix}"
            if legacy.exists():
                legacy.rename(new / f"nimbo.db{suffix}")
    except OSError:
        return False
    _rewrite_journal_paths(new / "nimbo.db", str(old), str(new))
    return True


def _rewrite_journal_paths(db: Path, old: str, new: str) -> None:
    """Los archivos en cuarentena viven dentro de la carpeta de datos: se corrigen sus rutas en el historial."""
    if not db.exists():
        return
    try:
        with closing(sqlite3.connect(str(db))) as conn:
            conn.execute(
                "UPDATE moves SET dst = ? || substr(dst, ?) WHERE substr(dst, 1, ?) = ?",
                (new, len(old) + 1, len(old), old),
            )
            conn.commit()
    except sqlite3.Error:
        pass  # sin historial que corregir (base nueva o sin la tabla)


def default_db_path() -> Path:
    return data_dir() / "nimbo.db"


def user_config_path() -> Path:
    return data_dir() / "config.json"


def load_user_config() -> dict:
    """config.json opcional: {"roots": [...], "extra_protected": [...]}"""
    try:
        with open(user_config_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_user_config(update: dict) -> None:
    data = load_user_config()
    data.update(update)
    user_config_path().parent.mkdir(parents=True, exist_ok=True)
    user_config_path().write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def windows_known_folders() -> dict[str, Path]:
    """Rutas reales de Escritorio, Documentos, etc. (respeta OneDrive)."""
    if os.name != "nt":
        return {}
    try:
        import winreg
    except ImportError:  # pragma: no cover
        return {}
    wanted = {
        "Desktop": "Desktop",
        "Personal": "Documents",
        "My Pictures": "Pictures",
        "My Video": "Videos",
        "My Music": "Music",
        "{374DE290-123F-4565-9164-39C4925E467B}": "Downloads",
    }
    out: dict[str, Path] = {}
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
        )
    except OSError:
        return {}
    with key:
        for value_name, label in wanted.items():
            try:
                raw, _ = winreg.QueryValueEx(key, value_name)
            except OSError:
                continue
            out[label] = Path(os.path.expandvars(raw))
    return out


def default_roots() -> list[Path]:
    home = Path.home()
    candidates: dict[str, Path] = {
        label: home / label for label in ("Downloads", "Desktop", "Documents", "Pictures", "Videos", "Music")
    }
    candidates.update(windows_known_folders())
    roots: list[Path] = []
    for p in candidates.values():
        if p.is_dir() and p not in roots:
            roots.append(p)
    return roots


def known_dir(label: str) -> Path:
    """Escritorio, Descargas, etc. reales (respeta OneDrive y el idioma de Windows)."""
    return windows_known_folders().get(label) or Path.home() / label


def inbox_dirs() -> list[Path]:
    """Carpetas de entrada que se ordenan solas: Descargas y Escritorio (config.json: "inbox")."""
    user = load_user_config().get("inbox")
    if user:
        return [Path(p) for p in user]
    return [d for d in (known_dir("Downloads"), known_dir("Desktop")) if d.is_dir()]


# ------------------------------------------------------------ protección

# Carpetas (nombre en minúsculas) que nunca se recorren por dentro.
PROTECTED_DIR_NAMES = {
    ".git",
    ".svn",
    ".hg",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    ".tox",
    ".idea",
    ".vs",
    "site-packages",
    "windows",
    "program files",
    "program files (x86)",
    "programdata",
    "appdata",
    "steamapps",
    "$recycle.bin",
    "system volume information",
}

# Si una carpeta contiene alguno de estos archivos, es un proyecto: no se toca.
PROJECT_MARKER_FILES = {
    ".git",
    "package.json",
    "pom.xml",
    "pyproject.toml",
    "cargo.toml",
    "build.gradle",
    "build.gradle.kts",
    "go.mod",
    "composer.json",
    "setup.py",
}
PROJECT_MARKER_SUFFIXES = (".sln", ".csproj", ".uproject")

# ------------------------------------------------------------ categorías

_CATEGORIES: dict[str, str] = {
    "imagenes": ".jpg .jpeg .png .gif .bmp .webp .heic .tiff .tif .svg .raw .cr2 .nef .ico",
    "videos": ".mp4 .mkv .avi .mov .wmv .flv .webm .m4v .mpg .mpeg .3gp",
    "musica": ".mp3 .wav .flac .aac .ogg .m4a .wma .opus .mid",
    "documentos": ".pdf .doc .docx .txt .rtf .odt .md .epub .mobi .tex",
    "hojas_de_calculo": ".xls .xlsx .csv .ods .tsv",
    "presentaciones": ".ppt .pptx .odp .key",
    "comprimidos": ".zip .rar .7z .tar .gz .bz2 .xz .tgz",
    "ejecutables": ".exe .msi .msix .appx .bat .cmd .apk",
    "codigo": ".py .js .ts .java .c .cpp .h .cs .go .rs .php .html .css .json .xml .sql .ps1 .sh .ipynb",
    "modelos_ia": ".gguf .safetensors .ckpt .onnx .pt .pth .bin",
    "emulacion": ".iso .rom .sav .nes .smc .sfc .gba .gb .gbc .nds .n64 .z64 .cue .img",
    "atajos": ".lnk .url",
    "temporales": ".tmp .crdownload .part .partial .bak .log",
    "fuentes": ".ttf .otf .woff .woff2",
}
CATEGORY_BY_EXT: dict[str, str] = {ext: cat for cat, exts in _CATEGORIES.items() for ext in exts.split()}
