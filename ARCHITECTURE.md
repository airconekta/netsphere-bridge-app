# Arquitectura Tecnica - NetSphere Bridge

## Vista general

La aplicacion sigue una arquitectura monolitica de script unico con estado global compartido.

Capas logicas:

1. **UI (CustomTkinter/Tkinter)**  
   Construccion de ventanas, tabs, tablas, dialogos y eventos.
2. **Dominio de conexion remota**  
   SSH, tuneles SOCKS, escaneo de red, cache de hosts remotos.
3. **Servicios remotos**  
   Autenticacion/registro/configuracion online + carga de clientes desde Sheets.
4. **Integracion OS/Navegador**  
   Hosts file, proxy sistema, perfiles de Firefox y apertura de navegadores.

---

## Componentes principales

## 1) Estado global y configuracion

Variables relevantes:

- `CFG`: configuracion en memoria (host, usuario, password, columnas, tema, etc.)
- `tuneles`: diccionario de sesiones activas por `tid` (`usuario@host`)
- `clientes_cache`: cache de clientes cargados
- `_usuario_activo`, `_session_token`: estado de sesion autenticada
- `_heartbeat_activo`: control del hilo de keepalive

Observacion:

- `_save_cfg` esta en no-op (`pass`), por lo que no hay persistencia local en disco.

## 2) Autenticacion y sesion

Funciones clave:

- `registrar_usuario(datos)`
- `verificar_login(usuario, clave)`
- `_guardar_config_online(usuario, config_data)`
- `_cargar_configs_online(usuario)`
- `_aplicar_config_online(cfg_data)`
- `_heartbeat_loop(root)` + `_iniciar_heartbeat()` + `_detener_heartbeat()`

Objetivo:

- Gestionar acceso, estado de sesion y sincronizacion de configuracion con backend remoto.

## 3) Conexion SSH y tuneles

Funciones clave:

- `conectar_ssh(host, user, pw)`
- `_server(transport, tid, port)` (servidor local SOCKS)
- `_handle(sock, transport)` y `_relay(a, b)`
- `desconectar(tid)` / `desconectar_todos()`
- `procesos_activos()`

Resultado:

- Se levanta un SOCKS local por sesion para enrutar trafico hacia la red remota.

## 4) Descubrimiento y acceso a equipos remotos

Funciones clave:

- `_detectar_redes_remotas(client)` (subredes LAN remotas)
- `_escanear_con_cb(subnet, ini, fin, transport, ...)`
- `_tcp_ping`, `_icmp_ping_remoto`, `_ping_batch_remoto`
- `_http_raw`, `_http_get`, `_titulo`

Objetivo:

- Encontrar IPs activas y detectar cuales responden por HTTP para acceso desde navegador.

## 5) Datos de clientes (Sheets)

Funciones clave:

- `_normalizar_sheets_url(url)`
- `cargar_clientes()`
- `invalidar_cache()`
- `buscar_clientes(q, clientes)`

Uso:

- Alimentar la tab de clientes para seleccionar rapidamente a quien conectar.

## 6) UI principal

Clases:

- `CtkTable`: wrapper de `ttk.Treeview` para tabla con ordenamiento.
- `App`: interfaz principal autenticada.
- `RootApp`: shell raiz de la app (login/registro/primer uso/main app).

Tabs de `App`:

- `👥 Clientes`: busqueda, tabla, ficha y acceso rapido.
- `🔌 Conectar`: conexion manual por host/usuario/clave.
- `📺 Abiertos`: sesiones activas, reabrir navegador, escanear, cerrar sesiones.

Menu oculto:

- Trigger `Alt + 6 + 6 + 6`, abre configuracion avanzada.

---

## Flujo principal de ejecucion

1. Arranque: `_init_tema()` -> `RootApp()`.
2. `RootApp._mostrar_login()` para autenticar.
3. Si login ok: verificar/cargar configuraciones remotas.
4. Primer uso o app principal (`_mostrar_primer_uso` / `_mostrar_app`).
5. En app principal: conectar SSH, escanear, abrir navegador por SOCKS.
6. Heartbeat mantiene sesion valida; si expira, forzar logout.

---

## Dependencias externas

- GUI: `customtkinter`, `tkinter`
- Red/SSH: `paramiko`, `socket`, `threading`
- HTTP: `requests`
- Imagenes: `Pillow`

Notas:

- El script intenta auto-instalar librerias faltantes al inicio.

---

## Deuda tecnica detectada (prioridad para refactor)

1. Script monolitico de gran tamano (dificulta pruebas y mantenibilidad).
2. Estado global mutable ampliamente compartido.
3. Multiples `except:` genericos que ocultan errores.
4. Duplicidad de funcion `_set_window_icon`.
5. Sin suite de pruebas automatizadas.
6. Persistencia de configuracion local deshabilitada por diseno.

---

## Propuesta de modularizacion (futura)

- `app_ui.py`: `RootApp`, `App`, widgets y tablas.
- `auth_service.py`: login, registro, heartbeat, config remota.
- `ssh_service.py`: conectar/desconectar, tunel, relay, procesos.
- `scan_service.py`: ping/http scan y deteccion de equipos.
- `clients_service.py`: sheets, cache, busqueda.
- `browser_service.py`: deteccion/apertura de navegadores y proxy.
- `config.py`: constantes, paletas y estado controlado.
