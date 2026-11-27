# Guía de auditoría

## Un solo comando
```powershell
powershell -ExecutionPolicy Bypass -File scripts\audit.ps1   # o: bash scripts/audit.sh
```
Deja el resultado en `audit-report.txt` (incluye el mapa de llamadas de borrado, red y procesos).

## Reproducir las comprobaciones (por separado)
```bash
pip install -r requirements.txt ruff mypy bandit coverage pip-audit
ruff check . && ruff format --check .          # estilo y errores
mypy nimbo                                  # tipos (plataforma win32)
bandit -q -r nimbo -c pyproject.toml        # análisis estático de seguridad
pip-audit -r requirements.txt                  # vulnerabilidades conocidas en dependencias
xvfb-run -a python -m coverage run -m unittest discover -s tests -t . && python -m coverage report   # >= 80 %
```
Estado al cortar v0.5.3 (medido en Linux): ruff, mypy y bandit sin hallazgos; 106 pruebas; cobertura 82 % (la ventana y el inicio automático
están excluidos del cálculo porque necesitan pantalla/Windows). Windows se verifica con la matriz de `ci.yml`.

## Mapa para revisar el código
```bash
# 1) ¿Qué puede borrar o mover?   (esperado: lab.py = datos falsos; programs.py = carpeta temporal propia; journal.py = shutil.move)
grep -rnE "os\.(remove|unlink|rmdir)|shutil\.(rmtree|move|copy)|\.unlink\(|os\.replace|os\.rename" nimbo
# 2) ¿Qué toca la red?            (esperado: solo ai.py -> urllib, solo si activas Gemini —con permiso, https y solo hacia Google— o un servidor local; ui.py usa un socket local solo como candado)
grep -rnE "urllib|socket|http\.client" nimbo
# 3) ¿Qué ejecuta procesos?       (esperado: programs.py winget/powershell, projmove.py git; todo con listas, sin shell)
grep -rn "subprocess" nimbo
```

## Lista de verificación manual
- [ ] Ningún borrado sobre rutas del usuario (comando 1). Los movimientos pasan solo por `journal.py` y `projmove.py`.
- [ ] `ai.ai_status` fija la clave de Gemini a `generativelanguage.googleapis.com`, exige permiso y https y rechaza otros esquemas; `keystore` no deja la clave en claro; la clave va en cabecera.
- [ ] `tests/test_no_secrets.py` pasa y GitHub *secret scanning* está activo.
- [ ] El release trae `SHA256SUMS.txt`, el SBOM `dist-sbom.cdx.json` y la atestación (`gh attestation verify Nimbo.exe -R TU_USUARIO/nimbo-pc`).
- [ ] `projmove.execute_gather`: renombrado atómico + manifiesto + `git status` + reversión.
- [ ] Cada `# nosec` / `# noqa` tiene justificación.
- [ ] Release: el `.sha256` coincide y la atestación verifica (`gh attestation verify Nimbo.exe -R <usuario>/<repo>`).
- [ ] `nimbo doctor` sin ERROR en una instalación limpia.

## Qué NO está cubierto (honesto)
Pruebas de integración reales en Windows (OneDrive solo-nube, rutas largas, archivos bloqueados), pruebas de la bandeja y del inicio automático,
fuzzing de nombres de archivo, revisión externa independiente.
