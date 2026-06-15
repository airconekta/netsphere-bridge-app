# Construye NetSphere Bridge con Nuitka (icono .ico, sin consola).
#
# Modo recomendado para antivirus: STANDALONE (carpeta, sin autoextraíble onefile).
# El onefile suele marcarse como troyano genérico por heurística (empaquetado + descompresión a %TEMP%).
#
# Uso:
#   .\build_windows_exe.ps1                          # standalone → DIST\NetSphereBridge\
#   .\build_windows_exe.ps1 -Mode Onefile            # un solo .exe en DIST\
#   .\build_windows_exe.ps1 -Mode Onefile -OnefileNoCompression  # onefile sin comprimir payload (a veces menos FP)
#
param(
    [ValidateSet('Standalone', 'Onefile')]
    [string]$Mode = 'Standalone',
    [switch]$OnefileNoCompression
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
Set-Location $Root

Write-Host "==> Modo Nuitka: $Mode"
if ($Mode -eq 'Onefile') {
    Write-Host "    (Onefile: más cómodo de distribuir; Defender a veces lo borra — prueba Standalone si pasa.)"
}

Write-Host "==> Dependencias de la app..."
& py -3 -m pip install -q -r "$Root\requirements.txt"

Write-Host "==> Generando constantes ofuscadas (bridge_runtime_constants.py)..."
& py -3 "$Root\tools\generate_runtime_constants.py"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "==> Nuitka (herramientas de build)..."
& py -3 -m pip install -q -r "$Root\requirements-build.txt"

$PyScript = Join-Path $Root "netsphere bridge.py"
if (-not (Test-Path $PyScript)) {
    Write-Error "No se encuentra: $PyScript"
    exit 1
}

# Icono del .exe (Nuitka: --windows-icon-from-ico)
$IconPath = $null
foreach ($name in @("descarga.ico", "icon.ico", "app.ico")) {
    $cand = Join-Path $Root $name
    if (Test-Path -LiteralPath $cand) {
        $IconPath = $cand
        break
    }
}
if (-not $IconPath) {
    Write-Host "==> Generando assets\bridge_app.ico (descarga.webp o logo embebido)..."
    & py -3 "$Root\tools\ensure_app_icon.py"
    if ($LASTEXITCODE -eq 0) {
        $gen = Join-Path $Root "assets\bridge_app.ico"
        if (Test-Path -LiteralPath $gen) { $IconPath = $gen }
    }
}

Write-Host "==> Nuitka (puede tardar varios minutos)..."
# --progress-bar=none: evita AssertionError en fase Onefile en algunas versiones.
$nuitka = @(
    "-m", "nuitka",
    "--windows-console-mode=disable",
    "--progress-bar=none",
    "--assume-yes-for-downloads",
    "--enable-plugin=tk-inter",
    "--include-package=platform_adapter",
    "--include-package-data=customtkinter",
    "--output-dir=$Root\DIST",
    "--output-filename=NetSphereBridge.exe",
    "--remove-output"
)

if ($Mode -eq 'Onefile') {
    $nuitka += "--mode=onefile"
    # Sin empaquetar vcruntime en el blob onefile (menos ruido); el PC necesita VC++ Redist si falta algo.
    $nuitka += "--include-windows-runtime-dlls=no"
    if ($OnefileNoCompression) {
        $nuitka += "--onefile-no-compression"
        Write-Host "    Onefile sin compresión de payload (exe más grande, a veces menos falsos positivos)."
    }
} else {
    $nuitka += "--mode=standalone"
    # Carpeta: comportamiento de app normal; incluir runtime MSVC suele ser aceptable y evita fallos en PCs sin Redist.
    $nuitka += "--include-windows-runtime-dlls=yes"
}

if ($IconPath -and (Test-Path -LiteralPath $IconPath)) {
    Write-Host "    Icono del ejecutable: $IconPath"
    $nuitka += "--windows-icon-from-ico=$IconPath"
} else {
    Write-Host "    (Sin .ico: Nuitka usará el icono por defecto del runtime Python)"
}
$const = Join-Path $Root "bridge_runtime_constants.py"
if (Test-Path -LiteralPath $const) {
    $nuitka += "--include-module=bridge_runtime_constants"
}
$nuitka += $PyScript

& py -3 @nuitka

if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if ($Mode -eq 'Standalone') {
    $distUgly = Join-Path $Root "DIST\netsphere bridge.dist"
    $distNice = Join-Path $Root "DIST\NetSphereBridge"
    if (Test-Path -LiteralPath $distUgly) {
        if (Test-Path -LiteralPath $distNice) {
            Remove-Item -LiteralPath $distNice -Recurse -Force
        }
        Rename-Item -LiteralPath $distUgly -NewName "NetSphereBridge"
    }
    Write-Host ""
    Write-Host "Listo (standalone, recomendado para antivirus):"
    Write-Host "  $Root\DIST\NetSphereBridge\NetSphereBridge.exe"
    Write-Host "  Distribuye toda la carpeta DIST\NetSphereBridge\ (zip o instalador)."
    Write-Host ""
} else {
    Write-Host ""
    Write-Host "Listo (onefile): $Root\DIST\NetSphereBridge.exe"
    Write-Host ""
}
