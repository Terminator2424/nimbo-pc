#!/usr/bin/env bash
# Auditoría de un solo comando: estilo, tipos, seguridad, dependencias, pruebas y cobertura.
# Uso:  bash scripts/audit.sh        (deja el resultado en audit-report.txt)
set -u
cd "$(dirname "$0")/.."
OUT=audit-report.txt
fail=0
run() {
  local name="$1"; shift
  echo "=== $name" | tee -a "$OUT"
  if "$@" >>"$OUT" 2>&1; then echo "OK   $name" | tee -a "$OUT"; else echo "FALLA $name (ver $OUT)" | tee -a "$OUT"; fail=1; fi
}
: >"$OUT"
{ echo "Nimbo auditoría · $(date -u +%FT%TZ)"; python3 -m nimbo --version; python3 --version; git rev-parse --short HEAD 2>/dev/null; } | tee -a "$OUT"
run "ruff (errores y estilo)" python3 -m ruff check .
run "ruff format"             python3 -m ruff format --check .
run "mypy (tipos)"            python3 -m mypy nimbo
run "bandit (seguridad estática)" python3 -m bandit -q -r nimbo -c pyproject.toml
run "pip-audit (vulnerabilidades en dependencias)" python3 -m pip_audit -r requirements.txt
XV=""; if [ -z "${DISPLAY:-}" ] && command -v xvfb-run >/dev/null 2>&1; then XV="xvfb-run -a"; fi
run "pruebas + cobertura"     bash -c "$XV python3 -m coverage run -m unittest discover -s tests -t . && python3 -m coverage report"
echo "--- mapa de riesgo (revisar a mano)" | tee -a "$OUT"
{
  echo "[borrado/movimiento]"; grep -rnE "os\.(remove|unlink|rmdir)|shutil\.(rmtree|move|copy)|\.unlink\(|os\.replace|os\.rename" nimbo
  echo "[red]";                grep -rnE "urllib|socket|http\.client" nimbo
  echo "[procesos]";           grep -rn "subprocess" nimbo
} >>"$OUT"
[ "$fail" -eq 0 ] && echo "RESULTADO: todo en orden" | tee -a "$OUT" || echo "RESULTADO: hay fallas" | tee -a "$OUT"
exit "$fail"
