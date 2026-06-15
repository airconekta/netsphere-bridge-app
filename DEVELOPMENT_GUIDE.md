# Development Guide

Guia operativa para desarrollar NetSphere Bridge con calidad de ingenieria.

## Setup rapido

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install -U pip
pip install -r requirements.txt
```

Linux/macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -r requirements.txt
```

## Ejecutar app

```powershell
python "netsphere bridge.py"
```

## Calidad local

```powershell
python -m black "netsphere bridge.py"
python -m ruff check .
python -m pytest
```

## Arquitectura actual (resumen)

- App monolitica en `netsphere bridge.py`
- UI: `customtkinter` + `tkinter`
- Red: SSH + SOCKS + escaneo de LAN remota
- Integraciones: auth/config online + carga de clientes

Documentos tecnicos clave:

- `ARCHITECTURE.md`
- `CODEMAP.md`
- `REFACTOR_PLAN.md`
- `COMPATIBILITY_MULTIPLATFORM.md`

## Regla de oro para cambios

No tocar todo de una vez.  
Mover por fases pequenas:

1. extraer
2. adaptar
3. validar
4. estabilizar

## Matriz minima de validacion manual

Antes de fusionar cambios, verificar:

1. login exitoso
2. login fallido
3. conexion SSH manual
4. busqueda de cliente + seleccion
5. escaneo de red remota
6. apertura de navegador via proxy
7. cierre individual y total de sesiones

## Roadmap de modularizacion recomendado

1. `platform_adapter/` (SO-specific)
2. `services/` (auth, ssh, scan, browser)
3. `ui/` (root, app, dialogs, widgets)
4. `state/` (CFG y estado global controlado)
