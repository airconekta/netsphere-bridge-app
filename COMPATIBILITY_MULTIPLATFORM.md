# Requisito de Compatibilidad Multiplataforma

Objetivo: que NetSphere Bridge funcione en **Windows, Linux y macOS** sin forks separados.

---

## Regla principal de arquitectura

Toda integración con sistema operativo debe pasar por una capa `platform_adapter`:

- `platform_adapter/windows.py`
- `platform_adapter/linux.py`
- `platform_adapter/macos.py`
- `platform_adapter/base.py` (interfaz común)

La UI y la lógica SSH/escaneo no deben llamar APIs del SO directamente.

---

## Hallazgos actuales que bloquean portabilidad

En `netsphere bridge.py` hay dependencias Windows-only:

- Hosts file fijo: `C:\Windows\System32\drivers\etc\hosts`
- Edición de proxy por `winreg`
- Búsqueda de navegadores con rutas `Program Files` y `.exe`

Esto hay que aislar para soportar Linux/macOS.

---

## Contrato mínimo del adapter (cross-platform)

Definir estos métodos con misma firma en los 3 sistemas:

- `get_hosts_path() -> str`
- `add_hosts_alias(ip: str, alias: str) -> bool`
- `clear_hosts_alias(marker: str) -> bool`
- `set_system_socks_proxy(port: int) -> bool`
- `clear_system_proxy() -> bool`
- `detect_browsers() -> list[dict]`
- `open_browser(url: str, browser_id: str | None, socks_port: int | None) -> bool`

---

## Estrategia recomendada para evitar fricción por SO

## 1) Proxy: preferir perfil por proceso/app, no proxy global del sistema

Por compatibilidad, usa primero modo "proxy por navegador" y deja proxy global como opcional:

- Firefox: perfil temporal con `network.proxy.socks`, `network.proxy.socks_port`
- Chromium/Chrome/Edge/Brave:
  - Windows/Linux/macOS: lanzar proceso con `--proxy-server=socks5://127.0.0.1:<port>`

Ventaja:

- Evitas diferencias de registro/desktop-environment y permisos de admin.

## 2) Hosts: alias opcional y no bloqueante

Rutas por SO:

- Windows: `C:\Windows\System32\drivers\etc\hosts`
- Linux/macOS: `/etc/hosts`

Si no hay permisos, no fallar el flujo: continuar con IP directa.

## 3) Descubrimiento de navegador multiplataforma

Orden de detección sugerido:

1. PATH (`chrome`, `chromium`, `firefox`, `brave`, `msedge`, etc.)
2. Rutas conocidas por SO
3. Fallback a `webbrowser.open`

---

## Matriz de compatibilidad objetivo

- **SSH tunel + SOCKS**: Windows/Linux/macOS
- **Escaneo de LAN remota sobre SSH**: Windows/Linux/macOS
- **Abrir URL interna por proxy**: Windows/Linux/macOS
- **Proxy global del sistema**:
  - Windows: soportado
  - Linux/macOS: opcional/mejor esfuerzo (depende del entorno)
- **Alias hosts**:
  - Soportado en los 3, con fallback sin privilegios

---

## Plan técnico corto (sin romper lo actual)

1. Extraer funciones actuales:
   - `detectar_navegadores`
   - `_set_proxy_sistema`
   - `_clear_proxy_sistema`
   - uso de `HOSTS_FILE`
2. Crear adapter Windows con implementación actual (sin cambiar comportamiento).
3. Crear adapter Linux/macOS con:
   - detección de navegador por PATH
   - lanzamiento con flags de proxy por proceso
   - hosts best-effort
4. Cambiar llamadas en app para usar solo interfaz del adapter.

---

## Criterio de aceptación

Se considera compatible cuando en los 3 sistemas se completa el flujo:

1. Conectar SSH
2. Definir IP interna (detectada o manual)
3. Abrir navegador hacia `http://<ip>` por túnel
4. Navegar LAN interna sin tocar configuración manual del usuario
