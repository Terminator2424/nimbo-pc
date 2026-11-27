# Hoja de ruta (prioridad de arriba hacia abajo; las estimaciones son cálculos, no mediciones)

## Seguridad y confianza
1. **Firma de código** del `.exe` (certificado o Azure Trusted Signing) para quitar el aviso de SmartScreen.
2. **Lockfile con hashes** (`pip-compile --generate-hashes`) e instalación con `--require-hashes`.
3. **Diario con cadena de hashes** (cada fila incluye el hash de la anterior) para detectar manipulación; `doctor` lo verifica.
4. **SBOM** (CycloneDX) en cada release y *pin* de las GitHub Actions por SHA.
5. Movimiento sin ventana TOCTOU en Linux/macOS (`link` + `unlink` o `renameat2(RENAME_NOREPLACE)`).

## IA
- Presupuesto mensual configurable y contador de consultas; más proveedores con presets; modo «sin contenido» también para PDF con OCR local; detección de datos personales por contenido (no solo por nombre).

## Calidad
6. **Migraciones de esquema versionadas** (hoy `CREATE IF NOT EXISTS`): imprescindible antes de cambiar columnas.
7. Pruebas de integración en Windows (OneDrive solo-nube, rutas > 260, archivos bloqueados, junctions) en la matriz de CI.
8. Pruebas de propiedades (Hypothesis): `apply` + `undo` = identidad sobre árboles aleatorios; nombres hostiles (reservados de Windows, Unicode, puntos finales).
9. Registro estructurado con rotación (`logging`) y exportación del historial a CSV.
10. Pasar los parámetros posicionales de API interna a objetos de configuración (hoy `PLR0917` está desactivado).

## Producto
11. Música por artista/álbum (etiquetas ID3) y fotos por EXIF.
12. Más lugares: Documentos, otros discos y OneDrive (con vista previa y cuarentena), no solo Descargas/Escritorio.
13. Proyectos: mover también los que tienen entorno virtual recreándolo; reescribir rutas absolutas conocidas (`.vscode`, `.idea`).
14. Detección por eventos del sistema (ReadDirectoryChangesW) para reaccionar al instante.
15. Reglas compartibles (paquetes de reglas en JSON) e internacionalización.
16. Instalador MSI/Inno Setup sin necesidad de Python en el PC (usando el `.exe` de Releases).
