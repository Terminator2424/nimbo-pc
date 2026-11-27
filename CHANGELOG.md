# Changelog

## 0.6.1
- **Bandeja del sistema solo en Windows y con hilo daemon.** En otros sistemas el hilo de la bandeja mantenía vivo el proceso tras cerrar la ventana (el CI de Ubuntu quedó colgado 6 h). Una prueba nueva exige que no quede ningún hilo que impida terminar.
- **Consola:** un carácter que la codificación de la salida no soporta (por ejemplo «✓» en una tubería de Windows) ya no tumba el comando.
- Pruebas: la rueda del mouse funciona con CustomTkinter 5.2 y 6; la migración de datos se prueba también con las rutas de Windows (`%LOCALAPPDATA%`).
- CI: límites de tiempo en todos los trabajos; `apt` en modo no interactivo.

## 0.6.0
- **El proyecto pasa a llamarse Nimbo** (antes OrdenaPC): paquete `nimbo`, `Nimbo.exe` / `Nimbo-cli.exe`, carpeta de datos `%LOCALAPPDATA%\\Nimbo`, variables `NIMBO_HOME` y `NIMBO_API_KEY`.
- Migración automática: al abrir, los datos del nombre anterior (historial con «deshacer», reglas, configuración, clave cifrada) se mueven a la carpeta nueva y se corrigen las rutas de cuarentena. `INSTALAR.bat` quita la instalación anterior (accesos, inicio con Windows, PATH).
- Repositorio limpio: sin documentos del proceso de construcción ni datos personales.

## 0.5.3
- **Windows:** cada comando de la línea de comandos dejaba abierta su conexión SQLite; en Windows un archivo abierto no se puede borrar, lo que rompía las pruebas con carpetas temporales. Ahora `main()` cierra toda conexión al terminar, y las pruebas fallan si alguna queda abierta (detectable también en Linux).
- Las pruebas de la rueda del mouse usan el evento correcto en cada plataforma (`<MouseWheel>` en Windows).
- Usuario de GitHub y nombre en la licencia en lugar de marcadores; `docs/AUDIT.md` ya no trae `USUARIO/REPO`.

## 0.5.2
- **Python mínimo 3.11.** La versión corregida de Pillow (13) no existe para Python 3.10 y la última para 3.10 (12.3.0) tiene una vulnerabilidad conocida; además 3.10 llega a su fin de vida según el calendario de Python. El CI prueba en 3.11 y 3.12; el instalador busca 3.11+.

## 0.5.1
- **Corrección:** la rueda del mouse dejaba de funcionar en Ajustes (y en cualquier panel con scroll) después de pasar el puntero por una lista como Plan o Historial. Las listas ya no reemplazan el enlace global de la rueda; hay una prueba de regresión.

## 0.5.0
- **IA simplificada: pegas tu API key de Gemini y se valida sola** (lista los modelos de tu cuenta, prueba cuál responde y lo guarda), o usas Local. Se quitan Claude/OpenAI/«Otro».
- La clave de Gemini solo se envía a `generativelanguage.googleapis.com` (cualquier otro host se rechaza) y va en cabecera, nunca en la URL.
- `ai-connect` (un comando: pega la clave, valida, elige modelo y guarda cifrada); el modelo ya no está fijo (Google restringe modelos viejos a cuentas nuevas).
- Proyecto listo para auditoría: `scripts/audit.ps1|sh` (un comando), CodeQL, plantillas de issue/PR, SBOM en cada release, prueba anti-secretos.
- Dependencias: `pillow>=13` (pip-audit detectó una vulnerabilidad corregida en la 13.0.0; el rango anterior la permitía). 104 pruebas.

## 0.4.0
- **IA por API** (ya no depende de un servidor local): Claude (Anthropic), OpenAI, cualquier servicio compatible con OpenAI, o local (Ollama/LM Studio). Configurable en Ajustes → IA o con `ai-config`, `ai-key`, `ai-test`.
- Privacidad y seguridad de la IA remota: permiso explícito antes de enviar nada, solo https, modo «solo nombres» por defecto, archivos con nombres sensibles nunca se envían, el contenido se trata como datos (anti prompt-injection), clave de API cifrada con Windows (DPAPI) y nunca en texto plano ni en mensajes de error.
- Errores de la IA entendibles (clave inválida, sin permiso, modelo inexistente, límite de uso); un lote se detiene al primer error de clave en vez de insistir.
- Diálogos rediseñados estilo iOS (icono por tipo, botones grandes, Enter/Esc, fundido en Windows) y avisos con icono de estado.
- 93 pruebas (nuevas: formatos de Claude y OpenAI, consentimiento, https, archivos sensibles, almacenamiento de la clave, errores HTTP).

## 0.3.2
- **Corrección visual (cuadros negros, botones sin texto, piezas superpuestas):** las listas se dibujan ahora en un solo lienzo con solo las filas visibles (antes ~8 widgets por fila, miles en pantalla), por lo que Windows ya no pinta a medias mientras carga.
- **Esqueletos de carga** (Plan y Proyectos) en vez de piezas apareciendo; el plan se calcula en segundo plano y la ventana no se congela.
- Interruptores iOS propios (los de CustomTkinter se recortaban con ciertos escalados), navegación lateral alineada, pestañas apiladas (cambiar de pestaña ya no reconstruye), datos de Historial/Sugerencias se cargan al entrar, la ventana aparece cuando todo está armado.
- 76 pruebas (nuevas: lista virtual con 5000 filas, clics, esqueleto, interruptor).

## 0.3.1
- **Corrección:** los puntos de reanálisis de Windows que no son enlaces (OneDrive, deduplicación) ya no se tratan como enlaces ni se omiten en silencio; solo se omiten symlinks y junctions, y ahora con motivo visible.
- El vigilante resume una vez qué revisó y en qué modo está (ya no repite las mismas líneas cada 30 s); el estado dice «solo simula» cuando no mueve.
- Plan: botón «¿Por qué no mueve el resto?». Instalador: `Nimbo-cli.exe` con consola en el PATH. 72 pruebas.

## 0.3.0
- Interfaz rediseñada al estilo iOS: barra lateral, tarjetas, filas con iconos de color, insignias de confianza, interruptores, diálogos y avisos propios.
- Modo claro/oscuro, 6 colores de acento y comando `theme` para cambiarlos desde la terminal. Sistema de diseño separado en `theme.py` y `ui_widgets.py`.
- Registro del vigilante más corto y legible; 69 pruebas (cobertura 82 %).

## 0.2.0
- Descubrimiento de proyectos por contenido (`projects`) y reunión segura (`gather`) con verificación (manifiesto + `git status`) y reversión automática.
- `doctor` (autodiagnóstico), notificaciones de bandeja al mover, pestaña Proyectos.
- IA local restringida a `localhost` por defecto (`allow_remote` explícito).
- Instalador de doble clic (`INSTALAR.bat`), CI (Linux+Windows), lint (ruff), tipos (mypy), SAST (bandit), pip-audit, cobertura >= 80 %.

## 0.1.0
- Escáner de solo lectura, duplicados, inventario de programas y Steam, informes.
- Clasificador por reglas, plan, ejecución con diario y deshacer, vigilante, aprendizaje, sugerencias de IA, ventana y bandeja.
