# Changelog

## 0.14.2 - Auth / sesión / Apps Script v8

- `Código.gs` v8: bloqueo 24 h solo por intentos fallidos de contraseña; conflicto otra WAN sin bloqueo; heartbeat mantiene sesión y permite roaming de IP; `force_new_session` para tomar sesión.
- Cliente: logout al cerrar app; heartbeat al entrar a la app principal; diálogo Tomar sesión / Reintentar / Regresar / Ayuda ante `session_active_other_network`.
- Documentación: `AUTH_APPS_SCRIPT.md`

## 0.14.1 - UI / skin y micro-animaciones

- Paleta dark/light renovada (acentos, bordes, estados de exito).
- Barra superior con acento y pestañas con bordes redondeados.
- Botones con borde y brillo al pasar el mouse; tarjetas con borde sutil.
- Campos de texto con borde animado al enfocar.
- Aparicion suave (fade-in) en login, app principal, registro, primer uso y dialogs.
- Indicador de estado con pulso cuando hay sesiones SSH activas.
- Tipografia segun SO (Segoe / SF / Ubuntu).

## 0.14.0 - Baseline de ingenieria

- Se agrego documentacion tecnica base del proyecto.
- Se agregaron guias de refactor, compatibilidad y benchmark.
- Se incorporaron estandares de desarrollo y calidad:
  - `pyproject.toml`
  - `requirements.txt`
  - `.editorconfig`
  - `CONTRIBUTING.md`
  - `QUALITY_GATES.md`
  - `SECURITY.md`
