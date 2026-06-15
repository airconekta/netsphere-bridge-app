# Plan de Refactor por Fases (sin romper produccion)

Objetivo: evolucionar `netsphere bridge.py` sin perder estabilidad funcional.

Principio rector: **mantener compatibilidad total en cada fase**.  
Si una fase no pasa validacion manual, no avanzar a la siguiente.

---

## Fase 0 - Baseline y seguridad de cambios (1-2 dias)

Meta:

- Congelar comportamiento actual y crear una linea base reproducible.

Acciones:

- Definir checklist de pruebas manuales obligatorias:
  - login exitoso/fallido
  - registro de usuario
  - carga de clientes
  - conexion manual SSH
  - flujo de escaneo
  - apertura de navegador
  - cierre de sesiones y logout
- Agregar `CHANGELOG.md` para trazabilidad por version.
- Crear `KNOWN_ISSUES.md` para fallas actuales conocidas.

Criterio de salida:

- Todas las pruebas basicas pasan en 2 corridas consecutivas.

---

## Fase 1 - Ordenar configuracion y constantes (2-3 dias)

Meta:

- Reducir acoplamiento y centralizar estado/configuracion.

Acciones:

- Extraer a `config_core.py`:
  - constantes (`_VER`, listas de columnas, navegadores, defaults)
  - paletas y helpers de tema
- Encapsular `CFG` y estado global en una estructura unica (`AppState`).
- Eliminar duplicidad de funciones (ej. `_set_window_icon` repetida).

Riesgo:

- Bajo (si solo se mueve codigo sin cambiar logica).

---

## Fase 2 - Separar servicios de red (4-6 dias)

Meta:

- Aislar logica de red para facilitar mantenimiento y pruebas.

Acciones:

- Crear `services/auth_service.py`:
  - login, registro, heartbeat, config online
- Crear `services/ssh_service.py`:
  - conectar/desconectar, server SOCKS, relay, lifecycle de tuneles
- Crear `services/scan_service.py`:
  - deteccion de redes, ping, HTTP detect, escaneo por rangos
- Mantener interfaz adaptadora desde UI para no romper llamadas.

Riesgo:

- Medio (hilos y sockets).

Mitigacion:

- Migracion incremental por bloques + pruebas de regresion por bloque.

---

## Fase 3 - Separar capa UI (4-7 dias)

Meta:

- Limpiar responsabilidades de interfaz y facilitar iteraciones visuales.

Acciones:

- `ui/root_app.py` para login/registro/primer uso.
- `ui/main_app.py` para tabs autenticadas.
- `ui/widgets/table.py` para `CtkTable`.
- `ui/dialogs/*.py` para dialogos (config oculta, whoami, acceso, cache).

Riesgo:

- Medio (eventos/estado en callbacks).

---

## Fase 4 - Observabilidad y manejo de errores (2-3 dias)

Meta:

- Dejar de ocultar errores y mejorar soporte en campo.

Acciones:

- Reemplazar `except:` genericos por excepciones concretas.
- Estandarizar logs estructurados por contexto:
  - auth
  - ssh
  - scan
  - browser
- Agregar modo debug activable por flag.

Riesgo:

- Bajo.

---

## Fase 5 - Pruebas automatizadas minimas (3-5 dias)

Meta:

- Proteger funciones criticas con tests de unidad.

Cobertura inicial:

- normalizacion de URL Sheets
- busqueda de clientes
- parseo de respuestas auth
- utilidades de escaneo sin red real (mocks)

Stack sugerido:

- `pytest`
- `pytest-mock`

Riesgo:

- Bajo, alto retorno.

---

## Fase 6 - Mejoras de producto (continuo)

Meta:

- Añadir capacidades "superiores" sin reescribir todo.

Prioridad sugerida:

1. Inventario tecnico de equipos + etiquetas
2. Historial por cliente de conexiones y acciones
3. Alertas basicas de disponibilidad
4. Integracion API con OSS/BSS externo (si aplica)
5. Provisionamiento CPE (TR-069) en etapa avanzada

---

## Estrategia de despliegue

- Rama por fase.
- Versionado semantico interno (ej. `14.1`, `14.2`).
- Release notes obligatorias por fase.
- Regla: no mezclar refactor y nuevas features en el mismo lote.

---

## Definicion de exito

- Misma funcionalidad actual, menor complejidad.
- Menos tiempo para ubicar y cambiar codigo.
- Menor riesgo de regresiones.
- Base lista para escalar con nuevas capacidades.
