## Qué cambia

## Lista de verificación
- [ ] `bash scripts/audit.sh` (o `scripts\audit.ps1`) sin fallas
- [ ] Prueba nueva o actualizada para el cambio
- [ ] No borra ni sobrescribe datos del usuario; todo movimiento pasa por `journal`/`projmove`
- [ ] No agrega red nueva ni dependencias (si lo hace: explicado en `docs/SECURITY_MODEL.md`)
- [ ] Cada `# nosec` / `# noqa` nuevo tiene justificación
