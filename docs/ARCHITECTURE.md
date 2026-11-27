# Arquitectura

```
nimbo/
  cli.py        punto de entrada de línea de comandos (argparse)
  ui.py         ventana CustomTkinter + bandeja (pystray); hilos con conexión SQLite propia; cola de mensajes
  context.py    arma Layout + carpetas de entrada + Protection (compartido por CLI y UI)
  config.py     rutas de datos, categorías por extensión, nombres protegidos, config.json
  db.py         esquema SQLite
  scanner.py    inventario de solo lectura (Fase 1)
  duplicates.py tamaño -> hash 64 KB -> SHA-256, con caché
  programs.py   registro de Windows, winget, Microsoft Store, Steam
  report.py     informes MD/JSON/CSV
  protect.py    Protection: qué NO se puede mover
  classifier.py reglas -> Plan(moves, skipped)        (no mueve nada)
  journal.py    apply_plan / undo / history           (ÚNICO sitio que mueve archivos sueltos)
  projects.py   descubre proyectos por contenido      (solo lectura)
  projmove.py   reúne proyectos con verificación y reversión (ÚNICO sitio que mueve carpetas)
  learning.py   reglas propias y aprendizaje de correcciones
  ai.py         cliente OpenAI-compatible, solo localhost; sugerencias que requieren aprobación
  watcher.py    bucle de vigilancia por sondeo
  autostart.py  clave Run de Windows
  doctor.py     autodiagnóstico
```

## Flujo
`classifier.build_plan` (lee) → `Plan` (JSON) → `journal.apply_plan` (revalida, mueve, registra) → `moves` en SQLite → `journal.undo`.
La ventana y el vigilante usan exactamente las mismas funciones que la línea de comandos.

## Tablas
`files`, `dirs`, `scans`, `scan_errors` (inventario) · `programs`, `steam_games` · `batches`, `moves` (diario) · `rules` · `suggestions` · `meta`.
`moves.action`: `move | quarantine | undo | move_dir`; `moves.status`: `done | undone | missing | corrected`.

## Decisiones
- Solo biblioteca estándar en el núcleo: menos superficie de ataque y fácil de auditar.
- Sondeo en vez de eventos del sistema de archivos: sin dependencias y más predecible; se paga con latencia (30 s por defecto).
- Proyectos fuera de `Documentos`: OneDrive los sincronizaría (miles de archivos de `node_modules`/`.git`).
