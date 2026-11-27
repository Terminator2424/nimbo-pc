"""Informes (Markdown + JSON + CSV) a partir de la base de datos."""

from __future__ import annotations

import csv
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from .db import last_scan
from .duplicates import duplicate_groups
from .pathutil import fmt_int, fmt_pct, fmt_size


def _q(conn: sqlite3.Connection, sql: str, params: tuple = ()):
    return conn.execute(sql, params).fetchall()


def build_summary(conn: sqlite3.Connection, min_dupe_size: int = 1) -> dict:
    scan = last_scan(conn)
    local = _q(conn, "SELECT COUNT(*) n, COALESCE(SUM(size),0) b FROM files WHERE cloud_only=0")[0]
    cloud = _q(conn, "SELECT COUNT(*) n, COALESCE(SUM(size),0) b FROM files WHERE cloud_only=1")[0]
    groups = duplicate_groups(conn, min_dupe_size)
    return {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "scan": dict(scan) if scan else None,
        "local": {"files": local["n"], "bytes": local["b"]},
        "cloud_only": {"files": cloud["n"], "bytes": cloud["b"]},
        "empty_files": _q(conn, "SELECT COUNT(*) n FROM files WHERE size=0")[0]["n"],
        "categories": [
            dict(r)
            for r in _q(
                conn,
                "SELECT category, COUNT(*) files, COALESCE(SUM(size),0) bytes FROM files "
                "WHERE cloud_only=0 GROUP BY category ORDER BY bytes DESC",
            )
        ],
        "roots": [
            dict(r)
            for r in _q(
                conn, "SELECT path, total_size bytes, total_files files FROM dirs WHERE depth=0 ORDER BY bytes DESC"
            )
        ],
        "top_dirs": [
            dict(r)
            for r in _q(
                conn,
                "SELECT path, kind, total_size bytes, total_files files FROM dirs "
                "WHERE depth BETWEEN 1 AND 3 ORDER BY bytes DESC LIMIT 25",
            )
        ],
        "top_files": [
            dict(r)
            for r in _q(
                conn, "SELECT path, size bytes, category FROM files WHERE cloud_only=0 ORDER BY size DESC LIMIT 20"
            )
        ],
        "opaque": [
            dict(r)
            for r in _q(
                conn,
                "SELECT path, kind, reason, direct_size bytes, direct_files files, measured FROM dirs "
                "WHERE kind!='normal' ORDER BY bytes DESC LIMIT 30",
            )
        ],
        "hints": {
            r["hint"]: {"files": r["n"], "bytes": r["b"]}
            for r in _q(
                conn,
                "SELECT hint, COUNT(*) n, COALESCE(SUM(size),0) b FROM files "
                "WHERE hint IS NOT NULL AND cloud_only=0 GROUP BY hint",
            )
        },
        "errors": [
            dict(r)
            for r in _q(
                conn, "SELECT path, error FROM scan_errors WHERE scan_id=? LIMIT 50", (scan["id"] if scan else -1,)
            )
        ],
        "duplicates": {
            "groups": len(groups),
            "wasted": sum(g.wasted for g in groups),
            "hashed_files": _q(conn, "SELECT COUNT(*) n FROM files WHERE hash_full IS NOT NULL")[0]["n"],
        },
        "programs": [
            dict(r)
            for r in _q(
                conn, "SELECT source, name, version, publisher, size_kb FROM programs ORDER BY name COLLATE NOCASE"
            )
        ],
        "steam_games": [
            dict(r)
            for r in _q(conn, "SELECT appid, name, size_bytes, library FROM steam_games ORDER BY size_bytes DESC")
        ],
        "_groups": groups,
    }


def _markdown(s: dict, top_groups: int) -> str:
    L: list[str] = [
        "# Informe de Nimbo (Fase 1, solo lectura)",
        "",
        f"Generado: {s['generated']}",
        "",
        "> Este informe solo describe tu PC. Nimbo todavía **no mueve ni borra nada**.",
        "",
    ]
    if not s["scan"]:
        return "\n".join(L + ["No hay ningún escaneo. Ejecuta primero `scan`."])
    sc = s["scan"]
    L += [
        "## Resumen",
        "",
        f"- Escaneo #{sc['id']} ({sc['status']}), duración {sc['seconds']:.1f} s.",
        f"- Archivos en disco: **{fmt_int(s['local']['files'])}** ({fmt_size(s['local']['bytes'])}).",
        f"- Archivos vacíos (0 bytes): {s['empty_files']}.",
    ]
    if s["cloud_only"]["files"]:
        L.append(f"- Solo en la nube (OneDrive, no leídos): {fmt_int(s['cloud_only']['files'])}.")
    if s["errors"]:
        L.append(f"- Errores de acceso: {len(s['errors'])} (abajo).")
    L += ["", "## Por categoría", "", "| Categoría | Archivos | Tamaño | % del espacio |", "|---|---:|---:|---:|"]
    for c in s["categories"]:
        L.append(
            f"| {c['category']} | {fmt_int(c['files'])} | {fmt_size(c['bytes'])} | "
            f"{fmt_pct(c['bytes'], s['local']['bytes'])} |"
        )
    L += [
        "",
        "_Nota: en Descargas los `.exe` suelen ser instaladores; se revisan a mano en la Fase 2._",
        "",
        "## Peso de cada carpeta raíz",
        "",
    ]
    L += [f"- `{r['path']}`: {fmt_size(r['bytes'])} en {fmt_int(r['files'])} archivos" for r in s["roots"]]
    L += ["", "## Carpetas más pesadas (hasta 3 niveles)", ""]
    L += [f"- {fmt_size(d['bytes'])}: `{d['path']}` ({fmt_int(d['files'])} archivos)" for d in s["top_dirs"]]
    L += ["", "## Archivos más grandes", ""]
    L += [f"- {fmt_size(f['bytes'])}: `{f['path']}` ({f['category']})" for f in s["top_files"]]
    L += [
        "",
        "## Zonas protegidas y proyectos",
        "",
        "Estas carpetas **no se tocarán** nunca (solo se mide su tamaño).",
        "",
    ]
    L += [f"- `{o['path']}`: {o['reason']}, {fmt_size(o['bytes'])}" for o in s["opaque"]] or ["- Ninguna."]
    if s["hints"]:
        L += ["", "## Pistas de origen", ""]
        L += [f"- {k}: {fmt_int(v['files'])} archivos ({fmt_size(v['bytes'])})" for k, v in s["hints"].items()]
    d = s["duplicates"]
    L += ["", "## Duplicados", ""]
    if not d["hashed_files"]:
        L.append("Aún no se buscaron duplicados. Ejecuta `dupes`.")
    else:
        L.append(f"**{d['groups']}** grupos; sobran **{fmt_size(d['wasted'])}**. `*` = copia sugerida para conservar.")
        for g in s["_groups"][:top_groups]:
            L += ["", f"- {fmt_size(g.size)} × {len(g.paths)} (sobran {fmt_size(g.wasted)})"]
            L += [f"  - {'*' if i == 0 else ' '} `{p}`" for i, p in enumerate(g.paths)]
    if s["programs"] or s["steam_games"]:
        L += ["", "## Programas instalados", ""]
        L += [f"- {p['name']} {p['version'] or ''} [{p['source']}]".replace("  ", " ") for p in s["programs"]]
        if s["steam_games"]:
            L += ["", "### Juegos de Steam", ""]
            L += [
                f"- {g['name']}: {fmt_size(g['bytes'] if 'bytes' in g else g['size_bytes'])}" for g in s["steam_games"]
            ]
    if s["errors"]:
        L += ["", "## Errores de acceso", ""] + [f"- `{e['path']}`: {e['error']}" for e in s["errors"]]
    return "\n".join(L) + "\n"


def generate_report(
    conn: sqlite3.Connection, out_dir: str | Path, min_dupe_size: int = 1, top_groups: int = 40
) -> dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    s = build_summary(conn, min_dupe_size)
    groups = s.pop("_groups")
    s["_groups"] = groups
    files: dict[str, Path] = {}
    files["informe"] = out / "informe.md"
    files["informe"].write_text(_markdown(s, top_groups), encoding="utf-8")
    s.pop("_groups")
    files["resumen"] = out / "resumen.json"
    files["resumen"].write_text(json.dumps(s, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    files["duplicados"] = out / "duplicados.csv"
    with open(files["duplicados"], "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["grupo", "tamano_bytes", "sobran_bytes", "sugerida_para_conservar", "ruta"])
        for i, g in enumerate(groups, 1):
            for j, p in enumerate(g.paths):
                w.writerow([i, g.size, g.wasted, "si" if j == 0 else "no", p])
    if s["programs"]:
        files["programas"] = out / "programas.csv"
        with open(files["programas"], "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["fuente", "nombre", "version", "editor", "tamano_kb"])
            for p in s["programs"]:
                w.writerow([p["source"], p["name"], p["version"], p["publisher"], p["size_kb"]])
    return files
