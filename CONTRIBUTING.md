# Contribuir

1. Crea una rama; cambios pequeños y con pruebas.
2. Antes de abrir el PR deben pasar (CI lo repite en Linux y Windows):
   `ruff check . && ruff format --check . && mypy nimbo && bandit -q -r nimbo -c pyproject.toml && python -m unittest discover -s tests -t .`
3. **Reglas innegociables** (un PR que las rompa se rechaza): nada que borre datos del usuario; nada que sobrescriba; todo movimiento
   pasa por `journal`/`projmove` y se registra; nada de red salvo `ai.py` y solo localhost; el núcleo sin dependencias externas.
4. Cualquier `# nosec` o `# noqa` necesita una frase de justificación.
5. Cambios en esquema SQLite: ver `docs/ROADMAP.md` (migraciones versionadas pendientes).
