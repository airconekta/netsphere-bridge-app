#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Genera assets/bridge_app.ico para empaquetado (.exe con Nuitka / PyInstaller).

Prioridad:
  1) descarga.webp en la raíz del repo (si existe)
  2) LOGO_B64 embebido en netsphere bridge.py
"""
from __future__ import annotations

import base64
import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "netsphere bridge.py"
OUT_DIR = ROOT / "assets"
OUT_ICO = OUT_DIR / "bridge_app.ico"
WEBP = ROOT / "descarga.webp"


def _resample():
    from PIL import Image

    try:
        return Image.Resampling.LANCZOS
    except AttributeError:
        return Image.LANCZOS  # type: ignore[attr-defined]


def _save_multi_ico(src, path: Path) -> None:
    from PIL import Image

    res = _resample()
    sizes_px = (16, 32, 48, 64, 128, 256)
    images = [src.resize((s, s), res) for s in sizes_px]
    path.parent.mkdir(parents=True, exist_ok=True)
    images[0].save(
        path,
        format="ICO",
        sizes=[(im.width, im.height) for im in images],
        append_images=images[1:],
    )


def main() -> int:
    try:
        from PIL import Image
    except ImportError:
        print("Falta Pillow: pip install Pillow", file=sys.stderr)
        return 1

    if WEBP.is_file():
        src = Image.open(WEBP).convert("RGBA")
        _save_multi_ico(src, OUT_ICO)
        print(f"OK (desde descarga.webp) → {OUT_ICO}")
        return 0

    text = MAIN.read_text(encoding="utf-8")
    m = re.search(r'^LOGO_B64\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not m:
        print("No se encontró LOGO_B64 ni descarga.webp", file=sys.stderr)
        return 1
    raw = base64.b64decode(m.group(1).encode("ascii"))
    src = Image.open(io.BytesIO(raw)).convert("RGBA")
    _save_multi_ico(src, OUT_ICO)
    print(f"OK (desde LOGO embebido) → {OUT_ICO}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
