# Modelo de seguridad

## Activos
Archivos del usuario (integridad y disponibilidad) · privacidad del contenido (con IA remota activada, nombres y a veces el inicio de algunos archivos salen del PC) · clave de API · historial (`moves`).

## Invariantes
| # | Invariante | Dónde se impone | Prueba |
|---|---|---|---|
| I1 | No se borran datos del usuario | no existen `remove/unlink/rmtree` sobre rutas del usuario (ver `docs/AUDIT.md`) | `test_scan_never_modifies_files`, `test_identical_copy_goes_to_quarantine_not_deleted` |
| I2 | No se sobrescribe | `journal.unique_path`, `_move_file`, `projmove` (falla si el destino existe) | `test_never_overwrites_different_file`, `test_undo_does_not_overwrite_occupied_origin` |
| I3 | Todo movimiento se registra y es reversible | `journal._record`, `undo` | `test_apply_then_undo_restores_everything`, `test_gather_moves_verifies_and_undo_restores` |
| I4 | Zonas protegidas intactas | `protect.Protection`, `scanner`, `projects` | `test_protected_prefix`, `test_does_not_enter_projects_and_skips_protected` |
| I5 | La IA solo sugiere; con Gemini nada sale del PC sin permiso explícito, solo por https y solo hacia Google; sin archivos sensibles; clave cifrada | `ai.ai_status`, `ai.make_suggestions`, `keystore`, `ai.resolve` | `test_gemini_needs_consent_key_and_model`, `test_key_is_pinned_to_google`, `test_sensitive_names_are_never_sent_to_remote_but_are_local`, `test_names_mode_never_sends_file_content`, `test_key_is_stored_encrypted_not_plain`, `test_accept_moves_with_history_and_reject_does_not` |
| I6 | Mover un proyecto es verificable y revierte solo | `projmove.execute_gather` | `test_auto_revert_when_verification_fails`, `test_failed_rename_changes_nothing` |
| I7 | Las fases de inventario son de solo lectura | `scanner`, `duplicates`, `projects` | `test_scan_never_modifies_files` |

## Amenazas y mitigaciones
| Amenaza | Mitigación | Riesgo residual |
|---|---|---|
| Nombre de carpeta sugerido por la IA con `..` o `/` (path traversal) | `ai._safe_name` + solo se aceptan carpetas existentes o `NUEVA:` saneada | bajo |
| Enlaces simbólicos / junctions que redirijan a zonas del sistema | se omiten (`_is_link`), no se sigue ningún enlace | bajo |
| Carrera (TOCTOU) entre comprobar y mover | revalidación justo antes de mover; en Windows `rename` no sobrescribe; en Linux hay una ventana mínima | bajo (documentado) |
| Exfiltración: Gemini recibe datos de archivos | consentimiento explícito antes del primer envío; solo https; modo «solo nombres» por defecto; nombres sensibles (contraseñas, claves, identidad, bancos) jamás se envían; máx. 1200 caracteres de contenido; permiso revocable (`ai-config --revoke`) | medio: Google ve lo que se envíe; la detección de nombres sensibles es heurística |
| Robo o filtración de la clave de API | cifrada con DPAPI (solo tu usuario de Windows en este PC la descifra); nunca en `config.json` en claro, ni en registros, ni en mensajes de error; viaja en la cabecera `x-goog-api-key` (no en la URL, que quedaría en registros); alternativa: variable de entorno | bajo: malware con tu sesión podría pedirle a Windows que la descifre |
| Prompt injection: un archivo con texto que da órdenes a la IA | el contenido se declara como datos en el prompt; la respuesta se valida (solo carpetas existentes o `NUEVA:` saneada, sin `/`); la IA no ejecuta nada y tú apruebas cada movimiento | bajo |
| Clave enviada a un servidor falso (config manipulada) | la clave de Gemini solo se envía a `generativelanguage.googleapis.com` (o localhost); cualquier otro host se rechaza, incluso `...googleapis.com.evil.com` | bajo |
| Secretos subidos al repositorio | `tests/test_no_secrets.py` falla si aparece una clave en archivos versionados; CodeQL y secret scanning de GitHub | bajo |
| Gasto inesperado en la API | máximo 20 consultas por lote y se detiene al primer error de clave/límite | bajo: el costo depende de tu proveedor |
| Cadena de suministro | núcleo sin dependencias; UI con rangos acotados; `pip-audit` y Dependabot en CI | medio: falta *lockfile* con hashes (ROADMAP) |
| Ejecutable sin firmar / sustitución | build en CI con atestación de procedencia y `.sha256`; build local por `INSTALAR.bat` | medio: sin firma de código (ROADMAP) |
| Inyección de comandos | `subprocess` solo con listas fijas (`winget`, `powershell`, `git`), sin `shell=True` | bajo |
| Inyección SQL | consultas parametrizadas; única interpolación = nombre de tabla de una tupla fija | bajo |
| Manipulación del historial | no está firmado | medio: cadena de hashes en ROADMAP |
| Mover un proyecto lo rompe (rutas absolutas, venv) | por defecto se omiten los que tienen venv; verificación + reversión; deshacer | bajo |

## Supuestos
El atacante no controla ya la cuenta de Windows del usuario (si puede editar `config.json` o la base, ya puede tocar los archivos directamente).
