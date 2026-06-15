# Quality Gates

Definicion de criterios de calidad para aceptar cambios.

## Gate 1 - Correctitud funcional

Debe pasar:

- login y carga de configuracion
- conexion SSH y tunel SOCKS
- acceso a IP interna de LAN remota
- gestion de sesiones abiertas

## Gate 2 - Estabilidad

- Sin excepciones no controladas en flujo principal.
- No degradar tasa de conexion exitosa.
- No aumentar cierres inesperados de sesion.

## Gate 3 - Compatibilidad

- Evitar dependencias hardcoded de un solo SO.
- Si se toca proxy/hosts/browser: validar en Windows y al menos un Unix-like.

## Gate 4 - Seguridad

- No exponer secretos en logs.
- No guardar credenciales en texto plano nuevo.
- Timeouts y manejo de errores de red definidos.

## Gate 5 - Mantenibilidad

- Cambios documentados.
- Nombres claros y responsabilidades separadas.
- Sin aumento innecesario de deuda tecnica.

## Evidencia minima por release

- Checklist manual completado.
- Notas de cambios.
- Riesgos conocidos y mitigacion.
