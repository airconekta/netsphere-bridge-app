# Mapa de Codigo - `netsphere bridge.py`

Este archivo sirve para ubicar rapido "donde tocar" sin releer todo el script.

## Secciones importantes por responsabilidad

## 1) Utilidades base y tema (inicio del archivo)

- Logging y helpers de decode/base64
- Paletas visuales y tema auto (dia/noche)
- Carga de logo en memoria
- Defaults de configuracion en `CFG`

Funciones clave:

- `_log`, `_d`, `_dd`
- `_apply_palette`, `_tema_auto`, `_init_tema`
- `_get_logo_pil`

## 2) Autenticacion y configuracion online

Funciones:

- `registrar_usuario`
- `verificar_login`
- `_guardar_config_online`
- `_cargar_configs_online`
- `_aplicar_config_online`

Si falla login o configuracion remota, revisar aqui primero.

## 3) SSH + SOCKS + lifecycle de tuneles

Funciones:

- `conectar_ssh`
- `_server`, `_handle`, `_relay`
- `desconectar`, `desconectar_todos`
- `_log_ssh_open`, `_log_ssh_close`

Si hay cortes de conexion o puertos ocupados, iniciar diagnostico aqui.

## 4) Red remota y escaneo

Funciones:

- `_detectar_redes_remotas`
- `_escanear_con_cb`
- `_tcp_ping`, `_icmp_ping_remoto`, `_ping_batch_remoto`
- `_http_raw`, `_http_get`, `_titulo`

Si no aparecen equipos remotos detectables, revisar esta zona.

## 5) Clientes (fuente externa tipo Sheets)

Funciones:

- `_normalizar_sheets_url`
- `cargar_clientes`
- `invalidar_cache`
- `buscar_clientes`

Si no se listan clientes o la busqueda no responde, revisar estas funciones.

## 6) UI reusable y tabla

Helpers:

- `mk_btn`, `mk_label`, `mk_frame`, `mk_sep`
- `_apply_treeview_style`

Componente:

- `class CtkTable` (tabla sortable con seleccion y doble click)

## 7) App principal autenticada (`class App`)

Metodos de estructura:

- `_build_header`
- `_build_tabs`
- `_build_statusbar`

Tabs:

- Clientes: `_build_tab_clientes`, `_do_search`, `_on_select`, `_flujo_buscador`
- Conectar: `_build_tab_conectar`, `_flujo_manual`, `_solo_conectar_manual`
- Abiertos: `_build_tab_sesiones`, `_refrescar_sesiones`, acciones `_ses_*`

Flujos destacados:

- Acceso automatico desde cliente seleccionado
- Dialogo de acceso (`_dialogo_acceso`)
- Escaneo interactivo (`_abrir_escaneo`)
- Apertura navegador (`_nav_dialog`)

Configuracion oculta:

- `_abrir_config_oculta` via combinacion `Alt + 6 + 6 + 6`

## 8) Shell de aplicacion (`class RootApp`)

Pantallas:

- `_mostrar_login`
- `_mostrar_registro`
- `_mostrar_primer_uso`
- `_mostrar_app`

Control general:

- `_cerrar_todo`
- `_limpiar`
- `_on_tema_login`

## 9) Sesion en segundo plano (heartbeat)

Funciones:

- `_heartbeat_loop`
- `_iniciar_heartbeat`
- `_detener_heartbeat`

Si el servidor invalida sesion o desconecta al usuario, revisar aqui.

## 10) Entrada del programa

- Bloque `if __name__ == "__main__":`
- Inicializa tema, crea `RootApp`, ejecuta `mainloop`.

---

## Guia de depuracion por sintoma

- **No entra al sistema** -> `verificar_login`, endpoint auth y respuesta JSON.
- **Conecta SSH pero no abre web** -> `_server`, `_nav_dialog`, `abrir_browser`.
- **No encuentra equipos en escaneo** -> `_detectar_redes_remotas`, `_escanear_con_cb`.
- **No aparecen clientes** -> `cargar_clientes`, URL de sheets y normalizacion.
- **Sesion se cae sola** -> `_heartbeat_loop` y validacion remota.

---

## Lista minima de chequeo antes de modificar

1. Ubicar la funcion en este mapa.
2. Revisar quien la llama y que estado global usa (`CFG`, `tuneles`).
3. Validar impactos en UI y en flujo de red.
4. Probar:
   - login
   - conexion manual
   - busqueda de cliente
   - apertura de navegador
   - cierre de sesiones
