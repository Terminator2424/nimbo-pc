"""Modo vigilante: cada cierto tiempo revisa Descargas/Escritorio y ordena lo nuevo.

Sin dependencias externas (sondeo por tiempo). Aprende de tus correcciones cada ~10 ciclos.
"""

from __future__ import annotations

import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from collections.abc import Callable

from .classifier import Layout, build_plan
from .journal import apply_plan
from .learning import detect_corrections, load_rules
from .protect import Protection


def _tail(path: str) -> str:
    parts = Path(path).parent.parts
    return "/".join(parts[-2:])


def watch(
    conn: sqlite3.Connection,
    inbox: list[Path],
    layout: Layout,
    protection: Protection,
    *,
    apply: bool | Callable[[], bool],
    interval: float = 30,
    settle: float = 60,
    deep: bool = False,
    max_cycles: int | None = None,
    log: Callable[[str], None] = print,
    sleep: Callable[[float], None] = time.sleep,
    should_stop: Callable[[], bool] = lambda: False,
    learn_every: int = 10,
    notify: Callable[[str], None] | None = None,
) -> int:
    cycles = 0
    last_state: tuple | None = None
    try:
        while (max_cycles is None or cycles < max_cycles) and not should_stop():
            cycles += 1
            stamp = datetime.now().strftime("%H:%M:%S")
            try:
                if cycles % learn_every == 0:
                    roots = [layout.pictures, layout.videos, layout.music, layout.documents, layout.downloads]
                    for msg in detect_corrections(conn, [r for r in roots if r.is_dir()], inbox):
                        log(f"[{stamp}] {msg}")
                plan = build_plan(inbox, layout, protection, deep=deep, settle_seconds=settle, rules=load_rules(conn))
                do_apply = apply() if callable(apply) else apply
                state = (len(plan.moves), len(plan.skipped), do_apply)
                if state != last_state:  # solo avisa cuando algo cambia (no cada 30 s)
                    last_state = state
                    modo = "moviendo de verdad" if do_apply else "SOLO SIMULACIÓN (nada se mueve)"
                    log(
                        f"[{stamp}] Revisé las carpetas: {len(plan.moves)} por mover, "
                        f"{len(plan.skipped)} se quedan quietos · {modo}"
                    )
                    if not do_apply:
                        for m in plan.moves:
                            log(f"[{stamp}]   (simulación) {os.path.basename(m.src)} → {_tail(m.dst)}  [{m.reason}]")
                if plan.moves and do_apply:
                    r = apply_plan(conn, plan, layout, protection, inbox, kind="watch")
                    last_state = None  # tras mover, vuelve a resumir
                    log(
                        f"[{stamp}] movidos {r.done}, a cuarentena {r.quarantined}, "
                        f"omitidos {len(r.skipped)}, fallidos {len(r.failed)} (lote {r.batch_id})"
                    )
                    for f in r.failed:
                        log(f"[{stamp}]   fallo: {f}")
                    if notify and (r.done or r.quarantined):
                        notify(f"Moví {r.done + r.quarantined} archivo(s). Puedes deshacerlo en Historial.")
            except Exception as e:  # el vigilante nunca debe morirse por un error puntual
                log(f"[{stamp}] error en este ciclo (sigo vigilando): {e}")
            if (max_cycles is None or cycles < max_cycles) and not should_stop():
                sleep(interval)
    except KeyboardInterrupt:
        log("Vigilante detenido.")
    return cycles
