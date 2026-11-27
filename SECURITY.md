# Política de seguridad

## Reportar una vulnerabilidad
No abras un *issue* público. Usa **GitHub → Security → Report a vulnerability** (reporte privado) en este repositorio.
Incluye versión (`nimbo --version`), salida de `nimbo doctor` y pasos para reproducir. Respuesta objetivo: 7 días (best effort).

## Alcance
Dentro: pérdida o corrupción de archivos, sobrescritura, escapes de zonas protegidas, traversal de rutas, fuga de datos
hacia la red, ejecución de comandos, integridad del historial. Fuera: ataques que ya requieren control de tu usuario de Windows
(pueden editar `config.json` o la base de datos directamente; ver supuestos en `docs/SECURITY_MODEL.md`).

## Versiones soportadas
Solo la última versión publicada.
