#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Genera ../bridge_runtime_constants.py con URL y secretos XOR + base85.
Ejecutar desde la raíz del repo antes de empaquetar (Nuitka / PyInstaller).

Opcional (sobrescriben los valores por defecto del proyecto):
  set BRIDGE_AUTH_URL=https://...
  set BRIDGE_APP_TOKEN=...
  set BRIDGE_OFFLINE_K=...
"""
from __future__ import annotations

import base64
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "bridge_runtime_constants.py"

# Valores por defecto = mismos que netsphere bridge.py (base64 histórico)
def _defaults() -> tuple[str, str, str]:
    auth = os.environ.get(
        "BRIDGE_AUTH_URL",
        "https://script.google.com/macros/s/"
        "AKfycbyBi2CziLFT1-vUrRoabK4Iy3HAl-BpBDOHY41gZgXK4-xxkMuKpAuUnWmyK2KVAOg"
        "/exec",
    ).strip()
    tok = os.environ.get(
        "BRIDGE_APP_TOKEN",
        base64.b64decode("QWlSYzBuM2t0QV9TM2NyM3RfMjAyNSE=").decode("utf-8"),
    ).strip()
    off = os.environ.get(
        "BRIDGE_OFFLINE_K",
        base64.b64decode("YWlyY29uZWt0YS4wMUA=").decode("utf-8"),
    ).strip()
    return auth, tok, off


def _xor(data: bytes, key: bytes) -> bytes:
    return bytes(data[i] ^ key[i % len(key)] for i in range(len(data)))


def _emit() -> str:
    auth, tok, off = _defaults()
    key = secrets.token_bytes(32)
    blobs = []
    for s in (auth, tok, off):
        raw = s.encode("utf-8")
        x = _xor(raw, key)
        b85 = base64.b85encode(x).decode("ascii")
        blobs.append(b85)
    key_repr = ", ".join(str(b) for b in key)

    return f'''# -*- coding: utf-8 -*-
# AUTO-GENERATED por tools/generate_runtime_constants.py — no editar a mano.
from __future__ import annotations

import base64

_KEY = bytes([{key_repr}])

def _x(data: bytes, k: bytes) -> bytes:
    return bytes(data[i] ^ k[i % len(k)] for i in range(len(data)))

def _dec(blob_b85: str) -> str:
    raw = base64.b85decode(blob_b85.encode("ascii"))
    return _x(raw, _KEY).decode("utf-8")

_B_AUTH = "{blobs[0]}"
_B_TOK = "{blobs[1]}"
_B_OFF = "{blobs[2]}"

def auth_url() -> str:
    return _dec(_B_AUTH)

def app_secret() -> str:
    return _dec(_B_TOK)

def offline_k() -> str:
    return _dec(_B_OFF)
'''


def main() -> int:
    text = _emit()
    OUT.write_text(text, encoding="utf-8")
    print(f"OK → {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
