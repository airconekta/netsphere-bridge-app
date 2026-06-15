# Security Notes

## Modelo de riesgo relevante

NetSphere Bridge opera con:

- credenciales de acceso (usuario/clave)
- conexiones SSH a infraestructura de clientes
- navegacion hacia interfaces internas

## Reglas basicas

- No commitear secretos reales.
- No imprimir claves en logs.
- Reducir superficie de datos sensibles en memoria cuando sea posible.
- Usar canales cifrados y timeouts de red razonables.

## Recomendaciones inmediatas

1. Migrar logs a niveles (`info/warn/error/debug`) con masking de campos sensibles.
2. Reemplazar `except:` genericos por manejo explicito.
3. Añadir validaciones de certificados/host keys segun modo operativo.
4. Definir politica de rotacion de credenciales operativas.

## Reporte responsable

Si detectas una vulnerabilidad:

1. No publiques exploit en canales abiertos.
2. Documenta impacto, escenario y pasos de reproduccion.
3. Prioriza parche y comunicacion interna antes de release.
