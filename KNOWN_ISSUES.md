# Known Issues

Lista inicial de riesgos/limitaciones tecnicas observadas.

## Arquitectura

- El core funcional vive en un archivo monolitico (`netsphere bridge.py`).
- Estado global compartido en varias capas.

## Portabilidad

- Existen partes acopladas a Windows (proxy por `winreg`, rutas de navegador, hosts path).
- Se requiere adapter por SO para soporte pleno Linux/macOS.

## Calidad de codigo

- Hay `except:` genericos que ocultan errores reales.
- No existe suite de pruebas automatizadas consolidada.

## Operacion

- Configuracion local persistente actualmente limitada (enfoque memoria + backend).
- Dependencia de servicios remotos para flujo completo de auth/config.
