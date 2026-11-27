# Nimbo
<img width="800" height="537" alt="nimbo_demo" src="https://github.com/user-attachments/assets/2ea5dcc7-f3f0-4621-9ac6-b818ca0a5029" />

*Interfaz estilo iOS: modo claro/oscuro, color de acento a elección (`python -m nimbo theme --preset rose`).*

Organizador autónomo de archivos para Windows. **Seguro por diseño**: nunca borra, nunca sobrescribe,
protege tus juegos y proyectos, y deja un historial de *de dónde a dónde* se movió cada archivo con botón de deshacer.

> Estado: v0.5.3. Probado en Linux y con CI en Windows (ver `.github/workflows`). El `.exe`, la bandeja y el inicio
> automático dependen de Windows: si algo falla en tu PC, abre un *issue* con `instalacion.log` y la salida de `nimbo doctor`.

## Qué hace

| Función | Detalle |
|---|---|
| Vigilante | Mira Descargas y Escritorio y ordena lo nuevo (capturas, PDFs, instaladores, WhatsApp...). Arranca en **simulación**. |
| Plan | Muestra *antes → después* con el motivo y la confianza de cada movimiento. Nada se mueve sin tu permiso. |
| Historial y deshacer | Cada movimiento se guarda (SQLite). Se deshace un lote o todo. Nunca pisa lo que haya en el origen. |
| Proyectos | Encuentra proyectos por su **contenido** (aunque se llamen `1234567`), sugiere un nombre y los reúne en `C:\Users\TU\Proyectos`, verificando y revirtiendo solo si algo falla. |
| Aprendizaje | Si recolocas algo que movió, aprende la regla. También hay reglas manuales (`teach`). |
| IA (opcional) | **Pegas tu API key de Gemini y se valida sola** (elige el modelo disponible para tu cuenta), o usas un servidor **Local** (Ollama, LM Studio). Solo sugiere para lo ambiguo y tú apruebas. Con Gemini envía únicamente lo que permitas (por defecto, solo nombres) y nunca archivos sensibles. |
| Inventarios | Duplicados (tamaño → hash parcial → SHA-256), programas instalados, juegos de Steam, informes MD/JSON/CSV. |
| Diagnóstico | `nimbo doctor`: integridad de la base, historial vs. disco, configuración. |

## Instalar (Windows)

1. Extrae el zip en una carpeta corta (`C:\Nimbo`).
2. Doble clic en **`INSTALAR.bat`**. Compila el `.exe` en tu PC, lo instala en `%LOCALAPPDATA%\Programs\Nimbo`,
   crea accesos directos y activa el inicio con Windows. Para quitarlo: `DESINSTALAR.bat`.
3. Alternativa: descarga `Nimbo.exe` y su `.sha256` de *Releases* (compilado por CI con atestación de procedencia).

## Línea de comandos

El instalador crea `Nimbo-cli.exe` (con consola) y lo agrega al PATH: en una terminal **nueva** escribe `Nimbo-cli plan`, `Nimbo-cli doctor`, etc.
(`Nimbo.exe` es la ventana y no imprime nada en la terminal.) Desde el código: `python -m nimbo <comando>`.

```text
python -m nimbo ui                      ventana + bandeja
python -m nimbo plan | apply --yes      proponer / ejecutar movimientos (apply sin --yes solo simula)
python -m nimbo undo --last|--batch N|--all
python -m nimbo history --search texto
python -m nimbo projects [--all-drives] [--json lista.json]
python -m nimbo gather [--rename] [--allow-venv] [--yes]
python -m nimbo watch [--apply]
python -m nimbo teach|rules|learn       reglas propias y aprendizaje
python -m nimbo ai-connect                        pegar la API key de Gemini: se valida y queda lista
python -m nimbo ai-config [--provider gemini|local] [--revoke]   ver o cambiar la IA
python -m nimbo ai-key | ai-test                 cambiar la clave (cifrada) / probar la conexión
python -m nimbo ai-suggest | suggestions | accept | reject
python -m nimbo scan | dupes | programs | report | all   inventario de solo lectura
python -m nimbo theme [--preset rose] [--mode dark]   cambia colores de la ventana
python -m nimbo doctor | games | autostart on|off|status | lab RUTA
```

## ¿Por qué no mueve algo?

1. Pestaña **Vigilante**: el estado debe decir *Vigilando · moviendo*. Si dice *solo simula*, enciende **Mover de verdad**.
2. Pestaña **Plan** → **¿Por qué no mueve el resto?** explica cada caso (muy reciente, sin regla, protegido, carpeta...).
3. Por diseño **no mueve**: carpetas (salvo proyectos desde la pestaña Proyectos), `.html`/código/atajos/temporales, archivos modificados hace menos de 60 s y archivos solo en la nube.
4. `Nimbo-cli doctor` y `Nimbo-cli plan` muestran lo mismo en la terminal.

## Garantías (invariantes que las pruebas verifican)

1. **No borra datos del usuario.** Las únicas llamadas de borrado del código son sobre el laboratorio falso y una carpeta temporal propia.
2. **No sobrescribe.** Si el destino existe: copia idéntica → cuarentena; distinta → `nombre (2)`.
3. **Todo es reversible** y queda registrado con origen, destino, motivo y confianza.
4. **Zonas protegidas** (Windows, Program Files, AppData, bibliotecas de Steam, repos/proyectos, `node_modules`, entornos virtuales).
5. **Proyectos:** renombrado atómico en el mismo disco + verificación de manifiesto y `git status`; reversión automática.
6. **Sin red salvo la IA que tú actives**: con permiso explícito, solo https y solo hacia Google, clave cifrada y sin archivos sensibles (ver `docs/SECURITY_MODEL.md`).

## Auditar el proyecto (un solo comando)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\audit.ps1     # Windows
bash scripts/audit.sh                                           # Linux/macOS
```
Corre estilo, tipos, seguridad estática (bandit), vulnerabilidades en dependencias (pip-audit), 106 pruebas con cobertura y un mapa de
llamadas de borrado/red/procesos; deja todo en `audit-report.txt`. Guía completa: [`docs/AUDIT.md`](docs/AUDIT.md).

## Desarrollo

```bash
pip install -r requirements.txt ruff mypy bandit coverage pip-audit
python -m unittest discover -s tests -t .      # 106 pruebas (la de ventana requiere pantalla/xvfb)
ruff check . && ruff format --check . && mypy nimbo && bandit -q -r nimbo -c pyproject.toml
```

Documentación: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) · [`docs/SECURITY_MODEL.md`](docs/SECURITY_MODEL.md) ·
[`docs/AUDIT.md`](docs/AUDIT.md) · [`docs/DESIGN.md`](docs/DESIGN.md) · [`docs/ROADMAP.md`](docs/ROADMAP.md) · [`CONTRIBUTING.md`](CONTRIBUTING.md) · [`SECURITY.md`](SECURITY.md)

Licencia: MIT.
