# Autenticación (Google Apps Script) — reglas v8

## Despliegue actual

| Campo | Valor |
|--------|--------|
| **URL** | `https://script.google.com/macros/s/AKfycbyBi2CziLFT1-vUrRoabK4Iy3HAl-BpBDOHY41gZgXK4-xxkMuKpAuUnWmyK2KVAOg/exec` |
| **Deployment ID** | `AKfycbyBi2CziLFT1-vUrRoabK4Iy3HAl-BpBDOHY41gZgXK4-xxkMuKpAuUnWmyK2KVAOg` |

Comprobación GET: debe responder `{"status":"ok","service":"bridge-auth-v8"}` (ver [endpoint](https://script.google.com/macros/s/AKfycbyBi2CziLFT1-vUrRoabK4Iy3HAl-BpBDOHY41gZgXK4-xxkMuKpAuUnWmyK2KVAOg/exec)).

El cliente Python usa esta URL por defecto en `_AUTH_URL` (`netsphere bridge.py`). Si en configuración oculta guardas otra `auth_url`, tiene prioridad.

## Archivo

Pega el contenido de `Código.gs` en el editor del proyecto Apps Script vinculado a tu hoja.

**Importante:** en la hoja de cálculo ejecuta una vez **`resetearHojas()`** para añadir las columnas `SESSION_STARTED` y `LAST_HEARTBEAT` en `usuarios` y crear la hoja **`bridge_semillas`** (si no existe).

## Hoja `bridge_semillas` (semilla por operador)

Hoja aparte para no tocar `usuarios` ni `configs_usuarios`. Tras `resetearHojas()` tendrá cabeceras:

| USUARIO | SEMILLA_BRIDGE |
|---------|----------------|

- Una fila por operador; **`USUARIO`** debe coincidir (sin distinguir mayúsculas) con el login.
- **`SEMILLA_BRIDGE`**: texto libre (recomendado: cadena larga y única por operador). Si está vacío o no hay fila para ese usuario, el servidor envía `bridge_semilla` vacío en el JSON de login.
- El cliente Python combina esa semilla con `bridge.key` (**NSC2**, PBKDF2) para cifrar la contraseña guardada en preferencias. Sin semilla sigue **NSC1** (solo `bridge.key`).
- Tras cerrar sesión o expulsión por heartbeat, la semilla se borra de memoria; con blob NSC2 hace falta un login que devuelva de nuevo la semilla para rellenar el campo de clave desde prefs.

## Comportamiento

| Situación | Qué hace el servidor |
|-----------|----------------------|
| Cerrar la app (X) | El cliente llama `logout` → se borra token, IP de sesión y marcas de sesión. |
| Cerrar sesión en la app | Igual: `logout`. |
| Heartbeat cada ~30 s | Renueva `LAST_HEARTBEAT` y actualiza IP si cambió la WAN (sin expulsar). No hay caducidad por “silencio” en v8. |
| Contraseña incorrecta | Suma intentos; a partir de **5** fallos → `BLOCKED_UNTIL` 24 h **solo para ese usuario**. |
| Misma cuenta, sesión activa en otra IP | Respuesta `session_active_other_network` **sin** bloqueo 24 h. El cliente ofrece **Tomar sesión aquí** (`force_new_session`). |
| Tomar sesión | Con la misma clave y `force_new_session: true` se invalida la sesión anterior y se emite token nuevo. |

## Acciones JSON

- `login` — campos habituales + opcional `force_new_session: true`. Respuesta OK incluye **`bridge_semilla`** (`""` si no hay fila o semilla en `bridge_semillas`).
- `logout` — `usuario`, `session_token`
- `heartbeat` — `usuario`, `session_token`, `ip_publica`

## Cliente Python

- `api_logout_best_effort()` al cerrar ventana o al salir con la app principal.
- `_iniciar_heartbeat()` al entrar a la pantalla principal.
- Diálogo si el servidor devuelve `code: session_active_other_network`.
