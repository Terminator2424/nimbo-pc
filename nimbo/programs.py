"""Inventario de programas instalados (solo lectura).

Fuentes en Windows: registro (Uninstall), `winget export`, apps de la Microsoft
Store (Get-AppxPackage) y juegos de Steam (appmanifest_*.acf).
En otros sistemas devuelve listas vacías con una nota; los parse_* son puros.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess  # nosec B404 - solo comandos fijos (winget, powershell, git); ver docs/SECURITY_MODEL.md
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class ProgramsResult:
    programs: list[dict] = field(default_factory=list)
    steam_games: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    winget_export_raw: str | None = None


def _norm_date(value: str | None) -> str | None:
    if value and re.fullmatch(r"\d{8}", value):
        return f"{value[:4]}-{value[4:6]}-{value[6:]}"
    return value or None


def _prog(
    source, name, version=None, publisher=None, install_date=None, install_location=None, size_kb=None, identifier=None
) -> dict:
    return {
        "source": source,
        "name": name,
        "version": version,
        "publisher": publisher,
        "install_date": install_date,
        "install_location": install_location,
        "size_kb": size_kb,
        "identifier": identifier,
    }


# -------------------------------------------------------------- registro


def read_uninstall_registry() -> list[dict]:
    if os.name != "nt":
        return []
    import winreg

    sub = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
    sources = [
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY),
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY),
        (winreg.HKEY_CURRENT_USER, 0),
    ]
    found: dict[tuple[str, str], dict] = {}
    for hive, flag in sources:
        try:
            root = winreg.OpenKey(hive, sub, 0, winreg.KEY_READ | flag)
        except OSError:
            continue
        with root:
            for i in range(winreg.QueryInfoKey(root)[0]):
                try:
                    key_name = winreg.EnumKey(root, i)
                    with winreg.OpenKey(root, key_name) as sk:

                        def val(n):
                            try:
                                return winreg.QueryValueEx(sk, n)[0]
                            except OSError:
                                return None

                        name = val("DisplayName")
                        if not name or val("SystemComponent") == 1 or val("ParentKeyName"):
                            continue
                        if val("ReleaseType") in ("Update", "Hotfix", "Security Update"):
                            continue
                        size = val("EstimatedSize")
                        entry = _prog(
                            "registro",
                            str(name).strip(),
                            str(val("DisplayVersion") or "") or None,
                            str(val("Publisher") or "") or None,
                            _norm_date(str(val("InstallDate") or "")),
                            str(val("InstallLocation") or "") or None,
                            int(size) if isinstance(size, int) else None,
                            key_name,
                        )
                        found.setdefault((entry["name"].lower(), entry["version"] or ""), entry)
                except OSError:
                    continue
    return list(found.values())


# ---------------------------------------------------------------- winget


def parse_winget_export(raw: str) -> list[dict]:
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return []
    out = []
    for src in (data.get("Sources") or []) if isinstance(data, dict) else []:
        for pk in src.get("Packages") or []:
            ident = pk.get("PackageIdentifier")
            if ident:
                out.append(_prog("winget", ident, pk.get("Version"), identifier=ident))
    return out


def run_winget_export() -> tuple[list[dict], str | None, str | None]:
    if not shutil.which("winget"):
        return [], None, "winget no está disponible."
    tmp = Path(tempfile.mkdtemp()) / "winget.json"
    try:
        subprocess.run(
            ["winget", "export", "-o", str(tmp), "--accept-source-agreements"],  # nosec B603 B607 - argumentos fijos
            capture_output=True,
            timeout=180,
            check=False,
        )
        raw = tmp.read_text(encoding="utf-8-sig") if tmp.exists() else None
    except (OSError, subprocess.SubprocessError) as e:
        return [], None, f"winget export falló: {e}"
    finally:
        shutil.rmtree(tmp.parent, ignore_errors=True)
    if not raw:
        return [], None, "winget export no produjo datos."
    return parse_winget_export(raw), raw, None


# ----------------------------------------------------------------- tienda


def parse_appx_json(raw: str) -> list[dict]:
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return []
    return [
        _prog("tienda", d["Name"], d.get("Version"), d.get("Publisher"), identifier=d["Name"])
        for d in data
        if isinstance(d, dict) and d.get("Name")
    ]


def read_store_apps() -> tuple[list[dict], str | None]:
    if os.name != "nt":
        return [], None
    cmd = [
        "powershell",
        "-NoProfile",
        "-Command",
        "Get-AppxPackage | Where-Object {$_.IsFramework -eq $false -and $_.SignatureKind -eq 'Store'} "
        "| Select-Object Name,Version,Publisher | ConvertTo-Json",
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False).stdout  # nosec B603 B607 - argumentos fijos
    except (OSError, subprocess.SubprocessError) as e:
        return [], f"No pude leer apps de la Tienda: {e}"
    return parse_appx_json(out), None


# ------------------------------------------------------------------ steam

_VDF_TOKEN = re.compile(r'"((?:[^"\\]|\\.)*)"|([{}])')


def parse_vdf(text: str) -> dict:
    """Parser mínimo de archivos VDF/ACF de Steam."""
    root: dict = {}
    stack = [root]
    key = None
    for m in _VDF_TOKEN.finditer(text):
        tok, brace = m.group(1), m.group(2)
        if brace == "{":
            new: dict = {}
            if key is not None:
                stack[-1][key] = new
            stack.append(new)
            key = None
        elif brace == "}":
            if len(stack) > 1:
                stack.pop()
            key = None
        else:
            tok = tok.replace("\\\\", "\\").replace('\\"', '"')
            if key is None:
                key = tok
            else:
                stack[-1][key] = tok
                key = None
    return root


def parse_library_folders(text: str) -> list[str]:
    data = parse_vdf(text)
    top = data.get("libraryfolders") or data.get("LibraryFolders") or {}
    libs: list[str] = []
    for k, v in top.items():
        if isinstance(v, dict) and v.get("path"):
            libs.append(v["path"])
        elif isinstance(v, str) and k.isdigit():  # formato antiguo
            libs.append(v)
    return libs


def _steam_dirs() -> list[Path]:
    dirs: list[Path] = []
    if os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
                dirs.append(Path(winreg.QueryValueEx(k, "SteamPath")[0]))
        except OSError:
            pass
        for env in ("ProgramFiles(x86)", "ProgramFiles"):
            if os.environ.get(env):
                dirs.append(Path(os.environ[env]) / "Steam")
    return [d for d in dirs if d.is_dir()]


def read_steam_games(steam_dirs: list[Path] | None = None) -> list[dict]:
    libs: dict[str, Path] = {}
    for sd in steam_dirs if steam_dirs is not None else _steam_dirs():
        libs[str(sd)] = sd
        vdf = sd / "steamapps" / "libraryfolders.vdf"
        try:
            for p in parse_library_folders(vdf.read_text(encoding="utf-8", errors="replace")):
                libs.setdefault(p, Path(p))
        except OSError:
            pass
    games = []
    for lib in libs.values():
        apps = lib / "steamapps"
        if not apps.is_dir():
            continue
        for acf in sorted(apps.glob("appmanifest_*.acf")):
            try:
                st = parse_vdf(acf.read_text(encoding="utf-8", errors="replace")).get("AppState", {})
            except OSError:
                continue
            if not st.get("appid"):
                continue
            size = st.get("SizeOnDisk", "0")
            games.append(
                {
                    "appid": st["appid"],
                    "name": st.get("name", st["appid"]),
                    "install_dir": str(apps / "common" / st.get("installdir", "")),
                    "size_bytes": int(size) if str(size).isdigit() else 0,
                    "library": str(lib),
                }
            )
    return games


# -------------------------------------------------------------- orquestación


def collect_all(use_winget: bool = True) -> ProgramsResult:
    res = ProgramsResult()
    if os.name != "nt":
        res.notes.append("Este sistema no es Windows: el inventario de programas solo funciona en Windows.")
    res.programs += read_uninstall_registry()
    if use_winget:
        pk, raw, note = run_winget_export()
        res.programs += pk
        res.winget_export_raw = raw
        if note and os.name == "nt":
            res.notes.append(note)
    store, note = read_store_apps()
    res.programs += store
    if note:
        res.notes.append(note)
    res.steam_games = read_steam_games()
    return res


def save_programs(conn: sqlite3.Connection, res: ProgramsResult) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute("DELETE FROM programs")
    conn.execute("DELETE FROM steam_games")
    conn.executemany(
        "INSERT INTO programs(source,name,version,publisher,install_date,install_location,"
        "size_kb,identifier,collected_at) VALUES (?,?,?,?,?,?,?,?,?)",
        [
            (
                p["source"],
                p["name"],
                p["version"],
                p["publisher"],
                p["install_date"],
                p["install_location"],
                p["size_kb"],
                p["identifier"],
                now,
            )
            for p in res.programs
        ],
    )
    conn.executemany(
        "INSERT INTO steam_games(appid,name,install_dir,size_bytes,library,collected_at) VALUES (?,?,?,?,?,?)",
        [(g["appid"], g["name"], g["install_dir"], g["size_bytes"], g["library"], now) for g in res.steam_games],
    )
    conn.commit()
