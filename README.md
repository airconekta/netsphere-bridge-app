# NetSphere Bridge - Proyecto

Este repositorio contiene una aplicacion de escritorio en Python para conectarse a equipos de clientes por SSH, crear tuneles SOCKS y abrir interfaces web remotas desde el navegador local.

## Propuesta de valor

NetSphere Bridge acelera soporte tecnico ISP con un flujo simple:

- buscar o indicar IP interna
- crear puente proxy por SSH
- navegar rango LAN interno sin configuracion manual compleja

## Estado actual del repositorio

- Codigo fuente principal: `netsphere bridge.py`
- Artefactos compilados (Nuitka): `DIST/`
- Recursos de icono: `descarga.ico`, `descarga.webp`
- Reporte de crash de compilacion: `nuitka-crash-report.xml`

## Que hace la aplicacion

- Autenticacion de usuarios contra servicio remoto (Apps Script)
- Registro de nuevos usuarios
- Conexion SSH con `paramiko`
- Forwarding SOCKS local para navegar por equipos remotos
- Busqueda de clientes desde Google Sheets
- Escaneo de red remota para detectar equipos
- Interfaz grafica completa con `customtkinter`

## Ejecutar en desarrollo

Requisitos:

- `customtkinter`
- `paramiko`
- `requests`
- `Pillow`

Instalacion recomendada:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Ejecucion:

```powershell
python "netsphere bridge.py"
```

## Empaquetar `.exe` (Windows)

Ver **`BUILD_EXE.md`**: script `build_windows_exe.ps1` (Nuitka + icono `.ico` + constantes XOR/base85). Por defecto genera **carpeta** `DIST\NetSphereBridge\` (menos falsos positivos de antivirus que el onefile). El archivo generado `bridge_runtime_constants.py` está en `.gitignore`.

## Punto de entrada

La aplicacion inicia en:

- `if __name__ == "__main__":`
- `_init_tema()`
- `RootApp().mainloop()`

## Estructura funcional (alto nivel)

- `RootApp`: ciclo de vida general, login, registro, primer uso y transicion a app principal.
- `App`: UI principal con 3 tabs:
  - Clientes
  - Conectar
  - Abiertos
- Utilidades globales:
  - autenticacion y heartbeat de sesion
  - gestion de tuneles SSH/SOCKS
  - escaneo de hosts remotos
  - integracion con navegador

## Flujo de uso tipico

1. Usuario inicia sesion.
2. Se cargan configuraciones remotas.
3. En la tab Clientes busca y selecciona cliente.
4. Se crea tunel SSH + SOCKS.
5. Se abre navegador apuntando al equipo remoto.
6. Se gestionan sesiones abiertas en la tab Abiertos.

## Documentacion interna recomendada

- Arquitectura y componentes: `ARCHITECTURE.md`
- Mapa de funciones y flujo: `CODEMAP.md`
- Plan de refactor por fases: `REFACTOR_PLAN.md`
- Compatibilidad multiplataforma: `COMPATIBILITY_MULTIPLATFORM.md`
- Benchmark enfoque bridge/proxy LAN: `RELAY_PROXY_LAN_BENCHMARK.md`
- Guia de desarrollo: `DEVELOPMENT_GUIDE.md`
- Reglas de contribucion: `CONTRIBUTING.md`
- Criterios de calidad: `QUALITY_GATES.md`
- Notas de seguridad: `SECURITY.md`

## Notas para mantenimiento

- El proyecto esta concentrado en un solo archivo grande.  
- Para cambios grandes, conviene extraer modulos (auth, ssh, ui, scanner, sheets).
- Evita editar `DIST/` manualmente: son artefactos de build.

## Objetivo de evolucion

Mantener el comportamiento actual estable y llevar la base a una arquitectura modular, portable y verificable para equipos de desarrollo mas exigentes.
