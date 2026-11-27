"""Línea de comandos: python -m nimbo <comando>."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from . import __version__
from . import config as cfg
from . import db as database
from .duplicates import find_duplicates
from .lab import LabError, create_lab
from .pathutil import fmt_int, fmt_size, parse_size
from .programs import collect_all, save_programs
from .report import generate_report
from .scanner import ScanOptions, scan
from .classifier import Layout, Plan, build_plan
from .journal import apply_plan, history, undo
from .programs import read_steam_games
from .protect import Protection
from .watcher import watch
from . import theme as themelib
from .doctor import run_checks
from .projects import discover_projects, fixed_drives
from .projmove import execute_gather, plan_gather
from . import ai as ailib
from . import keystore
from . import autostart
from .learning import add_rule, delete_rule, detect_corrections, load_rules

TTY = bool(sys.stdout and sys.stdout.isatty())
_OPEN_CONNS: list = []  # conexiones abiertas por el comando en curso; main() las cierra siempre


def _progress(files: int, dirs: int) -> None:
    if TTY:
        print(f"\r  escaneando... {fmt_int(files)} archivos", end="", flush=True)


def _end_progress() -> None:
    if TTY:
        print("\r" + " " * 60 + "\r", end="")


def _open_db(args):
    path = Path(args.db) if args.db else cfg.default_db_path()
    conn = database.connect(path)
    _OPEN_CONNS.append(conn)
    return conn, path


def _resolve_roots(args) -> list[Path]:
    if args.root:
        return [Path(r) for r in args.root]
    user_roots = cfg.load_user_config().get("roots") or []
    return [Path(r) for r in user_roots] or cfg.default_roots()


def cmd_scan(args) -> int:
    conn, db_path = _open_db(args)
    roots = _resolve_roots(args)
    if not roots:
        print("No encontré carpetas para escanear. Usa --root RUTA.")
        return 1
    extra = [Path(p) for p in (cfg.load_user_config().get("extra_protected") or [])]
    extra += [Path(p) for p in (args.protect or [])]
    options = ScanOptions(
        roots=roots,
        extra_protected=extra,
        exclude_dirs=[cfg.data_dir()],
        exclude_files=[db_path, Path(str(db_path) + "-wal"), Path(str(db_path) + "-shm")],
        measure_protected=not args.no_measure,
    )
    print("Escaneando (solo lectura, no se modifica nada):")
    for r in roots:
        print(f"  - {r}")
    res = scan(conn, options, progress=_progress)
    _end_progress()
    for w in res.warnings:
        print(f"AVISO: {w}")
    state = "completo" if res.status == "ok" else "INTERRUMPIDO (resultados parciales)"
    print(f"Escaneo {state} en {res.seconds:.1f} s")
    print(f"  Archivos: {fmt_int(res.files)} ({fmt_size(res.bytes)})")
    print(
        f"  Carpetas: {fmt_int(res.dirs)} · protegidas: {res.protected_dirs} · "
        f"proyectos: {res.project_dirs} · enlaces omitidos: {res.skipped_links}"
    )
    if res.cloud_only:
        print(f"  Solo en la nube (no leídos): {fmt_int(res.cloud_only)}")
    if res.errors:
        print(f"  Errores de acceso: {fmt_int(res.errors)} (ver informe)")
    print(f"  Base de datos: {db_path}")
    return 0 if res.status == "ok" else 2


def cmd_dupes(args) -> int:
    conn, _ = _open_db(args)
    min_size = parse_size(args.min_size)

    def prog(stage: str, done: int, total: int) -> None:
        if TTY:
            print(f"\r  hash {stage}: {done}/{total}", end="", flush=True)

    print("Buscando duplicados (solo lectura)...")
    try:
        groups, st = find_duplicates(conn, min_size=min_size, progress=prog)
    except KeyboardInterrupt:
        print("\nInterrumpido. Lo calculado queda guardado; vuelve a ejecutar para continuar.")
        return 2
    _end_progress()
    print(
        f"  Candidatos por tamaño: {st.candidates} · hashes rápidos: {st.quick_hashed} · "
        f"completos: {st.full_hashed} · errores: {st.errors}"
    )
    print(f"  Grupos de duplicados: {len(groups)} · espacio que sobra: {fmt_size(sum(g.wasted for g in groups))}")
    for g in groups[: args.top]:
        print(f"\n  {fmt_size(g.size)} × {len(g.paths)} (sobran {fmt_size(g.wasted)})")
        for i, p in enumerate(g.paths):
            print(f"    {'*' if i == 0 else ' '} {p}")
    print("\n  (*) = copia sugerida para conservar. No se borra nada.")
    return 0


def cmd_programs(args) -> int:
    conn, _ = _open_db(args)
    res = collect_all(use_winget=not args.no_winget)
    save_programs(conn, res)
    print(f"Programas: {len(res.programs)} · juegos de Steam: {len(res.steam_games)}")
    for n in res.notes:
        print(f"AVISO: {n}")
    out = Path(args.out) if args.out else cfg.data_dir() / "informes"
    if res.winget_export_raw:
        out.mkdir(parents=True, exist_ok=True)
        (out / "winget-export.json").write_text(res.winget_export_raw, encoding="utf-8")
        print(f'  Para reinstalar: winget import -i "{out / "winget-export.json"}"')
    return 0


def cmd_report(args) -> int:
    conn, _ = _open_db(args)
    out = Path(args.out) if args.out else cfg.data_dir() / "informes" / datetime.now().strftime("%Y%m%d-%H%M%S")
    files = generate_report(conn, out, min_dupe_size=parse_size(args.min_size))
    print(f"Informe generado en: {out}")
    for k, v in files.items():
        print(f"  {k}: {v}")
    return 0


def cmd_lab(args) -> int:
    try:
        c = create_lab(args.path, force=args.force)
    except LabError as e:
        print(f"ERROR: {e}")
        return 1
    print(f"Laboratorio creado en {args.path}: {c['files']} archivos, {fmt_size(c['bytes'])} (todo falso).")
    print(f'Pruébalo con: python -m nimbo scan --root "{args.path}" --db lab.db')
    return 0


def cmd_all(args) -> int:
    for fn in (cmd_scan, cmd_dupes, cmd_programs, cmd_report):
        rc = fn(args)
        if rc not in (0,):
            return rc
    return 0


# ------------------------------------------------- fases 2, 3 y vigilante


def _setup(args):
    conn, db_path = _open_db(args)
    if args.layout_root:
        root = Path(args.layout_root)
        layout = Layout.from_root(root)
        inbox = [Path(p) for p in args.inbox] if args.inbox else [root / "Descargas", root / "Escritorio"]
    else:
        layout = Layout.from_system()
        inbox = [Path(p) for p in args.inbox] if args.inbox else cfg.inbox_dirs()
    protection = Protection.from_system(conn, extra=[Path(p) for p in (args.protect or [])], inbox=inbox)
    return conn, layout, inbox, protection


def _print_plan(plan: Plan, limit: int) -> None:
    by_cat: dict[str, int] = {}
    for m in plan.moves:
        by_cat[m.category] = by_cat.get(m.category, 0) + 1
    print(f"Plan: {len(plan.moves)} movimientos propuestos · {len(plan.skipped)} archivos que NO se tocan")
    for c, n in sorted(by_cat.items(), key=lambda x: -x[1]):
        print(f"  {c}: {n}")
    for m in plan.moves[:limit]:
        print(f"\n  {m.src}\n    -> {m.dst}\n       {m.reason} (confianza {m.confidence})")
    if len(plan.moves) > limit:
        print(f"\n  ... y {len(plan.moves) - limit} más (están todos en el plan.json)")
    reasons: dict[str, int] = {}
    for sk in plan.skipped:
        reasons[sk["reason"]] = reasons.get(sk["reason"], 0) + 1
    if reasons:
        print("\nNo se tocan, por:")
        for r, n in sorted(reasons.items(), key=lambda x: -x[1]):
            print(f"  {n} × {r}")


def cmd_plan(args) -> int:
    conn, layout, inbox, protection = _setup(args)
    print("Carpetas de entrada:", ", ".join(str(i) for i in inbox) or "(ninguna)")
    plan = build_plan(inbox, layout, protection, deep=args.deep, settle_seconds=args.settle, rules=load_rules(conn))
    _print_plan(plan, args.top)
    out = Path(args.out) if args.out else cfg.data_dir() / "plan.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(plan.to_json(), encoding="utf-8")
    print(f"\nPlan guardado en {out}. SIMULACIÓN: no se movió nada. Para ejecutarlo: apply --yes")
    return 0


def cmd_apply(args) -> int:
    conn, layout, inbox, protection = _setup(args)
    if args.plan:
        plan = Plan.from_json(Path(args.plan).read_text(encoding="utf-8"))
    else:
        plan = build_plan(inbox, layout, protection, deep=args.deep, settle_seconds=args.settle, rules=load_rules(conn))
    if not args.yes:
        _print_plan(plan, args.top)
        print(
            "\nEsto fue una simulación. Agrega --yes para mover de verdad (todo queda en el historial y se puede deshacer)."
        )
        return 0
    r = apply_plan(conn, plan, layout, protection, inbox, note="apply")
    print(
        f"Movidos: {r.done} · a cuarentena (duplicados exactos): {r.quarantined} · "
        f"omitidos: {len(r.skipped)} · fallidos: {len(r.failed)} · lote #{r.batch_id}"
    )
    for line in (r.skipped + r.failed)[:20]:
        print("  -", line)
    if r.batch_id:
        print(f"Para deshacer este lote: undo --batch {r.batch_id}")
    return 0 if not r.failed else 2


def cmd_undo(args) -> int:
    conn, _ = _open_db(args)
    if not (args.everything or args.batch or args.last):
        print("Indica qué deshacer: --last, --batch N o --all")
        return 1
    r = undo(conn, batch_id=args.batch, everything=args.everything)
    print(f"Restaurados: {r.restored} · ya no estaban: {len(r.missing)} · fallidos: {len(r.failed)}")
    for line in (r.missing + r.failed)[:20]:
        print("  -", line)
    return 0 if not r.failed else 2


def cmd_history(args) -> int:
    conn, _ = _open_db(args)
    rows = history(conn, args.limit, args.search)
    if not rows:
        print("Sin movimientos en el historial.")
    for r in rows:
        print(
            f"#{r['id']} lote {r['batch_id']} · {r['ts']} · {r['action']} · {r['status']}\n"
            f"    antes:   {r['src']}\n    después: {r['dst']}"
        )
    return 0


def cmd_watch(args) -> int:
    conn, layout, inbox, protection = _setup(args)
    print("Vigilando:", ", ".join(str(i) for i in inbox))
    print("Modo:", "MOVIENDO de verdad" if args.apply else "solo simulación (agrega --apply para mover)")
    print("Ctrl+C para detener.")
    watch(conn, inbox, layout, protection, apply=args.apply, interval=args.interval, settle=args.settle, deep=args.deep)
    return 0


def cmd_games(args) -> int:
    games = read_steam_games()
    if not games:
        print("No encontré juegos de Steam (o no estás en Windows).")
    for g in games:
        print(f"  {g['name']}: {fmt_size(g['size_bytes'])} en {g['install_dir']}")
    print("\nLas bibliotecas de Steam quedan protegidas automáticamente. Otros programas y juegos")
    print("(Epic, GOG, emuladores) se protegen por su ruta de instalación si corriste `programs`;")
    print("para carpetas extra usa --protect RUTA o config.json -> extra_protected.")
    return 0


# ----------------------------------------------------- fases 4, 5 y 6


def cmd_ui(args) -> int:
    from .ui import run

    return run(start_hidden=args.tray, layout_root=args.layout_root, db=args.db)


def cmd_autostart(args) -> int:
    if args.mode == "status":
        print("Inicio con Windows:", "ACTIVADO" if autostart.is_enabled() else "desactivado")
        return 0
    ok = autostart.set_enabled(args.mode == "on")
    print("Listo." if ok else "No se pudo cambiar (¿no estás en Windows?).")
    return 0 if ok else 1


def cmd_teach(args) -> int:
    conn, _ = _open_db(args)
    rid = add_rule(conn, args.ext, args.dest, hint=args.hint or "")
    print(f"Regla #{rid}: {args.ext}{' (' + args.hint + ')' if args.hint else ''} -> {args.dest}")
    return 0


def cmd_rules(args) -> int:
    conn, _ = _open_db(args)
    if args.delete:
        print("Borrada." if delete_rule(conn, args.delete) else "No existe esa regla.")
        return 0
    rules = load_rules(conn)
    for r in rules:
        print(f"#{r['id']} [{r['source']}] {r['ext']}{' (' + r['hint'] + ')' if r['hint'] else ''} -> {r['dest_dir']}")
    if not rules:
        print("Sin reglas propias todavía. Se crean con `teach` o aprendiendo de tus correcciones (`learn`).")
    return 0


def cmd_learn(args) -> int:
    conn, layout, inbox, _ = _setup(args)
    roots = [layout.pictures, layout.videos, layout.music, layout.documents, layout.downloads]
    msgs = detect_corrections(conn, [r for r in roots if r.is_dir()], inbox)
    print("\n".join(msgs) if msgs else "No encontré correcciones tuyas nuevas.")
    return 0


def cmd_ai_suggest(args) -> int:
    conn, layout, inbox, protection = _setup(args)
    conf, problem = ailib.ai_status()
    if not conf:
        print(problem)
        print(
            "Configúrala con:  ai-connect  (Gemini, pega tu API key)  o  ai-config --provider local  (o desde Ajustes)"
        )
        return 1
    folder = Path(args.folder) if args.folder else None
    plan = build_plan(inbox, layout, protection, deep=args.deep, settle_seconds=args.settle, rules=load_rules(conn))
    cands = ailib.collect_candidates(plan, folder)
    donde = "tu PC" if not conf["remote"] else conf["url"]
    print(f"{len(cands)} archivos ambiguos; consultando a la IA ({conf['provider']}, {donde})...")
    errors: list[str] = []
    ids = ailib.make_suggestions(conn, cands, layout, conf, limit=args.limit, errors=errors)
    if errors:
        print(f"AVISO: {errors[0]}")
    print(f"{len(ids)} sugerencias nuevas. Revísalas con `suggestions` y aprueba con `accept`.")
    return 1 if errors and not ids else 0


def cmd_ai_config(args) -> int:
    ai = dict(cfg.load_user_config().get("ai") or {})
    changed = False
    if args.provider:
        ai["provider"] = args.provider
        changed = True
    for flag, key in ((args.model, "model"), (args.url, "url"), (args.mode, "mode")):
        if flag:
            ai[key] = flag
            changed = True
    if args.accept_remote:
        ai["consent"] = True
        sends = "solo el NOMBRE" if ai.get("mode", "names") == "names" else "el nombre y el inicio del contenido"
        print(f"Permiso concedido: se enviará {sends} de los archivos ambiguos al proveedor. Nunca archivos sensibles.")
        changed = True
    if args.revoke:
        ai["consent"] = False
        changed = True
    if changed:
        cfg.save_user_config({"ai": ai})
    conf, problem = ailib.ai_status()
    print(
        f"Proveedor: {ai.get('provider', '(sin configurar)')} · modelo: {ai.get('model') or '(por defecto)'}"
        f" · envío: {ai.get('mode', 'names')} · permiso remoto: {'sí' if ai.get('consent') else 'no'}"
        f" · clave guardada: {'sí' if keystore.has_key() else 'no'}"
    )
    print("Estado:", f"lista ({conf['model']})" if conf else problem)
    return 0


def cmd_ai_connect(args) -> int:
    """Pega la API key de Gemini: se valida, se elige el modelo y queda lista."""
    import getpass
    import os as _os

    key = (
        _os.environ.get(keystore.ENV_VAR, "").strip()
        or getpass.getpass("Pega tu API key de Gemini (no se mostrará): ").strip()
    )
    ai = dict(cfg.load_user_config().get("ai") or {})
    mode = args.mode or ai.get("mode") or "names"
    if not (ai.get("consent") and ai.get("provider") == "gemini"):
        sends = "solo el NOMBRE" if mode == "names" else "el nombre y el inicio del contenido (hasta 1200 caracteres)"
        print(f"Para sugerir carpetas se enviará {sends} de los archivos ambiguos a Google (Gemini) por internet.")
        print("Los archivos con nombres sensibles (contraseñas, claves, identidad) nunca se envían.")
        if not args.accept_remote and input("¿Permites el envío? [s/N] ").strip().lower() not in (
            "s",
            "si",
            "sí",
            "y",
            "yes",
        ):
            print("Cancelado: no se guardó nada.")
            return 1
    try:
        model = ailib.connect(key)
    except ailib.AIError as e:
        print(f"ERROR: {e}")
        return 1
    ai.update({"provider": "gemini", "model": model, "mode": mode, "consent": True})
    ai.pop("url", None)
    cfg.save_user_config({"ai": ai})
    saved = bool(key) and keystore.get_key() == key
    if not saved and not _os.environ.get(keystore.ENV_VAR):
        saved = keystore.set_key(key)
    print(f"✓ Conectado con Gemini (modelo {model}).")
    if not saved:
        print(f"AVISO: este sistema no puede cifrar la clave: define la variable {keystore.ENV_VAR} para usarla.")
    return 0


def cmd_ai_key(args) -> int:
    import getpass

    if args.clear:
        keystore.clear_key()
        print("Clave borrada.")
        return 0
    key = getpass.getpass("Pega tu clave de API (no se mostrará): ").strip()
    if not key:
        print("No escribiste nada.")
        return 1
    if keystore.set_key(key):
        print("Clave guardada, cifrada con tu cuenta de Windows.")
        return 0
    print(f"Este sistema no puede cifrarla. Usa la variable de entorno {keystore.ENV_VAR}.")
    return 1


def cmd_ai_test(args) -> int:
    conf, problem = ailib.ai_status()
    if not conf:
        print(problem)
        return 1
    try:
        reply = ailib.test_connection(conf)
    except ailib.AIError as e:
        print(f"ERROR: {e}")
        return 1
    print(f"✓ Conectado ({conf['provider']}, {conf['model']}). La IA respondió: {reply}")
    return 0


def cmd_suggestions(args) -> int:
    conn, _ = _open_db(args)
    rows = ailib.pending(conn)
    for r in rows:
        print(f"#{r['id']} ({(r['confidence'] or 0):.0%}) {r['src']}\n     -> {r['dst_dir']}  [{r['reason']}]")
    if not rows:
        print("No hay sugerencias pendientes.")
    return 0


def cmd_accept(args) -> int:
    conn, layout, inbox, protection = _setup(args)
    ids = args.ids or [r["id"] for r in ailib.pending(conn) if (r["confidence"] or 0) >= args.min]
    if not ids:
        print("Nada que aceptar (indica IDs; sin IDs se aceptan las de confianza >= --min).")
        return 1
    res = ailib.resolve(conn, ids, True, layout, protection, inbox)
    print(f"Movidos: {res.done + res.quarantined} · omitidos: {len(res.skipped)} · fallidos: {len(res.failed)}")
    return 0


def cmd_reject(args) -> int:
    conn, layout, inbox, protection = _setup(args)
    ailib.resolve(conn, args.ids, False, layout, protection, inbox)
    print("Rechazadas.")
    return 0


# ------------------------------------------------ proyectos y diagnóstico


def _project_roots(args) -> list[Path]:
    if args.root:
        return [Path(r) for r in args.root]
    if args.all_drives:
        return fixed_drives() or [Path.home()]
    return [Path.home()]


def _find_projects(args, conn, inbox):
    protection = Protection.from_system(conn, extra=[Path(p) for p in (args.protect or [])], inbox=inbox)

    def prog(dirs: int, found: int) -> None:
        if TTY:
            print(f"\r  revisadas {fmt_int(dirs)} carpetas · proyectos: {found}", end="", flush=True)

    roots = _project_roots(args)
    print("Buscando proyectos (solo lectura) en:", ", ".join(str(r) for r in roots))
    projs = discover_projects(roots, protection, progress=prog)
    _end_progress()
    return projs, protection


def cmd_projects(args) -> int:
    conn, layout, inbox, _ = _setup(args)
    projs, _ = _find_projects(args, conn, inbox)
    if args.json:
        import json as _json

        Path(args.json).write_text(
            _json.dumps([p.to_dict() for p in projs], indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"Lista guardada en {args.json}")
    for p in projs:
        extra = []
        if p.cryptic:
            extra.append(f'nombre confuso -> parece "{p.name_guess}"')
        if p.venvs:
            extra.append("tiene entorno virtual")
        print(
            f"\n  {p.path}\n    {', '.join(p.kinds)} · confianza {p.confidence} · {fmt_size(p.size)} · "
            f"{fmt_int(p.files)} archivos" + ("".join(" · " + e for e in extra))
        )
    print(f"\n{len(projs)} proyectos encontrados. Para reunirlos en {layout.projects}: gather (simula) / gather --yes")
    return 0


def cmd_gather(args) -> int:
    conn, layout, inbox, _ = _setup(args)
    projs, protection = _find_projects(args, conn, inbox)
    plan = plan_gather(
        projs,
        layout.projects,
        protection,
        rename=args.rename,
        allow_venv=args.allow_venv,
        min_confidence="media" if args.include_weak else "alta",
    )
    print(f"\nSe reunirían {len(plan.moves)} proyectos en {layout.projects}:")
    for m in plan.moves:
        print(f"  {m.src}\n    -> {m.dst}   ({fmt_size(m.size)}, {fmt_int(m.files)} archivos)")
    if plan.skipped:
        print(f"\nNo se tocan ({len(plan.skipped)}):")
        for s in plan.skipped[:25]:
            print(f"  {s['src']}: {s['reason']}")
    if not args.yes:
        print(
            "\nSIMULACIÓN: no se movió nada. Cómo lo haré: renombro cada carpeta entera en el mismo disco (sin copiar ni borrar),"
            "\nverifico que el contenido (y `git status`) sea idéntico y, si algo no coincide, lo devuelvo solo."
            "\nTodo queda en el historial y se deshace con undo. Para hacerlo: agrega --yes"
        )
        return 0
    print("\nMoviendo y verificando...")
    res = execute_gather(conn, plan)
    print(
        f"\nMovidos y verificados: {res.moved} · revertidos automáticamente: {len(res.reverted)} · fallidos: {len(res.failed)}"
    )
    for line in res.reverted + res.failed:
        print("  -", line)
    if res.batch_id:
        print(f"Para deshacer todo este lote: undo --batch {res.batch_id}")
    return 0 if not res.failed else 2


def cmd_doctor(args) -> int:
    conn, layout, inbox, protection = _setup(args)
    results = run_checks(conn, layout, inbox, protection)
    for level, name, msg in results:
        print(f"[{level:<5}] {name}: {msg}")
    return 1 if any(level == "ERROR" for level, _, _ in results) else 0


def cmd_theme(args) -> int:
    try:
        if args.reset or args.preset or args.accent or args.mode:
            accent = themelib.PRESETS[args.preset] if args.preset else args.accent
            cur = themelib.save(accent=accent, mode=args.mode, reset=args.reset)
            print(f"Guardado: color {cur['accent']} · modo {cur['mode']}. Reabre Nimbo para verlo.")
        else:
            cur = themelib.load()
            print(f"Color actual: {cur['accent']} · modo: {cur['mode']}")
            print("Presets:", ", ".join(f"{k} ({v})" for k, v in themelib.PRESETS.items()))
            print("Cambiar: theme --preset rose --mode dark   |   theme --accent #FF2D55   |   theme --reset")
    except ValueError as e:
        print(f"ERROR: {e}")
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="nimbo", description="Nimbo Fase 1: solo lectura.")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp, root=False):
        sp.add_argument("--db", help="ruta de la base de datos")
        if root:
            sp.add_argument("--root", action="append", help="carpeta a escanear (repetible)")
            sp.add_argument("--protect", action="append", help="carpeta extra intocable (repetible)")
            sp.add_argument("--no-measure", action="store_true", help="no medir carpetas protegidas")

    s = sub.add_parser("scan", help="escanear carpetas")
    common(s, True)
    s.set_defaults(fn=cmd_scan)
    d = sub.add_parser("dupes", help="buscar duplicados")
    common(d)
    d.add_argument("--min-size", default="1", help="tamaño mínimo, ej. 64KB")
    d.add_argument("--top", type=int, default=15)
    d.set_defaults(fn=cmd_dupes)
    g = sub.add_parser("programs", help="inventario de programas")
    common(g)
    g.add_argument("--out")
    g.add_argument("--no-winget", action="store_true")
    g.set_defaults(fn=cmd_programs)
    r = sub.add_parser("report", help="generar informe")
    common(r)
    r.add_argument("--out")
    r.add_argument("--min-size", default="1")
    r.set_defaults(fn=cmd_report)
    lb = sub.add_parser("lab", help="crear carpeta de pruebas falsa")
    lb.add_argument("path")
    lb.add_argument("--force", action="store_true")
    lb.set_defaults(fn=cmd_lab)
    a = sub.add_parser("all", help="scan + dupes + programs + report")
    common(a, True)
    a.add_argument("--min-size", default="1")
    a.add_argument("--top", type=int, default=10)
    a.add_argument("--out")
    a.add_argument("--no-winget", action="store_true")
    a.set_defaults(fn=cmd_all)

    def moving(sp):
        sp.add_argument("--db")
        sp.add_argument("--inbox", action="append", help="carpeta de entrada (repetible)")
        sp.add_argument("--protect", action="append")
        sp.add_argument("--layout-root", help="usar un laboratorio como raíz")
        sp.add_argument("--deep", action="store_true", help="incluir subcarpetas de las carpetas de entrada")
        sp.add_argument("--settle", type=float, default=60, help="segundos mínimos sin cambios (def. 60)")
        sp.add_argument("--top", type=int, default=15)

    pl = sub.add_parser("plan", help="proponer movimientos (simulación)")
    moving(pl)
    pl.add_argument("--out")
    pl.set_defaults(fn=cmd_plan)
    ap = sub.add_parser("apply", help="ejecutar el plan (con --yes)")
    moving(ap)
    ap.add_argument("--plan")
    ap.add_argument("--yes", action="store_true")
    ap.set_defaults(fn=cmd_apply)
    un = sub.add_parser("undo", help="deshacer movimientos")
    un.add_argument("--db")
    un.add_argument("--last", action="store_true")
    un.add_argument("--batch", type=int)
    un.add_argument("--all", dest="everything", action="store_true")
    un.set_defaults(fn=cmd_undo)
    hi = sub.add_parser("history", help="historial de movimientos")
    hi.add_argument("--db")
    hi.add_argument("--limit", type=int, default=30)
    hi.add_argument("--search")
    hi.set_defaults(fn=cmd_history)
    wa = sub.add_parser("watch", help="modo vigilante")
    moving(wa)
    wa.add_argument("--apply", action="store_true")
    wa.add_argument("--interval", type=float, default=30)
    wa.set_defaults(fn=cmd_watch)
    gm = sub.add_parser("games", help="juegos detectados y zonas protegidas")
    gm.set_defaults(fn=cmd_games)

    ui = sub.add_parser("ui", help="abrir la ventana (con ícono de bandeja)")
    ui.add_argument("--db")
    ui.add_argument("--tray", action="store_true", help="iniciar oculta en la bandeja")
    ui.add_argument("--layout-root")
    ui.set_defaults(fn=cmd_ui)
    au = sub.add_parser("autostart", help="iniciar con Windows")
    au.add_argument("mode", choices=["on", "off", "status"])
    au.set_defaults(fn=cmd_autostart)
    te = sub.add_parser("teach", help="crear una regla propia")
    te.add_argument("--db")
    te.add_argument("--ext", required=True)
    te.add_argument("--dest", required=True)
    te.add_argument("--hint")
    te.set_defaults(fn=cmd_teach)
    ru = sub.add_parser("rules", help="ver o borrar reglas")
    ru.add_argument("--db")
    ru.add_argument("--delete", type=int)
    ru.set_defaults(fn=cmd_rules)
    le = sub.add_parser("learn", help="aprender de tus correcciones")
    moving(le)
    le.set_defaults(fn=cmd_learn)
    ag = sub.add_parser("ai-suggest", help="pedir sugerencias a la IA local")
    moving(ag)
    ag.add_argument("--folder")
    ag.add_argument("--limit", type=int, default=20)
    ag.set_defaults(fn=cmd_ai_suggest)
    sg = sub.add_parser("suggestions", help="ver sugerencias pendientes")
    sg.add_argument("--db")
    sg.set_defaults(fn=cmd_suggestions)
    ac = sub.add_parser("accept", help="aceptar sugerencias (mueve con historial)")
    moving(ac)
    ac.add_argument("ids", nargs="*", type=int)
    ac.add_argument("--min", type=float, default=0.8)
    ac.set_defaults(fn=cmd_accept)
    rj = sub.add_parser("reject", help="rechazar sugerencias")
    moving(rj)
    rj.add_argument("ids", nargs="+", type=int)
    rj.set_defaults(fn=cmd_reject)

    def proj(sp):
        moving(sp)
        sp.add_argument("--root", action="append", help="carpeta donde buscar (def.: tu usuario)")
        sp.add_argument("--all-drives", action="store_true", help="buscar en todos los discos fijos")

    pj = sub.add_parser("projects", help="encontrar proyectos de código en el PC (solo lectura)")
    proj(pj)
    pj.add_argument("--json", help="guardar la lista en un archivo")
    pj.set_defaults(fn=cmd_projects)
    ga = sub.add_parser("gather", help="reunir proyectos en una carpeta (simula; con --yes mueve)")
    proj(ga)
    ga.add_argument("--yes", action="store_true")
    ga.add_argument(
        "--rename",
        action="store_true",
        help="nombrar la carpeta según el contenido (package.json, git...) en vez del nombre actual",
    )
    ga.add_argument("--allow-venv", action="store_true", help="mover también los que tienen entorno virtual")
    ga.add_argument("--include-weak", action="store_true", help="incluir los de confianza media")
    ga.set_defaults(fn=cmd_gather)
    dc = sub.add_parser("doctor", help="autodiagnóstico para auditoría")
    moving(dc)
    dc.set_defaults(fn=cmd_doctor)

    th = sub.add_parser("theme", help="cambiar colores y modo de la ventana")
    th.add_argument("--preset", choices=sorted(themelib.PRESETS))
    th.add_argument("--accent", help="color #RRGGBB")
    th.add_argument("--mode", choices=list(themelib.MODES))
    th.add_argument("--reset", action="store_true")
    th.set_defaults(fn=cmd_theme)

    ac2 = sub.add_parser("ai-config", help="ver o cambiar la IA (proveedor, modelo, qué se envía)")
    ac2.add_argument("--provider", choices=sorted(ailib.PROVIDERS))
    ac2.add_argument("--model")
    ac2.add_argument("--url")
    ac2.add_argument(
        "--mode", choices=list(ailib.MODES), help="names = solo nombres; content = nombres + inicio del contenido"
    )
    ac2.add_argument("--accept-remote", action="store_true", help="permitir enviar datos a un proveedor externo")
    ac2.add_argument("--revoke", action="store_true", help="retirar el permiso")
    ac2.set_defaults(fn=cmd_ai_config)
    acn = sub.add_parser("ai-connect", help="pegar la API key de Gemini: se valida y queda lista")
    acn.add_argument("--accept-remote", action="store_true", help="aceptar sin preguntar el envío a Google")
    acn.add_argument("--mode", choices=list(ailib.MODES))
    acn.set_defaults(fn=cmd_ai_connect)
    ak = sub.add_parser("ai-key", help="guardar la clave de API (cifrada)")
    ak.add_argument("--clear", action="store_true")
    ak.set_defaults(fn=cmd_ai_key)
    at = sub.add_parser("ai-test", help="probar la conexión con la IA")
    at.set_defaults(fn=cmd_ai_test)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        # Con la salida redirigida (archivo, tubería) Windows usa cp1252 y un «✓» haría fallar el comando.
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="replace") if not stream.isatty() else reconfigure(errors="replace")
    cfg.migrate_legacy_data()
    try:
        return args.fn(args)
    finally:
        # En Windows un archivo abierto no se puede borrar ni mover: se cierra toda conexión al terminar el comando.
        while _OPEN_CONNS:
            _OPEN_CONNS.pop().close()
