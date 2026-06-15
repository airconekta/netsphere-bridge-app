# Empaquetar NetSphere Bridge → Windows (**Nuitka**)

## Pasos rápidos (recomendado: **carpeta**, no un solo `.exe`)

```powershell
cd "ruta\al\proyecto\BRIDGE"
pip install -r requirements.txt
.\build_windows_exe.ps1
```

Salida: **`DIST\NetSphereBridge\NetSphereBridge.exe`** y el resto de DLL/archivos **en la misma carpeta**.  
Para repartir la app: **zippea toda** `DIST\NetSphereBridge\` (o usa un instalador). No muevas solo el `.exe`.

### Un solo archivo (onefile) — suele disparar antivirus

```powershell
.\build_windows_exe.ps1 -Mode Onefile
```

Opcional (exe más grande, a veces menos falsos positivos):

```powershell
.\build_windows_exe.ps1 -Mode Onefile -OnefileNoCompression
```

## Por qué Defender borra el `.exe` (y qué hacer)

- El modo **onefile** es un **autoextraíble** que descomprime a `%TEMP%`: muchas heurísticas lo tratan como **troyano genérico**, aunque el binario sea legítimo.
- Quitar DLL de MSVC **no** suele bastar: el patrón “empaquetado + ejecución desde temporal” ya es sospechoso.
- **Recomendación:** usa **`.\build_windows_exe.ps1`** sin parámetros (**standalone** / carpeta). Se comporta como una app normal con DLL al lado; **muchas veces deja de borrarse**.

Si aun así marca el build:

1. **Firmar el código** con un certificado de publicador (mejor mitigación para distribución real).  
2. **Enviar falso positivo** a Microsoft: [envío de archivos Windows Defender](https://www.microsoft.com/en-us/wdsi/filesubmission).  
3. **Exclusión temporal** solo en tu PC de desarrollo (no es solución para clientes).

## Requisitos de compilación (Nuitka)

Nuitka traduce el programa a C y lo enlaza: en Windows necesitas un **compilador C** (p. ej. **Visual Studio Build Tools** con “Desktop development with C++”, o el entorno que Nuitka pueda descargar). El script usa `--assume-yes-for-downloads` para que Nuitka pueda obtener dependencias cuando aplique.

Si falla el enlace o la descarga, revisa la salida de Nuitka y la [guía oficial de instalación en Windows](https://nuitka.net/doc/user-manual.html).

## DLL del runtime de Windows

- **Standalone (por defecto):** se usa **`--include-windows-runtime-dlls=yes`** para incluir las DLL de MSVC en la carpeta de salida (menos problemas al ejecutar en PCs sin Visual C++ Redistributable).
- **Onefile:** se usa **`--include-windows-runtime-dlls=no`** para no meter esas DLL dentro del blob comprimido. Si en destino falla por DLL faltante, instala el [**Visual C++ Redistributable x64**](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist) acorde a tu compilador (p. ej. VS 2022 / `cl 14.x`).

## Icono del `.exe`

Se pasa a Nuitka con **`--windows-icon-from-ico`**, en este orden:

1. `descarga.ico` en la raíz del proyecto  
2. `icon.ico` o `app.ico`  
3. Si existe `descarga.webp`, se convierte a `assets\bridge_app.ico`  
4. Si no hay ninguno, `tools/ensure_app_icon.py` genera `assets\bridge_app.ico` desde el **LOGO** embebido en `netsphere bridge.py` (mismo que la ventana).

## Qué hace el script

1. **`tools/generate_runtime_constants.py`** crea `bridge_runtime_constants.py` en la raíz (no lo subas a git si quieres ocultar endpoints en el repo fuente). Los valores se guardan **XOR + base85**; al arrancar, `netsphere bridge.py` los importa si existen.
2. **Nuitka** sin consola (`--windows-console-mode=disable`), plugin **tk-inter**, datos de **customtkinter**, paquete **platform_adapter**, y módulo **`bridge_runtime_constants`** si el archivo existe tras el paso 1.
3. **Standalone:** renombra `DIST\netsphere bridge.dist` → **`DIST\NetSphereBridge`** para una ruta limpia.

## Valores embebidos distintos a los del repo

Antes de generar:

```powershell
$env:BRIDGE_AUTH_URL = "https://script.google.com/macros/s/TU_ID/exec"
$env:BRIDGE_APP_TOKEN = "tu_app_secret"
$env:BRIDGE_OFFLINE_K = "tu_clave_offline"
py -3 tools\generate_runtime_constants.py
.\build_windows_exe.ps1
```

(O edita los defaults dentro de `tools/generate_runtime_constants.py`.)

## Sobre “ofuscación” y reverse engineering

- El `.exe` **no puede hacer imposible** el análisis: con tiempo y herramientas siempre se pueden extraer strings, depurar o volcar memoria.
- Lo que hace este flujo es **subir el esfuerzo**: secretos no van en texto plano en el `.py` que empaquetas.
- Para protección fuerte necesitarías productos comerciales (p. ej. ofuscadores con licencia) y aun así no hay garantía absoluta.

## Desarrollo sin archivo generado

Si **no** existe `bridge_runtime_constants.py`, la app usa los valores por defecto definidos en `netsphere bridge.py` (como hasta ahora).

## Archivo generado y git

Añade a `.gitignore` (recomendado):

```
bridge_runtime_constants.py
build/
*.build/
*.dist/
*.onefile-build/
```

Nuitka puede crear carpetas temporales con nombres derivados de `netsphere bridge.py`. La carpeta `DIST/` puede ignorarse o versionarse solo en releases internas.

## Alternativa: PyInstaller

Si necesitas un flujo solo con PyInstaller, instálalo aparte y replica las opciones (`--onefile`, `--windowed`, `--collect-all customtkinter`, etc.). El flujo **oficial** de este repo es **Nuitka**.
