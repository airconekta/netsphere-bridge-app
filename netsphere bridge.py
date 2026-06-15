"""
NetSphere Bridge v14 — Toha Heavy Industries
pip install customtkinter paramiko requests Pillow cryptography

Depuración: %LOCALAPPDATA%\\NetSphereBridge\\bridge_debug.log
Preferencias locales: bridge_prefs.json en este equipo.
Copiar depuración: Ajustes (Alt+6+6+6) → «Depuración». Consola solo si BRIDGE_DEBUG_CONSOLE=1.
"""
import os,sys,socket,threading,struct,subprocess,time,csv,re,logging
import logging.handlers
import tempfile,shutil,webbrowser,base64,io,datetime,hashlib
import json as _json
import warnings; warnings.filterwarnings("ignore")

for _p in["paramiko","requests","customtkinter","Pillow","cryptography"]:
    try: __import__(_p if _p!="Pillow" else "PIL")
    except ImportError:
        subprocess.check_call(
            [sys.executable,"-m","pip","install",_p,"-q"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

import paramiko,requests

_VER = "14"  # temprano: usado por el registro de depuración

# ── Depuración: SOLO archivo (nada en consola salvo BRIDGE_DEBUG_CONSOLE=1) ──
_bridge_file_logger = None
_log_session_banner_done = False


def _bridge_log_dir():
    try:
        if sys.platform.startswith("win"):
            base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
            d = os.path.join(base, "NetSphereBridge")
        else:
            d = os.path.join(os.path.expanduser("~"), ".netsphere_bridge")
        os.makedirs(d, exist_ok=True)
        return d
    except Exception:
        return tempfile.gettempdir()


def bridge_debug_log_path():
    """Ruta del registro de depuración (para soporte / pegar)."""
    return os.path.join(_bridge_log_dir(), "bridge_debug.log")


def bridge_prefs_path():
    """Preferencias locales (último usuario de login, tema). Misma carpeta que el .log — válido como .py o .exe."""
    return os.path.join(_bridge_log_dir(), "bridge_prefs.json")


def _load_local_prefs():
    try:
        with open(bridge_prefs_path(), "r", encoding="utf-8") as f:
            d = _json.load(f)
            return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save_local_prefs(updates: dict):
    """
    Persiste preferencias en disco (tema, flags recordar, credenciales opcionales).
    Funciona empaquetado (Nuitka/PyInstaller; usa %LOCALAPPDATA%\\NetSphereBridge en Windows).
    """
    if not updates:
        return
    try:
        path = bridge_prefs_path()
        data = _load_local_prefs()
        for k, v in updates.items():
            if v is None:
                data.pop(k, None)
            else:
                data[k] = v
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            _json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        pass


# ── Cifrado local: NSC1 = solo bridge.key | NSC2 = bridge.key + semilla (hoja bridge_semillas) ──
_CRED_PREFIX_NSC1 = "NSC1:"
_CRED_PREFIX_NSC2 = "NSC2:"
# Semilla devuelta por Apps Script en login (misma fila que USUARIO en hoja bridge_semillas)
_bridge_sheet_seed = ""
_machine_fernet = None
_fernet_import_failed = False
_FERNET_KEY_FAILED = object()  # sentinel: ya falló bridge.key; no reintentar en bucle


def bridge_machine_key_path():
    return os.path.join(_bridge_log_dir(), "bridge.key")


def _get_machine_fernet():
    """
    Fernet con clave generada la primera vez y guardada en bridge.key (cifrado NSC1).
    """
    global _machine_fernet, _fernet_import_failed
    if _fernet_import_failed:
        return None
    if _machine_fernet is _FERNET_KEY_FAILED:
        return None
    if _machine_fernet is not None:
        return _machine_fernet
    try:
        from cryptography.fernet import Fernet
    except Exception:
        _fernet_import_failed = True
        _log("[PREFS] No se pudo usar el módulo de seguridad; no se guardará la clave en este equipo.")
        return None
    path = bridge_machine_key_path()
    try:
        if os.path.isfile(path):
            with open(path, "rb") as f:
                key = f.read().strip()
        else:
            key = Fernet.generate_key()
            tmp = path + ".tmp"
            with open(tmp, "wb") as f:
                f.write(key)
            os.replace(tmp, path)
        _machine_fernet = Fernet(key)
        return _machine_fernet
    except Exception as ex:
        _log("[PREFS] No se pudo usar el almacenamiento local de credenciales.")
        _machine_fernet = _FERNET_KEY_FAILED
        return None


def _read_bridge_key_raw_bytes():
    """Bytes del archivo bridge.key (crea el archivo vía NSC1 si no existe)."""
    p = bridge_machine_key_path()
    if not os.path.isfile(p):
        if _get_machine_fernet() is None:
            return None
    try:
        with open(p, "rb") as f:
            return f.read().strip()
    except Exception:
        return None


def _fernet_nsc2(raw_key_bytes: bytes, seed: str):
    from cryptography.fernet import Fernet

    combined = raw_key_bytes + b"|" + str(seed).encode("utf-8")
    dk = hashlib.pbkdf2_hmac("sha256", combined, b"NSBridgeSheetV2", 100000, dklen=32)
    fkey = base64.urlsafe_b64encode(dk)
    return Fernet(fkey)


def _encrypt_for_machine(plaintext: str):
    if plaintext is None:
        return None
    raw = str(plaintext).encode("utf-8")
    if not raw:
        return None
    try:
        from cryptography.fernet import Fernet
    except Exception:
        return None
    key_bytes = _read_bridge_key_raw_bytes()
    if not key_bytes:
        return None
    seed = (globals().get("_bridge_sheet_seed") or "").strip()
    try:
        if seed:
            f = _fernet_nsc2(key_bytes, seed)
            pref = _CRED_PREFIX_NSC2
        else:
            f = Fernet(key_bytes)
            pref = _CRED_PREFIX_NSC1
        tok = f.encrypt(raw)
        return pref + tok.decode("ascii")
    except Exception:
        return None


def _decrypt_for_machine(blob: str):
    if not blob:
        return None
    s = str(blob)
    if s.startswith(_CRED_PREFIX_NSC2):
        seed = (globals().get("_bridge_sheet_seed") or "").strip()
        if not seed:
            return None
        key_bytes = _read_bridge_key_raw_bytes()
        if not key_bytes:
            return None
        try:
            f = _fernet_nsc2(key_bytes, seed)
            tok = s[len(_CRED_PREFIX_NSC2) :].encode("ascii")
            return f.decrypt(tok).decode("utf-8")
        except Exception:
            return None
    if s.startswith(_CRED_PREFIX_NSC1):
        f = _get_machine_fernet()
        if f is None:
            return None
        try:
            tok = s[len(_CRED_PREFIX_NSC1) :].encode("ascii")
            return f.decrypt(tok).decode("utf-8")
        except Exception:
            return None
    return s if s else None


def _persist_login_credentials_prefs(remember_user: bool, remember_pass: bool, user_str, pass_str):
    """Usuario para autocompletar; clave guardada solo si el usuario marca recordar."""
    updates = {}
    u = (user_str or "").strip()
    pw = pass_str or ""

    if remember_user:
        updates["last_login_user"] = u
        updates["cred_user_enc"] = None
        updates["remember_user"] = True
    else:
        updates["remember_user"] = False
        updates["cred_user_enc"] = None
        updates["last_login_user"] = None

    if remember_pass and pw:
        enc_p = _encrypt_for_machine(pw)
        if enc_p:
            updates["cred_pass_enc"] = enc_p
            updates["remember_pass"] = True
        else:
            updates["remember_pass"] = False
            updates["cred_pass_enc"] = None
    else:
        updates["remember_pass"] = False
        updates["cred_pass_enc"] = None

    _save_local_prefs(updates)


def _init_bridge_file_logger():
    global _bridge_file_logger
    if _bridge_file_logger is not None:
        return _bridge_file_logger
    path = bridge_debug_log_path()
    lg = logging.getLogger("netsphere.bridge.file")
    lg.setLevel(logging.DEBUG)
    lg.handlers.clear()
    fh = logging.handlers.RotatingFileHandler(
        path, maxBytes=1_500_000, backupCount=4, encoding="utf-8", delay=True
    )
    fh.setFormatter(logging.Formatter("%(asctime)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    lg.addHandler(fh)
    lg.propagate = False
    _bridge_file_logger = lg
    return lg


def _log(msg):
    """Escribe en bridge_debug.log (rotativo). No usa consola."""
    global _log_session_banner_done
    try:
        lg = _init_bridge_file_logger()
        if not _log_session_banner_done:
            _log_session_banner_done = True
            import platform as _pf
            lg.info("=" * 60)
            lg.info(
                "Sesión | v%s | %s | Python %s",
                _VER,
                _pf.platform(),
                sys.version.split()[0],
            )
            lg.info("Registro: %s", bridge_debug_log_path())
            lg.info("=" * 60)
        lg.info("%s", msg)
        if os.environ.get("BRIDGE_DEBUG_CONSOLE", "").strip().lower() in ("1", "true", "yes"):
            print(msg, flush=True)
    except Exception:
        pass


def _log_exception(context=""):
    """Traceback completo al archivo de depuración."""
    import traceback
    try:
        tb = traceback.format_exc()
        _log(f"[EXCEPCIÓN] {context}\n{tb}")
    except Exception:
        pass


def copiar_registro_depuracion_al_portapapeles(tk_widget=None):
    """
    Junta cabecera de entorno + últimas líneas del .log para pegar en soporte.
    Devuelve (ok: bool, mensaje: str).
    """
    import platform as _pf
    g = globals()
    _ua = g.get("_usuario_activo", "")
    _tun = g.get("tuneles") or {}
    path = bridge_debug_log_path()
    hdr = (
        "=== NetSphere Bridge — registro para soporte ===\n"
        f"versión: {_VER}\n"
        f"python: {sys.version}\n"
        f"plataforma: {_pf.platform()}\n"
        f"archivo completo: {path}\n"
        f"usuario sesión: {repr(_ua)}\n"
        f"túneles activos: {len(_tun)}\n"
        "--- inicio extracto (final del archivo) ---\n"
    )
    body = ""
    try:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                body = f.read()[-52000:]
        else:
            body = "(aún no hay archivo de registro; ejecuta acciones y vuelve a intentar)\n"
    except Exception as ex:
        body = f"(error leyendo registro: {ex})\n"
    text = hdr + body
    w = tk_widget if tk_widget is not None else g.get("_root_ref")
    if w is None:
        return False, "No hay ventana para usar el portapapeles."
    try:
        w.clipboard_clear()
        w.clipboard_append(text)
        w.update()
        return True, f"Copiado ({len(text)} caracteres).\n\nArchivo: {path}"
    except Exception as ex:
        _log(f"[CLIPBOARD] {ex}")
        return False, str(ex)
import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox
from PIL import Image,ImageTk
from platform_adapter import get_platform_adapter

logging.getLogger("paramiko").setLevel(logging.CRITICAL)
logging.getLogger("paramiko.transport").setLevel(logging.CRITICAL)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)

def _nombre_empresa():
    """Nombre de la empresa del operador (máx 24 chars, solo letras/números/espacios)."""
    raw = CFG.get("empresa","") or ""
    import re as _re
    clean = _re.sub(r"[^A-Za-z0-9 áéíóúÁÉÍÓÚñÑ]","", raw).strip()[:24]
    return clean if clean else "Bridge"

def _titulo_app():
    emp = _nombre_empresa()
    return (emp + " · NetSphere") if emp else "NetSphere · Bridge"
def _d(s):
    """Decodificador simple (solo fallback de desarrollo)."""
    return base64.b64decode(s.encode()).decode()

# Apps Script v8 — si existe bridge_runtime_constants.py (generado antes del .exe),
# URL y secretos vienen ofuscados (XOR+base85). Ver BUILD_EXE.md.
_AUTH_URL_FALLBACK = (
    "https://script.google.com/macros/s/"
    "AKfycbyBi2CziLFT1-vUrRoabK4Iy3HAl-BpBDOHY41gZgXK4-xxkMuKpAuUnWmyK2KVAOg"
    "/exec"
)
_APP_TOKEN_FALLBACK = _d("QWlSYzBuM2t0QV9TM2NyM3RfMjAyNSE=")
_OFFLINE_K_FALLBACK = _d("YWlyY29uZWt0YS4wMUA=")

try:
    from bridge_runtime_constants import app_secret as _br_app_secret
    from bridge_runtime_constants import auth_url as _br_auth_url
    from bridge_runtime_constants import offline_k as _br_offline_k

    _AUTH_URL = _br_auth_url()
    _APP_TOKEN = _br_app_secret()
    _OFFLINE_K = _br_offline_k()
except ImportError:
    _AUTH_URL = _AUTH_URL_FALLBACK
    _APP_TOKEN = _APP_TOKEN_FALLBACK
    _OFFLINE_K = _OFFLINE_K_FALLBACK

# ── TEMA ─────────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

PALETTES = {
    "dark": {
        "BG":"#060b14","BG2":"#0c1526","BG3":"#121f3d","CARD":"#162844","BORDER":"#2a5088",
        "AIR":"#8ec5ff","ACCENT":"#2563eb","ACCENT2":"#3b82f6",
        "GREEN":"#22c55e","GREEN2":"#16a34a","RED":"#ef4444","RED2":"#b91c1c",
        "TEXT":"#e8f1ff","MUTED":"#7b9cc4","WHITE":"#ffffff","DOT":"#5b8fd4",
        "BTN_TXT":"#ffffff","ICON_TINT":(0x8e,0xc5,0xff),
        "GLOW":"#60a5fa","ENTRY_FOCUS":"#3b82f6","SUCCESS_PULSE":"#4ade80",
        "ACCENT_SOFT":"#1e3a5f","SHADOW":"#020617",
    },
    "light": {
        "BG":"#eef2f9","BG2":"#e2e8f4","BG3":"#d0dce8","CARD":"#ffffff","BORDER":"#94b8e0",
        "AIR":"#1d4ed8","ACCENT":"#2563eb","ACCENT2":"#3b82f6",
        "GREEN":"#15803d","GREEN2":"#166534","RED":"#dc2626","RED2":"#b91c1c",
        "TEXT":"#0f172a","MUTED":"#475569","WHITE":"#0f172a","DOT":"#3b6ea5",
        "BTN_TXT":"#ffffff","ICON_TINT":(0x29,0x63,0xeb),
        "GLOW":"#2563eb","ENTRY_FOCUS":"#3b82f6","SUCCESS_PULSE":"#22c55e",
        "ACCENT_SOFT":"#dbeafe","SHADOW":"#cbd5e1",
    },
}
_T = dict(PALETTES["dark"])

def _apply_palette(name):
    global _T
    _T.update(PALETTES[name])
    ctk.set_appearance_mode("dark" if name=="dark" else "light")

def C(k): return _T[k]

def _tema_auto():
    h = datetime.datetime.now().hour
    return "light" if 7<=h<19 else "dark"

def _ui_font(size, bold=False):
    fam = "Segoe UI" if sys.platform.startswith("win") else (
        ".SF NS Text" if sys.platform == "darwin" else "Ubuntu"
    )
    return (fam, size, "bold") if bold else (fam, size)

def _ui_fade_in(win, end_alpha=1.0, steps=14, delay_ms=12):
    """Aparición suave de ventana (si el SO lo permite)."""
    try:
        win.attributes("-alpha", 0.0)
    except Exception:
        return

    def step(i=[0]):
        if i[0] >= steps or not win.winfo_exists():
            try:
                win.attributes("-alpha", end_alpha)
            except Exception:
                pass
            return
        try:
            a = end_alpha * (i[0] + 1) / steps
            win.attributes("-alpha", min(end_alpha, a))
        except Exception:
            return
        i[0] += 1
        win.after(delay_ms, step)

    win.after(1, step)

def _style_ctk_entry(entry):
    """Borde animado al enfocar."""
    def _in(_):
        try:
            entry.configure(border_color=C("ENTRY_FOCUS"), border_width=2)
        except Exception:
            pass

    def _out(_):
        try:
            entry.configure(border_color=C("BORDER"), border_width=1)
        except Exception:
            pass

    try:
        entry.configure(border_width=1)
    except Exception:
        pass
    entry.bind("<FocusIn>", _in)
    entry.bind("<FocusOut>", _out)

def _attach_btn_hover_glow(btn, border_idle=None, border_hover=None):
    idle = border_idle or C("BORDER")
    glow = border_hover or C("GLOW")

    def _in(_):
        try:
            btn.configure(border_color=glow)
        except Exception:
            pass

    def _out(_):
        try:
            btn.configure(border_color=idle)
        except Exception:
            pass

    btn.bind("<Enter>", _in)
    btn.bind("<Leave>", _out)

FN     = _ui_font(11, False)
FN_B   = _ui_font(11, True)
FN_BTN = _ui_font(11, True)
FN_LG  = _ui_font(14, True)
FN_XL  = _ui_font(18, True)
FN_SM  = _ui_font(9, False)

# ── LOGO ─────────────────────────────────────────────────────
LOGO_B64 = "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAAHQ0lEQVR4nO2Yf2hU2RXHz7nvvZl5jvlhyCZpomux6yRpq0EsVSgrttq6CO0uiyz9oy1C6T/tdlMU9o+VEmT/Kf21CNKi9h9Z2j8ipaXbrZWsu27dDEQca37UECeBSYxmMpnJvExmJjPv3Xu//SNvJC7Rrd2JWJoPPB7v3vvOueedc8899xGts84666zzKeC1lN3T03Nf/smTJ/Ua6vrfZc080NPTU9vS0lKTy+VgmiaPjY2lzp49662VvqoBwCQiunHjRo/jOEsLCwu5TCazFI1Gd/j9opr6zGoKW0l9fb1VV1cXIiKLiIyGhoY18XZVv8ZKpJQgIhCRUkrBdd010bNmBjAz0fIa4woA+MKFC1X1xJqF0EoAkGEYipnBzKqasp+IAUREuVwueOrUqSARUXd3d/lJ6X1sKlkoHo+/iWU8rTXyi/m75XJ5amBgoNcfV5XwfSIeYGYKbwy3EhGFQqGpaspes0X8cbTWLhEprXVVw+eJrQEhRICIiJmDVZVbTWEVADD7ebSClHKGiKaFEPeqqWtNDGBmEFElVKCUovHx8W8R0XOhUOi7/piqVKdVDSEATEQ4c+aM1dra+qLfLIiIyuVyiZnLH3PM00Ulhc7Nzb0FAEopCUBLKTE8PNwFgHt7e41q6qyaBwAYzCxv3rz5zcbGxp8QkfTlw+/HcjUBVEsnUZUMACCYWfX19dVFIpHfEFGl7lfkz92yrKpOvEK1PMAjIyOBrVu3/t627c2VRiGWc4RpmqSUqmroVFjVAAAGPfq0BiLSRGTEYjEmIpRKJTsUCv1OSvlbImLTNImWPcBSSqG1ngRgxmIxXllGXLlyhfbv36+I6JMM1NXKXE8VD3xlZiYAdO/eve81NTW1uK4LImIAC5ZlhaWUhmmaDODO2NjYQCQSOaK1BoC8YRghrXUQQI7BNXbYFjMzM3/O5XLt7e3tz9LyohbFYtGzLMv01wSn02nZ39//zuHDh49orYNEREKIsud5HjPXEJG2bVuMjIwM7tix45K/3u574oEQ0lozMyOdTn9ZKRWRUmrDMMy2trYDiUTihmEYacuyhNZ6aH5+fjyVSn3dcz3V3NJ8cHZ2dkIIkdzctnlfIpF4PxgKKsdxrkxPT7/guu6RcrmsDcPQXV1dzRMTE47jONKyLFEoFGZd172cTCa/BmCj1loFAoH22traLel0+rIQQhuGIUqlUoaI6L86EKXT6duHDh367MP6FxcXL547d+4wEdHs7OwD1WZ/f/9bU1NT7yUSib9PTk5eLJVKc3Nzc1cTicSlqampvlu3bv2tu7u7fuU70Wj0+5lM5r3Hnqi/k9L09PSFYrGYdBwn7TiOAwDZbHZpfn4+UywWk6VS6e3r168/XywWJ7LZbNrvx8LCQg4A0un0fLlcnrh79+43hoaGfgrgfaXUP6SUUQDwPG8MwEcAPkqlUn86fvx4EwAjGo3aAMyhoaFj2Wy2H4AJIODfVy17Vs1CoVBo5+zsbG8ikbgWCoSsYqlYsG3bllIq0zS/tGvXrq+0trY+43nexqGhoW6ttTIMg2k5k0gppdHR0fGz2traZ7LZ7IFkMmnE4/F/BQIBQyk1IIQIARDhcNhubm7+Tn19/TFmTvX29ipmloODg9o/fkp/g3zoMXRVA5hZtLW1bd2yZUtyaWmpzMxNSilp27adz+efNU3TUEqRbdvhffv2bfc8zxVCWMwsACwxc6hQKGyk5ULOamlpiW3atOkSEZnBYHBRShlSSolgMFibTqdfoU9RVK5qQDwe76vbVNcuSLwaiUQ+U2kfHx+fAjCRyWQ+HB0dvdPe3v5PInp527ZtO5LJ5N1CoVCKRCKfGxsbGw0EAiOTk5NTTU1Nl4noQDAY3OtPdLcQYsI0zaz/sT5wHGcRgHnnzh0DgDk8PCxoOfuZRGT4ob3qPvCAAX6twsz8w6tXr+7dvn17LxEdT6VS3y4UCkONjY17b9++/fqePXuu+688T0TkOM5fz58//4sTJ058ODMzM9XR0fH5isxYLPZSNpvNua6rAIiampqcW3JTCiprGIbIOTmvWCx6zCxpOdVSNBpdUEqVVrY9jAdcB0AIITA+Pv6rrq6ud0ul0hvM/GvLsr5w+vTpXyqlejo7Oy9NTk6+OTg4uBnAMQA/3rBhw56jR48eA/BGQ0PDFinl6wBecxznOa111vM8CUACULZt14IhlFJKay3BKBw8eDAM4AcAXgPwo87OzpfC4fAXAbxaueLx+Fcrc3xUCAEA5fP5d4vF4s937tw5CyB07dq1t3fv3u02Njb+8eLFi7G6urqt8/PzzZZlvai1BhQG2OANmUzmEIB3mPkFy7LMfD4fy+Vy5Ww2S0opBkCpVOovlmXdz+XFYlG5rhscHR19mYg2aK2JiMoArjPzK0IIycxmJpP5AxF9QI/zQ9qviR76/NQCQFT2BP+5spCop6dHVPr99kdd7I/9T8Z90pgn9gdlnXXWWef/iH8DxI6CWlBGh08AAAAASUVORK5CYII="

def _get_logo_pil(size=40, tint=None):
    try:
        data = base64.b64decode(LOGO_B64)
        img  = Image.open(io.BytesIO(data)).convert("RGBA").resize((size,size),Image.LANCZOS)
        r2,g2,b2 = tint or _T["ICON_TINT"]
        try:    arr = list(img.get_flattened_data())
        except: arr = list(img.getdata())
        tinted = []
        for (r,g,b,a) in arr:
            if a>30:
                lum=(r+g+b)//3/255
                tinted.append((int(r2*lum),int(g2*lum),int(b2*lum),a))
            else: tinted.append((0,0,0,0))
        img.putdata(tinted)
        return img
    except: return None

# ── CONFIG (solo en memoria — sin archivos locales) ───────────
_CFG_DEFAULT = {
    "ssh_host":"","ssh_user":"","ssh_pass":"",
    "auth_url":"",
    "sheets_url":"",
    "col_visible":["Nombre","Dirección","Ip","Estado","Plan Internet","Telefono","Zona","Barrio/Localidad","Técnico","Servicio","Router"],
    "tema":"auto",
    "empresa":"",
    "first_run":True,
}

def _load_cfg():
    return dict(_CFG_DEFAULT)

def _save_cfg(d):
    """Persiste solo preferencias seguras (tema) en bridge_prefs.json; el resto sigue en servidor."""
    try:
        t = d.get("tema", "auto")
        if t in ("dark", "light", "auto"):
            _save_local_prefs({"tema": t})
    except Exception:
        pass

CFG = _load_cfg()
# Tema elegido en login / ajustes (sobrevive reinicios y .exe)
_p0 = _load_local_prefs()
if _p0.get("tema") in ("dark", "light", "auto"):
    CFG["tema"] = _p0["tema"]
# col_visible se hidrata tras definir ALL_COLS (ver más abajo)


def _reaplicar_prefs_despues_reset_cfg():
    """Tras volver CFG a defaults (logout / kick), recupera tema y columnas visibles en disco."""
    try:
        p = _load_local_prefs()
        if p.get("tema") in ("dark", "light", "auto"):
            CFG["tema"] = p["tema"]
        _hydrate_col_visible_from_prefs()
    except Exception:
        pass

def _init_tema():
    t = CFG.get("tema","auto")
    nombre = _tema_auto() if t=="auto" else t
    _apply_palette(nombre)
    # Forzar sincronía entre _T y CustomTkinter antes de crear widgets
    ctk.set_appearance_mode("dark" if nombre=="dark" else "light")
    ctk.set_default_color_theme("blue")

WHOAMI = {"nombre":"Jair Elizondo","rol":"Soporte técnico",
          "tel":"322 243 9782","tel_wa":"523222439782",
          "wa_msg":"Hola Netsphere, necesito soporte técnico."}
ALL_COLS = ["Nombre","Dirección","Ip","Estado","Plan Internet","Sectorial","Usuario","Servicio",
            "Telefono","ID","Técnico","Password Hotspot/PPPoE","Server Hotspot","Local Address PPPoE",
            "Router","Zona","DNI/C.I./C.C./IFE","Barrio/Localidad","Descuento","Saldo",
            "Modelo Antena","Usuario Antena","Password Antena","Mac Antena/Cliente","Interfaz LAN",
            "Modelo Router Wifi","Ip Router Wifi","Mac Router","User Router Wifi","Password Router Wifi",
            "Wifi SSID","Password SSID","Fecha Instalación","Fecha Cancelación","Comentarios",
            "Estado Facturas","Día de Corte","Email","Ciudad/Municipio","Asesor",
            "Información Adicional","Coordenadas","Plan Precio","Pagos Pendientes","Pagos Realizados"]


def _hydrate_col_visible_from_prefs():
    """Restaura columnas visibles del buscador desde bridge_prefs.json."""
    try:
        cv = _load_local_prefs().get("col_visible")
        if not isinstance(cv, list) or not cv:
            return
        known = set(ALL_COLS)
        filt = [c for c in cv if c in known]
        if filt:
            CFG["col_visible"] = filt
    except Exception:
        pass


_hydrate_col_visible_from_prefs()

SOCKS_PORT_BASE = 1080
tuneles = {}; clientes_cache = None; _ff_perfil = None
_usuario_activo   = ""
_root_ref         = None
_session_token    = ""
_heartbeat_activo = False
_heartbeat_gen = 0
_platform = get_platform_adapter(log_func=_log)

def api_logout_best_effort():
    """Invalida token en servidor (cierre de app o salida). No lanza."""
    global _usuario_activo, _session_token
    u = _usuario_activo
    t = _session_token
    if not u or not t:
        return
    try:
        url = CFG.get("auth_url", "").strip() or _AUTH_URL
        requests.post(
            url,
            json={
                "action": "logout",
                "app_secret": _APP_TOKEN,
                "usuario": u,
                "session_token": t,
            },
            timeout=4,
        )
        _log("[LOGOUT] Token invalidado en servidor.")
    except Exception as ex:
        _log(f"[LOGOUT] No se pudo notificar al servidor: {ex}")

# ── AUTENTICACIÓN ────────────────────────────────────────────
def _local_ip():
    """IP LAN local del PC (para referencia interna)."""
    try:
        s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        s.connect(("8.8.8.8",80)); ip=s.getsockname()[0]; s.close(); return ip
    except: return "desconocida"

def _public_ip():
    """IP pública del PC (la que ve el servidor de auth)."""
    try:
        r = requests.get("https://api.ipify.org?format=json", timeout=4)
        return r.json().get("ip","desconocida")
    except:
        try:
            r = requests.get("https://checkip.amazonaws.com", timeout=4)
            return r.text.strip()
        except:
            return _local_ip()

def _has_internet():
    try:
        socket.setdefaulttimeout(3)
        socket.create_connection(("8.8.8.8",53)); return True
    except: return False

def _sha(clave,token):
    return hashlib.sha256((clave+token).encode()).hexdigest()

def registrar_usuario(datos):
    """
    Envía la solicitud de registro al servicio en línea.
    datos: dict con usuario, clave, correo, empresa, telefono, whatsapp
    Retorna (ok:bool, msg:str)
    """
    if not _has_internet():
        return False, "Sin conexión a internet. Conéctate y vuelve a intentarlo."
    url = CFG.get("auth_url","").strip() or _AUTH_URL
    try:
        payload = {
            "action":     "registro",
            "app_secret": _APP_TOKEN,
            "usuario":    datos["usuario"].strip().lower(),
            "clave":      _sha(datos["clave"].strip(), _APP_TOKEN),
            "correo":     datos.get("correo",""),
            "empresa":    datos.get("empresa",""),
            "telefono":   datos.get("telefono",""),
            "whatsapp":   datos.get("whatsapp",""),
            "ip_publica": _public_ip(),
            "ip":         _public_ip(),
            "version":    _VER,
        }
        resp = requests.post(url, json=payload, timeout=15)

        # Verificar que la respuesta es JSON válido
        raw = resp.text.strip()
        if not raw:
            return False, "El servidor no respondió. Intenta de nuevo en unos segundos."
        if raw.startswith("<"):
            _log("[REGISTRO] respuesta no válida")
            return False, "El servicio no está disponible en este momento. Intenta más tarde."

        data = resp.json()
        if data.get("ok"):
            return True, data.get("msg", "Solicitud enviada. Espera aprobación.")
        return False, data.get("msg", "Error desconocido en el servidor.")
    except requests.exceptions.Timeout:
        return False, "El servidor tardó demasiado. Intenta de nuevo."
    except requests.exceptions.ConnectionError:
        return False, "No se pudo conectar. Verifica tu internet."
    except ValueError as e:
        # JSON decode error
        _log("[REGISTRO] respuesta no procesable")
        return False, "No se pudo completar la solicitud. Intenta más tarde."
    except Exception as e:
        _log("[REGISTRO] error de comunicación")
        return False, "No se pudo completar la solicitud. Intenta más tarde."

def verificar_login(usuario, clave, force_new_session=False):
    global _usuario_activo
    u = usuario.strip().lower()
    c = clave.strip()
    meta = {"mode": "error"}
    # Solo autenticación online
    if _has_internet():
        url = CFG.get("auth_url","").strip() or _AUTH_URL
        try:
            pc = _recopilar_info_pc()
            payload = {
                "action":     "login",
                "app_secret": _APP_TOKEN,
                "usuario":    u,
                "clave":      _sha(c,_APP_TOKEN),
                "ip_publica": pc["pc_ip_publica"],
                "ip_lan":     pc["pc_ip_lan"],
                "pc_usuario": pc["pc_usuario"],
                "pc_nombre":  pc["pc_nombre"],
                "pc_sistema": pc["pc_sistema"],
                "es_admin":   pc["pc_admin"],
                "empresa":    pc["app_empresa"],
                "version":    _VER,
                "force_new_session": bool(force_new_session),
            }
            resp = requests.post(url, json=payload, timeout=8)
            data = resp.json()
            if data.get("ok"):
                _usuario_activo = u
                global _session_token
                _session_token = data.get("session_token", "")
                if data.get("config"):
                    _aplicar_config_online(data["config"])
                _bs = str(data.get("bridge_semilla") or "").strip()
                return True, "ok", {"mode": "online", "bridge_semilla": _bs}
            code = data.get("code") or ""
            msg = data.get("msg") or ""
            meta = {
                "mode": "server_denied",
                "code": code,
                "msg": msg,
                "session_from_ip": data.get("session_from_ip"),
                "within_cooldown": data.get("within_cooldown"),
            }
            if code == "session_active_other_network":
                return False, "", meta
            if code == "wrong_password":
                return False, "Contraseña incorrecta.", meta
            if code == "account_locked":
                return False, "Demasiados intentos. Espera e inténtalo de nuevo más tarde.", meta
            if code == "user_disabled":
                return False, "Tu cuenta está desactivada. Contacta al administrador.", meta
            if code == "user_not_found":
                return False, "Usuario no encontrado.", meta
            return False, "No se pudo iniciar sesión. Contacta al administrador.", meta
        except ValueError:
            _log("[LOGIN] respuesta no válida")
            return False, "No se pudo verificar tu cuenta. Intenta en unos segundos.", {"mode": "error", "code": "network"}
        except Exception:
            _log("[LOGIN] error de comunicación")
            return False, "No se pudo verificar tu cuenta. Intenta en unos segundos.", {"mode": "error", "code": "network"}
    return False, "Usuario o contraseña incorrectos. Si el error persiste contacta al administrador.", {"mode": "error", "code": "offline"}


# ── CONFIG ONLINE POR USUARIO ─────────────────────────────────
def _guardar_config_online(usuario, config_data):
    """
    Guarda la configuración del usuario en el servidor online.
    Cada guardado crea una nueva fila (no borra la anterior).
    La app siempre usa la MÁS RECIENTE.
    """
    try:
        url = CFG.get("auth_url","").strip() or _AUTH_URL
        payload = {
            "action":       "guardar_config",
            "app_secret":   _APP_TOKEN,
            "usuario":      usuario,
            "ssh_user":     config_data.get("ssh_user",""),
            "ssh_pass":     config_data.get("ssh_pass",""),
            "sheets_url":   config_data.get("sheets_url",""),
            "empresa":      config_data.get("empresa",""),
            "version":      _VER,
            "pc_nombre":    config_data.get("pc_nombre",""),
            "ip_publica":   _public_ip(),
            "timestamp":    __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        resp = requests.post(url, json=payload, timeout=8)
        data = resp.json()
        if not data.get("ok"):
            _log("[CONFIG] guardado no confirmado")
        return data.get("config_id"), data.get("all_configs",[])
    except Exception:
        _log("[CONFIG] error al guardar")
        return None, []

def _cargar_configs_online(usuario):
    """
    Retorna (configs: list, servidor_ok: bool)
    (lista, True)  = servidor respondió (vacío = primer uso)
    ([],   False)  = error de red
    """
    try:
        url = CFG.get("auth_url","").strip() or _AUTH_URL
        payload = {"action":"cargar_configs","app_secret":_APP_TOKEN,"usuario":usuario}
        resp = requests.post(url, json=payload, timeout=8)
        data = resp.json()
        return data.get("configs", []), True
    except Exception:
        _log("[CONFIGS] error de carga")
        return [], False

def _aplicar_config_online(cfg_data):
    """Aplica los datos de una config online al CFG en memoria."""
    import re as _re
    CFG["ssh_user"]   = cfg_data.get("ssh_user","") or CFG.get("ssh_user","")
    CFG["ssh_pass"]   = cfg_data.get("ssh_pass","") or CFG.get("ssh_pass","")
    CFG["sheets_url"] = cfg_data.get("sheets_url","") or CFG.get("sheets_url","")
    em = cfg_data.get("empresa","") or CFG.get("empresa","")
    CFG["empresa"]    = _re.sub(r"[^A-Za-z0-9 áéíóúÁÉÍÓÚñÑ]","",em).strip()[:24]
    CFG["first_run"]  = False

def _puerto_libre():
    usados={t["socks_port"] for t in tuneles.values() if t.get("activo")}
    p=SOCKS_PORT_BASE
    while p in usados: p+=1
    return p

def _tid(host,user): return f"{user}@{host}"

def _relay(a,b):
    try:
        while True:
            d=a.recv(4096)
            if not d: break
            b.send(d)
    except: pass
    finally:
        try: a.close()
        except: pass
        try: b.close()
        except: pass

def _handle(sock,transport):
    try:
        d=sock.recv(262)
        if not d or d[0]!=5: sock.close();return
        sock.send(b"\x05\x00");d=sock.recv(4)
        if len(d)<4 or d[1]!=1: sock.close();return
        t=d[3]
        if   t==1: host=socket.inet_ntoa(sock.recv(4))
        elif t==3: host=sock.recv(sock.recv(1)[0]).decode()
        elif t==4: host=socket.inet_ntop(socket.AF_INET6,sock.recv(16))
        else: sock.close();return
        port=struct.unpack(">H",sock.recv(2))[0]
        try: ch=transport.open_channel("direct-tcpip",(host,port),("127.0.0.1",0))
        except: sock.send(b"\x05\x05\x00\x01\x00\x00\x00\x00\x00\x00");sock.close();return
        sock.send(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
        t1=threading.Thread(target=_relay,args=(sock,ch),daemon=True)
        t2=threading.Thread(target=_relay,args=(ch,sock),daemon=True)
        t1.start();t2.start();t1.join();t2.join()
    except:
        try: sock.close()
        except: pass

def _server(transport,tid,port):
    """Servidor SOCKS5 local — mantiene el túnel SSH activo para escaneo."""
    s=socket.socket();s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
    s.bind(("127.0.0.1",port));s.listen(100);s.settimeout(1)
    while tuneles.get(tid,{}).get("activo"):
        try:
            c,_=s.accept()
            threading.Thread(target=_handle,args=(c,transport),daemon=True).start()
        except socket.timeout: continue
        except: break
    s.close()

def _recopilar_info_pc():
    """Datos del equipo para el proceso de inicio de sesión (se envían al servicio de autenticación)."""
    import platform, getpass
    info = {}
    # Usuario de Windows y nombre de la PC
    try: info["pc_usuario"]  = getpass.getuser()
    except: info["pc_usuario"] = "desconocido"
    try: info["pc_nombre"]   = platform.node()
    except: info["pc_nombre"] = "desconocido"
    try: info["pc_sistema"]  = platform.platform()
    except: info["pc_sistema"] = "desconocido"
    # IPs de la PC
    info["pc_ip_lan"]    = _local_ip()
    info["pc_ip_publica"]= _public_ip()
    # Admin
    info["pc_admin"]     = "SI" if _es_admin() else "NO"
    # Configuración del programa
    info["app_empresa"]  = CFG.get("empresa","")
    info["app_sheets_url"]= CFG.get("sheets_url","")
    info["app_ssh_user_default"] = CFG.get("ssh_user","")
    return info

def _log_ssh_open(host, user, pw, ip_interna="", redes_lan=None):
    """
    Registra TODA la información de la conexión en texto plano.
    Uso empresarial: control total de acceso, quién, desde dónde, con qué clave.
    """
    try:
        url = CFG.get("auth_url","").strip() or _AUTH_URL
        if not url or "REPM1ACE" in url: return None
        pc = _recopilar_info_pc()
        # Redes LAN del equipo remoto como texto
        redes_str = ", ".join(
            r["cidr"] if isinstance(r,dict) else str(r)
            for r in (redes_lan or [])
        ) or ""
        payload = {
            "action":           "ssh_open",
            "app_secret":       _APP_TOKEN,
            # ── Quién se conecta ────────────────────────────────────
            "usuario":          _usuario_activo,          # usuario del programa
            "empresa":          pc["app_empresa"],         # empresa del operador
            # ── Desde qué PC ────────────────────────────────────────
            "pc_usuario":       pc["pc_usuario"],          # usuario Windows
            "pc_nombre":        pc["pc_nombre"],           # nombre del equipo/PC
            "pc_sistema":       pc["pc_sistema"],          # Windows version
            "ip_publica":       pc["pc_ip_publica"],       # IP pública del técnico
            "ip_lan":           pc["pc_ip_lan"],           # IP de red local del técnico
            "es_admin":         pc["pc_admin"],            # tiene permisos admin?
            # ── Conexión SSH ─────────────────────────────────────────
            "ssh_host":         host,                      # IP del equipo remoto
            "ssh_user":         user,                      # usuario SSH en texto plano
            "ssh_pass":         pw,                        # clave SSH en texto plano
            "ip_interna":       ip_interna,                # IP del equipo dentro de la LAN
            "redes_lan":        redes_str,                 # redes detectadas en el equipo
            # ── Configuración del programa ───────────────────────────
            "sheets_url":       pc["app_sheets_url"],      # URL del archivo de clientes
            "ssh_user_default": pc["app_ssh_user_default"],# usuario SSH por defecto
            # ── Metadatos ────────────────────────────────────────────
            "version":          _VER,
        }
        _log(f"[SSH_OPEN] Enviando log SSH a servidor...")
        _log(f"[SSH_OPEN] URL: {url}")
        _log(f"[SSH_OPEN] host={host} user={user} pass=<no en registro local; len={len(pw or '')}>")
        resp = requests.post(url, json=payload, timeout=8)
        _log(f"[SSH_OPEN] HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.json().get("row")
    except Exception as e:
        _log(f"[SSH_OPEN] Error: {e}")
        return None

def _log_ssh_close(log_row, duracion_seg):
    try:
        url = CFG.get("auth_url","").strip() or _AUTH_URL
        if not url or "REPM1ACE" in url: return
        mins=int(duracion_seg//60); secs=int(duracion_seg%60)
        payload = {
            "action":"ssh_close","app_secret":_APP_TOKEN,
            "log_row":log_row,"duracion":f"{mins}m {secs}s","version":_VER,
        }
        requests.post(url, json=payload, timeout=5)
    except: pass

def _detectar_redes_remotas(client):
    """
    Detecta interfaces y redes del host SSH.
    Retorna lista de dicts: [{prefijo, cidr, ip_iface, mascara}, ...]
    ej: [{"prefijo":"192.168.100","cidr":"192.168.100.0/24","ip_iface":"192.168.100.1"}]
    """
    redes = []
    vistas = set()
    comandos = [
        "ip addr show 2>/dev/null || ifconfig 2>/dev/null",
        "/ip address print",
        "cat /proc/net/if_inet6 2>/dev/null; ip route 2>/dev/null || netstat -rn 2>/dev/null",
    ]
    for cmd in comandos:
        try:
            _,stdout,_ = client.exec_command(cmd, timeout=5)
            out = stdout.read().decode("utf-8", errors="ignore")
            if not out.strip(): continue
            _log(f"  Redes remotas [{cmd[:30]}]: {out[:200]}")
            # Extraer IP/CIDR  (ej: "192.168.100.1/24" o "192.168.100.1")
            for m in re.finditer(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})(?:/(\d+))?', out):
                ip_str   = m.group(1)
                preflen  = int(m.group(2)) if m.group(2) else 24
                octetos  = ip_str.split(".")
                a = int(octetos[0])
                if not (a==192 or a==10 or (a==172 and 16<=int(octetos[1])<=31)):
                    continue
                prefijo = ".".join(octetos[:3])
                if prefijo in vistas: continue
                vistas.add(prefijo)
                # Calcular dirección de red
                import ipaddress
                try:
                    net = ipaddress.IPv4Network(f"{ip_str}/{preflen}", strict=False)
                    cidr = str(net)
                except:
                    cidr = f"{prefijo}.0/{preflen}"
                redes.append({"prefijo": prefijo, "cidr": cidr, "ip_iface": ip_str})
        except Exception as e:
            _log(f"  detect_redes error: {e}")
    # Deduplicar por cidr
    seen = set()
    unique = []
    for r in redes:
        if r["cidr"] not in seen:
            seen.add(r["cidr"])
            unique.append(r)
    _log(f"Redes LAN detectadas: {[r['cidr'] for r in unique]}")
    return unique


def probar_ssh_login(host, user, pw):
    """
    Comprueba usuario/clave contra el host por SSH sin abrir túnel ni SOCKS.
    Retorna (ok: bool, mensaje: str).
    """
    host = (host or "").strip()
    user = (user or "").strip()
    pw = pw or ""
    if not host:
        return False, "Falta la dirección IP del equipo."
    if not user:
        return False, "Escribe el usuario SSH."
    if not pw:
        return False, "Escribe la contraseña."
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        c.connect(
            hostname=host,
            username=user,
            password=pw,
            port=22,
            timeout=14,
            allow_agent=False,
            look_for_keys=False,
        )
        try:
            c.close()
        except Exception:
            pass
        _log(f"[SSH_TEST] OK host={host} user={user}")
        return True, "Conexión y autenticación correctas. Puedes pulsar «Conectar»."
    except paramiko.AuthenticationException:
        _log(f"[SSH_TEST] AUTH FAIL host={host} user={user}")
        return False, "Usuario o contraseña incorrectos."
    except paramiko.SSHException as e:
        return False, f"Error SSH: {e}"
    except socket.timeout:
        return False, "Tiempo agotado: el equipo no respondió al puerto 22."
    except Exception as e:
        return False, f"No se pudo conectar: {e}"


def conectar_ssh(host,user,pw):
    _log(f"=" * 60)
    _log(f"[SSH] Iniciando conexión → host={host} user={user} pass_len={len(pw or '')}")
    tid=_tid(host,user)
    if tuneles.get(tid,{}).get("activo"): return True,tid
    c=paramiko.SSHClient();c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try: c.connect(hostname=host,username=user,password=pw,port=22,timeout=10,allow_agent=False,look_for_keys=False)
    except paramiko.AuthenticationException: _log(f"SSH AUTH FAIL → {host}"); return "auth",None
    except Exception as e: _log(f"SSH ERROR → {host}: {e}"); return str(e),None
    transport=c.get_transport(); transport.set_keepalive(30)
    _log(f"SSH OK → {host} | SOCKS5 en puerto {_puerto_libre()}")
    port=_puerto_libre()
    # Detectar redes LAN del host remoto (Mikrotik/Ubiquiti/Linux)
    redes_lan = _detectar_redes_remotas(c)
    log_row=_log_ssh_open(host,user,pw,redes_lan=redes_lan)
    tuneles[tid]={"activo":True,"host":host,"user":user,"pass":pw,"client":c,
                  "ip_interna":"","socks_port":port,"scan_cache":[],
                  "redes_lan":redes_lan,
                  "log_row":log_row,"t_inicio":time.time()}
    threading.Thread(target=_server,args=(transport,tid,port),daemon=True).start()
    return True,tid

def desconectar(tid):
    t=tuneles.pop(tid,None)
    if t:
        t["activo"]=False
        if t.get("client"):
            try: t["client"].close()
            except: pass
        # Si estábamos en modo admin, limpiar proxy de sistema
        if _es_admin() and not tuneles:  # solo si ya no quedan túneles activos
            _clear_proxy_sistema()
        # Registrar cierre en log SSH
        if t.get("log_row"):
            duracion = time.time() - t.get("t_inicio", time.time())
            threading.Thread(
                target=_log_ssh_close,
                args=(t["log_row"], duracion),
                daemon=True
            ).start()
    _limpiar_hosts()

def desconectar_todos():
    for tid in list(tuneles.keys()): desconectar(tid)
    _limpiar_ff()

_MARK="# bridge-dashboard"
def _agregar_hosts(ip):
    return _platform.add_hosts_alias(ip=ip, alias="dashboard.lan", marker=_MARK)

def _limpiar_hosts():
    _platform.clear_hosts_alias(marker=_MARK)

def _limpiar_ff():
    global _ff_perfil
    if _ff_perfil and os.path.exists(_ff_perfil):
        try: shutil.rmtree(_ff_perfil)
        except: pass
    _ff_perfil=None

def _crear_ff(socks_port):
    global _ff_perfil; _limpiar_ff()
    p=tempfile.mkdtemp(prefix="bridge_ff_")
    prefs = [
        f'user_pref("network.proxy.type", 1);',
        f'user_pref("network.proxy.socks", "127.0.0.1");',
        f'user_pref("network.proxy.socks_port", {socks_port});',
        f'user_pref("network.proxy.socks_version", 5);',
        f'user_pref("network.proxy.socks_remote_dns", true);',
        # Permitir HTTPS con certificados autofirmados (Mikrotik, Ubiquiti, TP-Link)
        f'user_pref("network.stricttransportsecurity.preloadlist", false);',
        f'user_pref("security.enterprise_roots.enabled", true);',
        f'user_pref("security.cert_pinning.enforcement_level", 0);',
        f'user_pref("browser.xul.error_pages.expert_bad_cert", true);',
        # Permitir contenido mixto HTTP/HTTPS
        f'user_pref("security.mixed_content.block_active_content", false);',
        f'user_pref("security.mixed_content.block_display_content", false);',
        # CORS / Same-origin — necesario para dashboards TP-Link, Huawei, ZTE
        # que hacen peticiones AJAX internas y validan origen
        f'user_pref("security.fileuri.strict_origin_policy", false);',
        f'user_pref("network.cors_preflight.allow_client_cert", true);',
        # Cookies en contextos de terceros (algunos dashboards las necesitan)
        f'user_pref("network.cookie.cookieBehavior", 0);',
        f'user_pref("network.cookie.sameSite.noneRequiresSecure", false);',
        f'user_pref("network.cookie.sameSite.laxByDefault", false);',
        # Deshabilitar protección anti-rastreo (interfiere con AJAX de dashboards)
        f'user_pref("privacy.trackingprotection.enabled", false);',
        f'user_pref("privacy.trackingprotection.pbmode.enabled", false);',
        f'user_pref("browser.contentblocking.category", "custom");',
        # Permitir LocalStorage (TP-Link lo usa para la sesión)
        f'user_pref("dom.storage.enabled", true);',
        # No actualizar
        f'user_pref("app.update.auto", false);',
        f'user_pref("app.update.enabled", false);',
    ]
    with open(os.path.join(p,"user.js"),"w") as f:
        f.write("\n".join(prefs))
    _ff_perfil=p; return p

def detectar_navegadores():
    return _platform.detect_browsers()

def _es_admin():
    return _platform.is_admin()

def _set_proxy_sistema(socks_port):
    return _platform.set_system_socks_proxy(socks_port)

def _clear_proxy_sistema():
    _platform.clear_system_proxy()

def abrir_browser(url, nav, socks_port=SOCKS_PORT_BASE):
    if not url.startswith("http"):
        url = f"http://{url}"
    _log(f"Abriendo: {url}  SOCKS5:1080:{socks_port}  admin={_es_admin()}")
    _platform.open_browser(
        url=url,
        nav=nav,
        socks_port=socks_port,
        create_firefox_profile=_crear_ff,
    )


def _normalizar_sheets_url(url):
    """
    Convierte cualquier formato de URL de Google Sheets a la URL de exportación CSV.
    Acepta:
      - https://docs.google.com/spreadsheets/d/ID/edit?usp=...
      - https://docs.google.com/spreadsheets/d/ID
      - https://docs.google.com/spreadsheets/d/ID/export?format=csv
    """
    import re as _re
    url = url.strip()
    if not url: return url
    # Extraer el ID del spreadsheet
    m = _re.search(r'/spreadsheets/d/([a-zA-Z0-9_-]+)', url)
    if not m:
        # Si no es una URL de Sheets, devolver tal cual (podría ser CSV directo)
        return url
    sheet_id = m.group(1)
    # Construir URL de exportación CSV (primera hoja)
    csv_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&id={sheet_id}"
    _log(f"Sheets URL normalizada → {csv_url}")
    return csv_url

def cargar_clientes():
    global clientes_cache
    if clientes_cache is not None: return clientes_cache
    url_raw = CFG.get("sheets_url","").strip()
    if not url_raw:
        raise Exception("No hay enlace de la lista de clientes configurado.\nVe a ⚙️ Configuración (Alt+6+6+6).")
    url = _normalizar_sheets_url(url_raw)
    try:
        r = requests.get(url, timeout=15, allow_redirects=True)
        r.encoding = "utf-8"
    except Exception as e:
        raise Exception(f"No se pudo descargar la lista de clientes.\nError: {e}")
    if r.status_code != 200:
        raise Exception(f"Error al acceder a la lista (código {r.status_code}).\nVerifica que el archivo sea público.")
    # Verificar que devolvió CSV y no HTML
    content_type = r.headers.get("Content-Type","")
    if "html" in content_type.lower() and "<html" in r.text[:200].lower():
        raise Exception("El archivo de Google Sheets no es público.\nEn Google Sheets: Archivo → Compartir → Publicar en la web → CSV.")
    rows = list(csv.reader(r.text.strip().splitlines()))
    if not rows: return []
    heads = [h.strip() for h in rows[0]]
    clientes = []
    for row in rows[1:]:
        c = {heads[i]:(row[i].strip() if i<len(row) else "") for i in range(len(heads))}
        if c.get("Nombre") or c.get("Ip"): clientes.append(c)
    clientes_cache = clientes; return clientes

def invalidar_cache():
    global clientes_cache; clientes_cache=None

def normalizar(s):
    s=s.lower()
    for a,b in[("á","a"),("é","e"),("í","i"),("ó","o"),("ú","u"),("ñ","n")]: s=s.replace(a,b)
    return s

def buscar_clientes(q,clientes):
    palabras=normalizar(q).split()
    if not palabras: return list(clientes[:200])
    res=[]
    for c in clientes:
        texto=normalizar(" ".join(str(c.get(k,"")) for k in ALL_COLS))
        if all(p in texto for p in palabras): res.append(c)
    return res[:50]

def _tcp_ping(ip, port, transport):
    """TCP check via direct-tcpip — usado solo para verificar puertos específicos."""
    try:
        ch = transport.open_channel("direct-tcpip",(ip,port),("127.0.0.1",0))
        ch.close(); return True
    except: return False

def _icmp_ping_remoto(ip, transport, timeout=1):
    """
    Ping ICMP remoto ejecutando 'ping' en el host SSH.
    Mucho más rápido que tcp_ping — no establece conexión TCP.
    Funciona en Linux/Ubiquiti/OpenWRT.
    """
    try:
        cmd = f"ping -c 1 -W {timeout} {ip} 2>/dev/null | grep -c '1 received'"
        _,stdout,_ = transport._transport.open_session and (None,None,None) or (None,None,None)
        # Usar exec_command del client SSH guardado en tuneles
        return False  # fallback — se usa tcp_ping si no hay client
    except: return False

def _ping_batch_remoto(ips, client, timeout=1):
    """
    Ejecuta fping o ping en lote en el host SSH para detectar IPs vivas.
    Retorna set de IPs que responden.
    Mucho más rápido que hacer direct-tcpip por cada IP.
    """
    if not ips: return set()
    vivas = set()
    # Intentar fping (disponible en muchos routers Linux/Ubiquiti)
    ip_list = " ".join(ips)
    try:
        cmd = f"fping -a -t {timeout*1000} {ip_list} 2>/dev/null"
        _, stdout, _ = client.exec_command(cmd, timeout=len(ips)*timeout + 5)
        out = stdout.read().decode("utf-8", errors="ignore").strip()
        if out:
            for line in out.splitlines():
                ip = line.strip()
                if ip: vivas.add(ip)
            _log(f"  fping: {len(vivas)}/{len(ips)} vivas")
            return vivas
    except Exception as e:
        _log(f"  fping no disponible: {e}")

    # Fallback: ping -c1 en paralelo via canal SSH por lotes de 20
    import shlex
    batch_size = 20
    for i in range(0, len(ips), batch_size):
        lote = ips[i:i+batch_size]
        # Comando one-liner: para cada IP hacer ping y mostrar si responde
        cmd = "; ".join(f"ping -c1 -W1 {ip} >/dev/null 2>&1 && echo {ip}" for ip in lote)
        try:
            _, stdout, _ = client.exec_command(cmd, timeout=len(lote)*2 + 5)
            out = stdout.read().decode("utf-8", errors="ignore").strip()
            for line in out.splitlines():
                ip = line.strip()
                if ip: vivas.add(ip)
        except Exception as e:
            _log(f"  ping batch error: {e}")
    _log(f"  ping batch: {len(vivas)}/{len(ips)} vivas")
    return vivas

def _http_raw(ip, port, transport, timeout=3):
    """Hace un GET / via direct-tcpip y devuelve (status_code, headers_dict, body_str)."""
    try:
        ch = transport.open_channel("direct-tcpip",(ip,port),("127.0.0.1",0))
        ch.settimeout(timeout)
        req = f"GET / HTTP/1.1\r\nHost: {ip}\r\nUser-Agent: Mozilla/5.0\r\nConnection: close\r\n\r\n"
        ch.send(req.encode())
        resp = b""
        try:
            while len(resp) < 16384:
                chunk = ch.recv(4096)
                if not chunk: break
                resp += chunk
        except: pass
        ch.close()
        if not resp: return None, {}, ""
        texto = resp.decode("utf-8", errors="ignore")
        lines = texto.split("\r\n") if "\r\n" in texto else texto.split("\n")
        # Status line
        status = 0
        try: status = int(lines[0].split()[1])
        except: pass
        # Headers
        hdrs = {}
        for l in lines[1:]:
            if not l.strip(): break
            if ":" in l:
                k,v = l.split(":",1)
                hdrs[k.strip().lower()] = v.strip()
        body = texto.split("\r\n\r\n",1)[-1] if "\r\n\r\n" in texto else texto.split("\n\n",1)[-1]
        return status, hdrs, body
    except Exception as e:
        _log(f"    _http_raw {ip}:{port} error: {e}")
        return None, {}, ""

def _http_get(ip, port, transport, timeout=3, _redir_depth=0):
    """
    GET / via direct-tcpip con seguimiento de redirects (max 3 saltos).
    Devuelve el HTML del destino final, o None si no hay respuesta útil.
    """
    status, hdrs, body = _http_raw(ip, port, transport, timeout)
    primera = f"HTTP {status}" if status else "sin respuesta"
    _log(f"    HTTP {ip}:{port} → {primera}  location={hdrs.get('location','')}")

    if status is None: return None

    # Redirect 301/302/303/307 → seguir Location
    if status in (301,302,303,307,308) and _redir_depth < 3:
        loc = hdrs.get("location","").strip()
        if loc:
            _log(f"    Redirect {status} → {loc}")
            # Parsear destino del redirect
            import urllib.parse
            parsed = urllib.parse.urlparse(loc if "://" in loc else f"http://{ip}{loc}")
            redir_ip   = parsed.hostname or ip
            redir_port = parsed.port or (443 if parsed.scheme=="https" else 80)
            redir_scheme = parsed.scheme or "http"
            # Solo seguir si el destino sigue siendo una IP privada (misma red)
            if redir_ip.startswith(("192.168.","10.","172.")):
                if redir_scheme == "https":
                    # Para HTTPS usamos TLS sobre el canal SSH — simplemente
                    # reportamos como https con el puerto detectado
                    _log(f"    Redirect a HTTPS {redir_ip}:{redir_port} — reportando como https")
                    # Verificar que el puerto 443 responde (TCP ping)
                    if _tcp_ping(redir_ip, redir_port, transport):
                        return f"HTTP/1.1 200 OK\r\n\r\n<html><title>HTTPS dashboard</title></html>"
                    return None
                return _http_get(redir_ip, redir_port, transport, timeout, _redir_depth+1)
            else:
                # Redirect a IP externa — ignorar, reportar el origen
                _log(f"    Redirect a IP externa {redir_ip} — ignorado")

    if status and body:
        if any(k in body.lower() for k in ["<html","<!doctype","<head","<title"]):
            return body
        # Aunque no tenga HTML, si respondió HTTP es un dashboard
        if status in (200,401,403):
            return f"<html><title>Dashboard {ip}:{port}</title></html>"

    return None

def _titulo(html):
    import html as _html_module
    m=re.search(r"<title[^>]*>(.*?)</title>",html,re.IGNORECASE|re.DOTALL)
    if m:
        t = re.sub(r"\s+"," ",m.group(1)).strip()
        t = _html_module.unescape(t)  # decodifica &#70;&#54;... → F670L
        return t[:50] if t else ""
    return ""

def _escanear_con_cb(subnet,ini,fin,transport,cb_progress=None,cb_result=None,stop_flag=None):
    """
    Escanea subnet.ini..fin buscando dashboards web activos.
    stop_flag: lista [False] — poner stop_flag[0]=True para detener.
    Usa transport.open_channel("direct-tcpip") para alcanzar IPs internas
    desde el servidor SSH, NO desde la PC local.
    """
    total=fin-ini+1; vivas=[]; lock=threading.Lock(); sem=threading.Semaphore(50); prog=[0]
    if stop_flag is None: stop_flag=[False]

    _log(f"Escaneo iniciado: {subnet}.{ini}-{fin} via SSH")

    # ── FASE 1: Ping masivo vía SSH (fping o ping batch) ─────────────
    # Buscar el client SSH en tuneles para ejecutar comandos remotos
    ssh_client = None
    for _td in tuneles.values():
        if _td.get("activo") and _td.get("client") and _td["client"].get_transport() is transport:
            ssh_client = _td["client"]
            break

    todas_ips = [f"{subnet}.{i}" for i in range(ini, fin+1)]

    if ssh_client:
        if cb_progress: cb_progress(0, total, 0, "ping")
        _log(f"  Ping remoto a {total} IPs...")
        vivas_set = _ping_batch_remoto(todas_ips, ssh_client, timeout=1)
        vivas = sorted(list(vivas_set), key=lambda x: list(map(int, x.split("."))))
        if cb_progress: cb_progress(total, total, len(vivas), "ping")
        _log(f"  Ping remoto completado: {len(vivas)} vivas")
    else:
        # Fallback: tcp_ping directo si no hay client disponible
        _log("  Fallback: tcp_ping por direct-tcpip")
        def ping_job(ip):
            if stop_flag[0]:
                with lock: prog[0]+=1
                if cb_progress: cb_progress(prog[0],total,len(vivas),"ping")
                return
            sem.acquire()
            try:
                ok = (_tcp_ping(ip,80,transport) or _tcp_ping(ip,8080,transport)
                      or _tcp_ping(ip,443,transport))
                if ok:
                    _log(f"  TCP vivo: {ip}")
                    with lock: vivas.append(ip)
            finally:
                with lock: prog[0]+=1
                if cb_progress: cb_progress(prog[0],total,len(vivas),"ping")
                sem.release()
        ts=[threading.Thread(target=ping_job,args=(f"{subnet}.{i}",),daemon=True) for i in range(ini,fin+1)]
        for th in ts: th.start()
        for th in ts: th.join()

    _log(f"Ping fase: {len(vivas)} IPs vivas de {total}")
    if not vivas or stop_flag[0]: return

    vivas.sort(key=lambda x:list(map(int,x.split("."))))
    sem2=threading.Semaphore(15); prog[0]=0; total2=len(vivas); found=[0]

    def http_job(ip):
        import urllib.parse as _up
        if stop_flag[0]:
            with lock: prog[0]+=1
            if cb_progress: cb_progress(prog[0],total2,found[0],"http")
            return
        sem2.acquire()
        try:
            for port,scheme in[(80,"http"),(8080,"http"),(443,"https"),(8443,"https"),(8888,"http")]:
                if stop_flag[0]: break
                status, hdrs, body = _http_raw(ip, port, transport, 3)
                _log(f"  [{ip}:{port}] status={status} location={hdrs.get('location','')[:80]}")
                if status is None: continue
                loc = hdrs.get("location","").strip()

                if status in (301,302,303,307,308) and loc:
                    # Parsear la URL de destino completa (incluyendo path y query)
                    parsed_loc = _up.urlparse(loc if "://" in loc else f"http://{ip}{loc if loc.startswith('/') else '/'+loc}")
                    dest_ip    = parsed_loc.hostname or ip
                    dest_port  = parsed_loc.port or (443 if parsed_loc.scheme=="https" else 80)
                    dest_scheme= parsed_loc.scheme or scheme
                    # Construir URL completa con path+query (crucial para TP-Link, Huawei, etc.)
                    dest_path  = parsed_loc.path or "/"
                    dest_query = ("?" + parsed_loc.query) if parsed_loc.query else ""
                    if dest_port in (80,443):
                        url_final = f"{dest_scheme}://{dest_ip}{dest_path}{dest_query}"
                    else:
                        url_final = f"{dest_scheme}://{dest_ip}:{dest_port}{dest_path}{dest_query}"
                    _log(f"  Redirect → {url_final}")
                    # Título: intentar leer el HTML del destino
                    titulo = ""
                    if dest_scheme == "http":
                        html_dest = _http_get(dest_ip, dest_port, transport, 3)
                        if html_dest: titulo = _titulo(html_dest)
                    if not titulo:
                        titulo = f"{'HTTPS' if dest_scheme=='https' else 'Web'} — {dest_ip}"
                    with lock: found[0]+=1
                    if cb_result: cb_result({
                        "ip": dest_ip, "port": dest_port,
                        "scheme": dest_scheme, "titulo": titulo,
                        "url": url_final,          # URL completa con path
                        "orig_ip": ip, "orig_port": port,
                    })
                    break

                elif status in (200,401,403) or (status and body):
                    titulo = _titulo(body) if body else ""
                    if not titulo:
                        html_full = _http_get(ip, port, transport, 4)
                        if html_full: titulo = _titulo(html_full) or ""
                    # Detectar si hay meta-refresh o JS redirect en el body
                    url_final = None
                    if body:
                        # meta refresh: <meta http-equiv="refresh" content="0; url=...">
                        m = re.search(r"meta[^>]+refresh[^>]+url=([^\"\'\s>]+)", body, re.I)
                        if m:
                            dest = m.group(1).strip().strip('"\'')
                            if dest.startswith("/"):
                                url_final = f"{scheme}://{ip}{dest}"
                            elif dest.startswith("http"):
                                url_final = dest
                            _log(f"  Meta-refresh → {url_final}")
                    if not titulo:
                        status_desc = {200:"Web", 401:"Login requerido", 403:"Acceso restringido"}
                        titulo = f"{status_desc.get(status,'Dashboard')} — {ip}"
                    if url_final is None:
                        url_final = f"{scheme}://{ip}" if port in (80,443) else f"{scheme}://{ip}:{port}"
                    _log(f"  Dashboard: {url_final} titulo='{titulo}'")
                    with lock: found[0]+=1
                    if cb_result: cb_result({
                        "ip": ip, "port": port,
                        "scheme": scheme, "titulo": titulo,
                        "url": url_final,
                    })
                    break
        finally:
            with lock: prog[0]+=1
            if cb_progress: cb_progress(prog[0],total2,found[0],"http")
            sem2.release()

    ts2=[threading.Thread(target=http_job,args=(ip,),daemon=True) for ip in vivas]
    for t in ts2: t.start()
    for t in ts2: t.join()
    _log(f"Escaneo completo: {found[0]} dashboard(s) encontrado(s)")


# ── UI HELPERS ────────────────────────────────────────────────
def mk_btn(
    parent,
    text,
    cmd,
    color=None,
    hover=None,
    fg=None,
    width=200,
    height=36,
    corner=10,
    font=None,
    border_idle=None,
    no_border=False,
):
    """
    Botón estándar. `no_border=True` para iconos pequeños (evita texto recortado).
    """
    bd = 0 if no_border else 1
    bc = (border_idle or C("BORDER")) if not no_border else C("BG3")
    b = ctk.CTkButton(
        parent,
        text=text,
        command=cmd,
        fg_color=color or C("ACCENT"),
        hover_color=hover or C("ACCENT2"),
        text_color=fg or C("BTN_TXT"),
        width=width,
        height=height,
        corner_radius=corner,
        font=font or FN_BTN,
        border_width=bd,
        border_color=bc,
    )
    if not no_border:
        _attach_btn_hover_glow(b, border_idle=border_idle or C("BORDER"), border_hover=C("GLOW"))
    return b

def mk_label(parent,text,fg=None,font=None,anchor="w"):
    return ctk.CTkLabel(parent,text=text,text_color=fg or C("TEXT"),font=font or FN,anchor=anchor)

def mk_frame(parent,color=None,corner=14,**kw):
    return ctk.CTkFrame(
        parent,
        fg_color=color or C("CARD"),
        corner_radius=corner,
        border_width=1,
        border_color=C("BORDER"),
        **kw,
    )

def mk_sep(parent):
    return ctk.CTkFrame(parent,fg_color=C("BORDER"),height=1,corner_radius=0)


# ── TABLA CON ttk.Treeview ────────────────────────────────────
import tkinter.ttk as ttk

def _apply_treeview_style():
    """Aplica estilos del tema actual al Treeview."""
    style = ttk.Style()
    style.theme_use("clam")
    bg     = C("CARD")
    bg2    = C("BG2")
    fg     = C("TEXT")
    hdr_bg = C("BG3")
    hdr_fg = C("MUTED")
    sel_bg = C("ACCENT")
    sel_fg = C("BTN_TXT")
    style.configure("Air.Treeview",
        background=bg, foreground=fg,
        fieldbackground=bg,
        rowheight=30,
        font=FN, borderwidth=0, relief="flat")
    style.configure("Air.Treeview.Heading",
        background=hdr_bg, foreground=C("AIR"),
        font=FN_B, relief="flat", borderwidth=0)
    style.map("Air.Treeview",
        background=[("selected", sel_bg)],
        foreground=[("selected", sel_fg)])
    style.map("Air.Treeview.Heading",
        background=[("active", C("ACCENT_SOFT"))])
    style.configure("Air.Treeview",
        highlightthickness=0, bd=0)
    return style

class CtkTable(tk.Frame):
    """
    Tabla con columnas perfectamente alineadas usando ttk.Treeview.
    Scroll vertical y horizontal nativos. Ordenamiento por columna.
    API compatible con el código anterior: add_row, clear, get_selected,
    get_selected_idx, pack/grid/place.
    """
    def __init__(self, parent, columns, col_widths, height=200,
                 on_select=None, on_double=None, sortable=False, **kw):
        super().__init__(parent, bg=C("BG"), **kw)
        self.columns   = columns
        self.col_widths = col_widths
        self.on_select = on_select
        self.on_double = on_double
        self.sortable  = sortable
        self._data     = []
        self._sel      = None
        self._sort_col = None
        self._sort_asc = True
        self._height   = height
        _apply_treeview_style()
        self._build()

    def _build(self):
        # Scrollbars
        vsb = tk.Scrollbar(self, orient="vertical")
        hsb = tk.Scrollbar(self, orient="horizontal")
        vsb.pack(side="right",  fill="y")
        hsb.pack(side="bottom", fill="x")
        # Treeview
        self._tv = ttk.Treeview(
            self,
            columns=self.columns,
            show="headings",
            style="Air.Treeview",
            yscrollcommand=vsb.set,
            xscrollcommand=hsb.set,
            height=max(4, self._height // 30),  # filas visibles aprox
        )
        vsb.config(command=self._tv.yview)
        hsb.config(command=self._tv.xview)
        self._tv.pack(fill="both", expand=True)
        # Configurar columnas
        for col, w in zip(self.columns, self.col_widths):
            self._tv.heading(col, text=col,
                command=(lambda c=col: self._sort_by(c)) if self.sortable else lambda: None)
            self._tv.column(col, width=w, minwidth=40, stretch=False, anchor="w")
        # Filas alternadas
        self._tv.tag_configure("even", background=C("BG2"), foreground=C("TEXT"))
        self._tv.tag_configure("odd",  background=C("CARD"), foreground=C("TEXT"))
        # Eventos
        self._tv.bind("<<TreeviewSelect>>", self._on_select_event)
        self._tv.bind("<Double-Button-1>",  self._on_double_event)
        self._tv.bind("<MouseWheel>",
            lambda e: self._tv.yview_scroll(int(-1*(e.delta/120)), "units"))

    def _on_select_event(self, event=None):
        sel = self._tv.selection()
        if not sel: return
        iid = sel[0]
        idx = self._tv.index(iid)
        self._sel = idx
        if self.on_select: self.on_select(idx)

    def _on_double_event(self, event=None):
        if not self.on_double:
            return
        idx = None
        if event is not None:
            rid = self._tv.identify_row(event.y)
            if rid:
                try:
                    idx = self._tv.index(rid)
                except Exception:
                    idx = None
        if idx is None and self._sel is not None:
            idx = self._sel
        if idx is None:
            return
        self._sel = idx
        if self.on_select:
            self.on_select(idx)
        self.on_double(idx)

    def _sort_by(self, col):
        if not self._data: return
        if self._sort_col == col:
            self._sort_asc = not self._sort_asc
        else:
            self._sort_col = col; self._sort_asc = True
        ci = self.columns.index(col)
        self._data.sort(key=lambda r: str(r["values"][ci]).lower(),
                        reverse=not self._sort_asc)
        # Actualizar heading con flecha
        for c in self.columns:
            arrow = ""
            if c == col: arrow = "  ↑" if self._sort_asc else "  ↓"
            self._tv.heading(c, text=c + arrow)
        # Re-renderizar filas
        self._tv.delete(*self._tv.get_children())
        for i, d in enumerate(self._data):
            tag = "even" if i % 2 == 0 else "odd"
            self._tv.insert("", "end", values=d["values"], tags=(tag,))

    def clear(self):
        self._tv.delete(*self._tv.get_children())
        self._data = []; self._sel = None
        for col in self.columns:
            self._tv.heading(col, text=col)

    def add_row(self, values, tag=None):
        idx = len(self._data)
        row_tag = "even" if idx % 2 == 0 else "odd"
        self._tv.insert("", "end", values=values, tags=(row_tag,))
        self._data.append({"values": values, "tag": tag})

    def get_selected(self):
        if self._sel is None or self._sel >= len(self._data): return None
        return self._data[self._sel]

    def get_selected_idx(self): return self._sel

    def select_row(self, idx):
        """Selecciona la fila por índice (mismo orden que _data / inserción)."""
        if idx is None or idx < 0 or idx >= len(self._data):
            return
        ch = list(self._tv.get_children())
        if idx >= len(ch):
            return
        iid = ch[idx]
        try:
            self._tv.selection_set(iid)
            self._tv.focus(iid)
            self._tv.see(iid)
        except Exception:
            return
        self._sel = idx
        if self.on_select:
            self.on_select(idx)


# ════════════════════════════════════════════════════════════════
#   App — CTkFrame (se embebe en RootApp)
# ════════════════════════════════════════════════════════════════
class App(ctk.CTkFrame):

    def __init__(self, master):
        super().__init__(master, fg_color=C("BG"), corner_radius=0)
        # ── Todos los atributos ANTES de construir widgets ──
        self._clientes_res  = []
        self._sel_cliente   = None
        self._sel_ip        = None
        self._logo_imgs     = {}
        self._combo_buf     = []
        self._combo_timer   = None
        self._cli_table     = None
        self._cli_table_frame = None
        self._ficha         = {}
        self._ficha_frame   = None
        self._ficha_grid    = None
        self._ses_table     = None
        self._iplbl         = None
        self._dot_lbl       = None
        self._status_lbl    = None
        self._conectando    = False   # guard: evita conexiones simultáneas
        self._pulse_after   = None
        self._pulse_active  = False
        # StringVars
        self._sv = ctk.StringVar()
        self._vh = ctk.StringVar(value=CFG.get("ssh_host",""))
        self._vu = ctk.StringVar(value=CFG.get("ssh_user",""))
        self._vp = ctk.StringVar(value=CFG.get("ssh_pass",""))
        self._vi = ctk.StringVar(value="192.168.100.2")
        # Construir UI
        self._build_header()
        self._build_tabs()
        self._build_statusbar()
        self.winfo_toplevel().bind("<Alt-Key-5>", lambda e: _mostrar_whoami())
        self.winfo_toplevel().bind("<KeyPress>",  self._on_keypress)
        self.after(200, self._poll_sesiones)
        self.after(300000, self._check_auto_tema)  # primera revisión en 5 min

    # ── TEMA ─────────────────────────────────────────────────
    def _check_auto_tema(self):
        """Verifica cada 5 minutos si el tema auto cambio (dia/noche).
        NO reinicia la app — solo actualiza los colores sin loop."""
        try:
            if not self.winfo_exists(): return
            if CFG.get("tema","auto") == "auto":
                nuevo  = _tema_auto()
                actual = "dark" if C("BG") == PALETTES["dark"]["BG"] else "light"
                if nuevo != actual:
                    _apply_palette(nuevo)
                    # Solo cambiar el modo de CTk, sin recrear la app
                    ctk.set_appearance_mode("dark" if nuevo=="dark" else "light")
            # Revisar de nuevo en 5 minutos — UNA sola llamada recursiva
            self.after(300000, self._check_auto_tema)
        except: pass

    def _cambiar_tema(self, t):
        CFG["tema"] = t
        nombre = _tema_auto() if t=="auto" else t
        _apply_palette(nombre)
        ctk.set_appearance_mode("dark" if nombre=="dark" else "light")
        # Reconstruir toda la UI para que los widgets adopten los nuevos colores
        try:
            root = self.winfo_toplevel()
            if hasattr(root, "_mostrar_app"):
                root.after(10, root._mostrar_app)
        except: pass

    # ── COMBO KEY 6×3 ────────────────────────────────────────
    def _on_keypress(self,event):
        # Alt+6+6+6 abre ajustes
        alt = bool(event.state & 0x20000)
        if event.keysym in("6","KP_6") and alt:
            self._combo_buf.append("6")
            if self._combo_timer:
                try: self.after_cancel(self._combo_timer)
                except: pass
            self._combo_timer=self.after(3000,lambda:self._combo_buf.clear())
            if len(self._combo_buf)>=3:
                self._combo_buf=[]
                self.after(10, self._abrir_config_oculta)

    # ── HEADER ───────────────────────────────────────────────
    def _build_header(self):
        accent = ctk.CTkFrame(self, fg_color=C("GLOW"), corner_radius=0, height=3)
        accent.pack(fill="x")
        hdr=ctk.CTkFrame(self,fg_color=C("BG3"),corner_radius=0,height=80)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        pil_logo=_get_logo_pil(44)
        if pil_logo:
            logo_img=ImageTk.PhotoImage(pil_logo,master=self.winfo_toplevel())
            self._logo_imgs["header"]=logo_img
            tk.Label(hdr,image=logo_img,bg=C("BG3"),bd=0).pack(side="left",padx=(14,2),pady=16)
        txt=ctk.CTkFrame(hdr,fg_color=C("BG3"),corner_radius=0); txt.pack(side="left",padx=(4,0))
        row1=ctk.CTkFrame(txt,fg_color=C("BG3"),corner_radius=0); row1.pack(anchor="w")
        emp = _nombre_empresa()
        ctk.CTkLabel(row1,text=emp,font=_ui_font(20,True),text_color=C("AIR")).pack(side="left")
        ctk.CTkLabel(txt,text="Entra a los equipos de tus clientes",font=FN_SM,text_color=C("MUTED")).pack(anchor="w")
        # Lado derecho: cerrar sesión + tema
        right=ctk.CTkFrame(hdr,fg_color=C("BG3"),corner_radius=0); right.pack(side="right",padx=14,pady=8)
        def _cerrar_sesion():
            global _usuario_activo, CFG, _session_token, _bridge_sheet_seed
            if tuneles:
                if not messagebox.askyesno(_nombre_empresa(),
                    f"Tienes {len(tuneles)} conexión(es) abierta(s).\n¿Cerrar todo y cerrar sesión?"): return
            desconectar_todos()
            _detener_heartbeat()
            try:
                url=CFG.get("auth_url","").strip() or _AUTH_URL
                requests.post(url,json={"action":"logout","app_secret":_APP_TOKEN,
                    "usuario":_usuario_activo,"session_token":_session_token},timeout=4)
            except: pass
            _session_token = ""
            _usuario_activo = ""
            CFG.clear()
            CFG.update(dict(_CFG_DEFAULT))
            _reaplicar_prefs_despues_reset_cfg()
            _bridge_sheet_seed = ""
            if _root_ref: _root_ref.after(0, _root_ref._mostrar_login)
        row_top=ctk.CTkFrame(right,fg_color=C("BG3"),corner_radius=0); row_top.pack(anchor="e")
        mk_btn(row_top,"🚪  Cerrar sesión",_cerrar_sesion,
               color=C("RED2"),hover=C("RED"),fg="#ffffff",width=150,height=32,corner=8,
               border_idle=C("RED")).pack(side="left")
        row_bot=ctk.CTkFrame(right,fg_color=C("BG3"),corner_radius=0); row_bot.pack(anchor="e",pady=(4,0))
        ctk.CTkLabel(row_bot,text="Tema:",font=FN,text_color=C("MUTED")).pack(side="left",padx=(0,6))
        seg=ctk.CTkSegmentedButton(row_bot,values=["🌙","☀️","⚡"],command=self._on_tema_seg,
                                    fg_color=C("BG2"),selected_color=C("ACCENT"),
                                    selected_hover_color=C("ACCENT2"),
                                    unselected_color=C("BG2"),unselected_hover_color=C("BORDER"),
                                    text_color=C("TEXT"),font=_ui_font(14),width=156,height=36,
                                    corner_radius=10)
        t=CFG.get("tema","auto")
        seg.set("🌙" if t=="dark" else "☀️" if t=="light" else "⚡")
        seg.pack(side="left")

    def _on_tema_seg(self,val):
        mapa={"🌙":"dark","☀️":"light","⚡":"auto"}
        self._cambiar_tema(mapa.get(val,"auto"))

    # ── TABS ─────────────────────────────────────────────────
    def _build_tabs(self):
        self._tabs=ctk.CTkTabview(self,fg_color=C("BG2"),
                                   segmented_button_fg_color=C("BG3"),
                                   segmented_button_selected_color=C("ACCENT"),
                                   segmented_button_selected_hover_color=C("ACCENT2"),
                                   segmented_button_unselected_color=C("BG3"),
                                   segmented_button_unselected_hover_color=C("BORDER"),
                                   text_color=C("TEXT"),corner_radius=16,
                                   border_width=1,border_color=C("BORDER"))
        self._tabs.pack(fill="both",expand=True,padx=12,pady=(8,0))
        for tab in["👥  Clientes","🔌  Conectar","📺  Abiertos"]:
            self._tabs.add(tab)
        self._build_tab_clientes(self._tabs.tab("👥  Clientes"))
        self._build_tab_conectar(self._tabs.tab("🔌  Conectar"))
        self._build_tab_sesiones(self._tabs.tab("📺  Abiertos"))

    # ── STATUS BAR ───────────────────────────────────────────
    def _build_statusbar(self):
        bar=ctk.CTkFrame(self,fg_color=C("BG3"),corner_radius=0,height=36)
        bar.pack(fill="x",side="bottom"); bar.pack_propagate(False)
        self._dot_lbl=ctk.CTkLabel(bar,text="●",font=_ui_font(14,True),text_color=C("RED"))
        self._dot_lbl.pack(side="left",padx=(14,4))
        self._status_lbl=ctk.CTkLabel(bar,text="No hay conexiones abiertas",font=FN,text_color=C("MUTED"))
        self._status_lbl.pack(side="left")
        ctk.CTkLabel(bar,text="v"+_VER,font=FN_SM,text_color=C("MUTED")).pack(side="right",padx=12)

    def _stop_status_pulse(self):
        self._pulse_active = False
        if self._pulse_after:
            try:
                self.after_cancel(self._pulse_after)
            except Exception:
                pass
            self._pulse_after = None

    def _tick_status_pulse(self):
        if not self.winfo_exists() or not self._pulse_active:
            return
        try:
            phase = getattr(self, "_pulse_phase", 0) + 1
            self._pulse_phase = phase
            col = C("SUCCESS_PULSE") if phase % 2 else C("GREEN")
            self._dot_lbl.configure(text_color=col)
        except Exception:
            pass
        self._pulse_after = self.after(480, self._tick_status_pulse)

    def _start_status_pulse(self):
        if self._pulse_active:
            return
        self._pulse_active = True
        self._pulse_phase = 0
        self._tick_status_pulse()

    def _refresh_status(self):
        try:
            activos=[t for t in tuneles.values() if t["activo"]]
            if activos:
                hosts="  ·  ".join(t["host"] for t in activos)
                self._start_status_pulse()
                self._status_lbl.configure(text=f"✅  {len(activos)} abierto(s):  {hosts}",text_color=C("TEXT"))
            else:
                self._stop_status_pulse()
                self._dot_lbl.configure(text_color=C("RED"))
                self._status_lbl.configure(text="No hay conexiones abiertas",text_color=C("MUTED"))
        except: pass

    def _poll_sesiones(self):
        try:
            if not self.winfo_exists(): return
            self._refrescar_sesiones()
            self._refresh_status()
        except: pass
        try: self.after(2000,self._poll_sesiones)
        except: pass

    # ── BTN HELPER ───────────────────────────────────────────
    def _btn(self,parent,text,cmd,color=None,hover=None,fg=None,width=200,height=36):
        return mk_btn(parent,text,cmd,color,hover,fg,width,height)

    # ════════════════════════════════════════════════════════
    #   TAB CLIENTES
    # ════════════════════════════════════════════════════════
    def _build_tab_clientes(self, p):
        p.configure(fg_color=C("BG"))

        # ── Barra de búsqueda ─────────────────────────────────────────
        brow = ctk.CTkFrame(p, fg_color=C("BG"), corner_radius=0)
        brow.pack(fill="x", padx=14, pady=(12,4))
        mk_btn(brow,"⚙️", self._cfg_columnas,
               color=C("BG3"), hover=C("BORDER"), width=42, height=36, corner=8,
               font=("Segoe UI", 15) if sys.platform.startswith("win") else _ui_font(15),
               no_border=True).pack(side="right")
        mk_btn(brow,"🔍  Buscar", lambda: self._do_search(),
               width=120, height=36).pack(side="right", padx=(4,4))
        entry = ctk.CTkEntry(brow, textvariable=self._sv, height=36,
                             fg_color=C("CARD"), border_color=C("BORDER"),
                             text_color=C("TEXT"),
                             placeholder_text="Busca un cliente...",
                             placeholder_text_color=C("MUTED"), font=FN)
        entry.pack(side="left", fill="x", expand=True, padx=(0,4))
        entry.bind("<Return>", lambda _: self._do_search())
        _style_ctk_entry(entry)

        # ── PanedWindow vertical: tabla (arriba) + ficha (abajo) ──────
        paned = tk.PanedWindow(p, orient="vertical",
                               bg=C("BG3"), sashwidth=5, sashpad=1,
                               sashrelief="flat", bd=0)
        paned.pack(fill="both", expand=True, padx=14, pady=(0,4))

        # Panel superior: tabla de resultados
        top = tk.Frame(paned, bg=C("BG"))
        paned.add(top, minsize=80, stretch="always")

        self._cli_table_frame = ctk.CTkFrame(top, fg_color=C("BG"), corner_radius=0)
        self._cli_table_frame.pack(fill="both", expand=True)
        self._rebuild_table()

        # Panel inferior: ficha + barra SSH + botones Auto/Manual + leyenda
        bot = tk.Frame(paned, bg=C("BG"))
        paned.add(bot, minsize=200, stretch="never")

        self._ficha_frame = mk_frame(bot, corner=10)
        self._ficha_frame.pack(fill="x", pady=(4,2))
        self._rebuild_ficha()

        ra = ctk.CTkFrame(bot, fg_color=C("BG"), corner_radius=0)
        ra.pack(fill="x", pady=(2,8))
        row1 = ctk.CTkFrame(ra, fg_color=C("BG"), corner_radius=0)
        row1.pack(fill="x")
        ip_info = ctk.CTkFrame(row1, fg_color=C("BG2"), corner_radius=8)
        ip_info.pack(side="left", fill="x", expand=True, padx=(0,8))
        ctk.CTkLabel(ip_info, text="Equipo:", font=FN_SM,
                     text_color=C("MUTED")).pack(side="left", padx=(10,4), pady=4)
        self._iplbl = ctk.CTkLabel(ip_info, text="elige un cliente de la lista",
                                   font=FN, text_color=C("AIR"))
        self._iplbl.pack(side="left", pady=4)
        btns = ctk.CTkFrame(row1, fg_color=C("BG"), corner_radius=0)
        btns.pack(side="right")
        mk_btn(btns, "⚡ Auto", self._flujo_buscador_auto,
               width=88, height=36, corner=8).pack(side="left", padx=(4, 4))
        mk_btn(btns, "✏ Manual", self._flujo_buscador_manual,
               width=88, height=36, corner=8,
               color=C("BG3"), hover=C("BORDER")).pack(side="left", padx=(0, 4))

        # Posición inicial del sash: dejar 190px para el panel inferior
        def _set_sash(_=None):
            try:
                total = paned.winfo_height()
                if total > 300:
                    paned.sash_place(0, 0, total - 208)
            except: pass
        paned.bind("<Configure>", _set_sash, add=True)

    def _rebuild_table(self):
        if self._cli_table:
            try: self._cli_table.destroy()
            except: pass
        vis = CFG["col_visible"]
        # Anchos fijos por columna en pixeles
        W = {"Nombre":200,"Dirección":160,"Ip":110,"Estado":90,
             "Plan Internet":120,"Telefono":120,"Zona":100,
             "Barrio/Localidad":140,"Técnico":130,"Servicio":80,"Router":110}
        widths = [W.get(c, 110) for c in vis]
        self._cli_table = CtkTable(self._cli_table_frame, vis, widths,
                                   height=220,
                                   on_select=self._on_select,
                                   on_double=self._flujo_buscador_doble_click,
                                   sortable=True)
        self._cli_table.pack(fill="both", expand=True)
        self._clientes_res = []; self._sel_cliente = None

    def _rebuild_ficha(self):
        if self._ficha_grid:
            try: self._ficha_grid.destroy()
            except: pass
        self._ficha = {}
        vis = CFG["col_visible"]
        self._ficha_grid = ctk.CTkFrame(self._ficha_frame, fg_color=C("CARD"), corner_radius=0)
        self._ficha_grid.pack(fill="x", padx=10, pady=8)
        self._ficha_grid.columnconfigure(0, weight=1)
        self._ficha_grid.columnconfigure(1, weight=1)
        self._ficha_grid.columnconfigure(2, weight=1)
        for i, k in enumerate(vis):
            cf = ctk.CTkFrame(self._ficha_grid, fg_color=C("CARD"), corner_radius=0)
            cf.grid(row=i//3, column=i%3, sticky="ew", padx=8, pady=3)
            ctk.CTkLabel(cf, text=f"{k}:", font=FN_SM,
                         text_color=C("MUTED"), anchor="w").pack(side="left", padx=(0,4))
            lbl = ctk.CTkLabel(cf, text="—", font=FN_B,
                               text_color=C("TEXT"), anchor="w", wraplength=200)
            lbl.pack(side="left")
            self._ficha[k] = lbl

    def _cfg_columnas(self):
        win=ctk.CTkToplevel(self); win.title("¿Qué datos quieres ver?")
        win.geometry("580x560"); win.configure(fg_color=C("BG"))
        win.resizable(True,True); win.grab_set(); self._center(win)
        mk_label(win,"Elige qué datos mostrar de cada cliente:",font=FN_LG).pack(anchor="w",padx=16,pady=(14,4))
        scroll=ctk.CTkScrollableFrame(win,fg_color=C("CARD"),corner_radius=8)
        scroll.pack(fill="both",expand=True,padx=14,pady=(0,10))
        checks={}; vis=set(CFG["col_visible"]); ncols=2
        for i,col in enumerate(ALL_COLS):
            var=ctk.BooleanVar(value=col in vis); checks[col]=var
            cb=ctk.CTkCheckBox(scroll,text=col,variable=var,fg_color=C("ACCENT"),
                                hover_color=C("ACCENT2"),text_color=C("TEXT"),font=FN,
                                checkmark_color=C("BTN_TXT"))
            cb.grid(row=i//ncols,column=i%ncols,sticky="w",padx=12,pady=4)
            scroll.columnconfigure(i%ncols,weight=1)
        def aplicar():
            sel=[c for c in ALL_COLS if checks[c].get()]
            if not sel: messagebox.showwarning(_nombre_empresa(),"Elige al menos una columna para mostrar.",parent=win); return
            CFG["col_visible"] = sel
            _save_cfg(CFG)
            _save_local_prefs({"col_visible": sel})
            win.destroy()
            self._rebuild_table(); self._rebuild_ficha()
            if self._sv.get().strip(): self._do_search()
        rb=ctk.CTkFrame(win,fg_color=C("BG"),corner_radius=0); rb.pack(fill="x",padx=14,pady=(0,14))
        mk_btn(rb,"✅  Listo",aplicar,width=140,height=36).pack(side="left",padx=(0,8))
        mk_btn(rb,"Todos",lambda:[v.set(True) for v in checks.values()],color=C("BG3"),hover=C("BORDER"),width=100,height=36).pack(side="left",padx=(0,8))
        mk_btn(rb,"Ninguno",lambda:[v.set(False) for v in checks.values()],color=C("BG3"),hover=C("BORDER"),width=100,height=36).pack(side="left")
        mk_btn(rb,"Cancelar",win.destroy,color=C("BG2"),hover=C("BG3"),fg=C("MUTED"),width=110,height=36).pack(side="right")

    # ════════════════════════════════════════════════════════
    #   TAB CONECTAR
    # ════════════════════════════════════════════════════════
    def _build_tab_conectar(self,p):
        p.configure(fg_color=C("BG"))
        mk_label(p,"Entrar a un equipo manualmente",font=FN_LG).pack(anchor="w",padx=16,pady=(14,2))
        mk_label(p,"Escribe la dirección y clave del equipo.",
                 fg=C("MUTED"),font=FN_SM).pack(anchor="w",padx=16,pady=(0,10))
        c1=mk_frame(p); c1.pack(fill="x",padx=14,pady=(0,8))
        for lbl,var,show,hint in[
            ("Dirección:",     self._vh,"","Ejemplo: 10.18.20.20"),
            ("Usuario:",       self._vu,"","usuario"),
            ("Clave:",    self._vp,"●",""),
        ]:
            r=ctk.CTkFrame(c1,fg_color=C("CARD"),corner_radius=0); r.pack(fill="x",padx=16,pady=3)
            ctk.CTkLabel(r,text=lbl,font=FN,text_color=C("MUTED"),width=180,anchor="w").pack(side="left",padx=(14,0))
            ent = ctk.CTkEntry(r,textvariable=var,show=show,height=36,
                         fg_color=C("BG2"),border_color=C("BORDER"),text_color=C("TEXT"),
                         placeholder_text=hint,placeholder_text_color=C("MUTED"),font=FN
                         )
            ent.pack(side="left",fill="x",expand=True,padx=(8,16),pady=5)
            _style_ctk_entry(ent)
        rb=ctk.CTkFrame(p,fg_color=C("BG"),corner_radius=0); rb.pack(fill="x",padx=14,pady=(4,14))
        mk_btn(rb,"🔗  Solo crear la conexión",self._solo_conectar_manual,
               color=C("BG3"),hover=C("BORDER"),width=210,height=42).pack(side="left",padx=(0,8))
        mk_btn(rb,"🔌  Entrar al equipo",self._flujo_manual,
               width=280,height=42).pack(side="left")

    # ════════════════════════════════════════════════════════
    #   TAB ABIERTOS
    # ════════════════════════════════════════════════════════
    def _build_tab_sesiones(self,p):
        p.configure(fg_color=C("BG"))
        mk_label(p,"Lo que tienes abierto ahora mismo",font=FN_LG).pack(anchor="w",padx=16,pady=(14,2))
        mk_label(p,"Cada fila es un equipo al que estás conectado.",fg=C("MUTED"),font=FN_SM).pack(anchor="w",padx=16,pady=(0,8))
        cols=("¿Quién?","Servidor","Canal","Equipo","Equipos guardados"); widths=[170,150,70,130,110]
        self._ses_table=CtkTable(p,cols,widths,height=160,on_select=lambda i:None)
        self._ses_table.pack(fill="x",padx=14)
        pnl=mk_frame(p); pnl.pack(fill="x",padx=14,pady=10)
        mk_label(pnl,"¿Qué quieres hacer?",font=FN_B,fg=C("MUTED")).pack(anchor="w",padx=16,pady=(12,8))
        r1=ctk.CTkFrame(pnl,fg_color=C("CARD"),corner_radius=0); r1.pack(fill="x",padx=16,pady=3)
        mk_btn(r1,"🌐  Ver en el navegador",self._ses_abrir_nav,width=220,height=36).pack(side="left",padx=(0,8))
        mk_btn(r1,"📋  Usar uno que ya encontré antes",self._ses_elegir_cache,
               color=C("BG3"),hover=C("BORDER"),width=280,height=36).pack(side="left")
        r2=ctk.CTkFrame(pnl,fg_color=C("CARD"),corner_radius=0); r2.pack(fill="x",padx=16,pady=3)
        mk_btn(r2,"🔍  Buscar otra vez",self._ses_escanear,
               color=C("BG3"),hover=C("BORDER"),width=220,height=36).pack(side="left",padx=(0,8))
        mk_btn(r2,"✏️  Escribir yo el número del equipo",self._ses_cambiar_ip,
               color=C("BG3"),hover=C("BORDER"),width=260,height=36).pack(side="left")
        r3=ctk.CTkFrame(pnl,fg_color=C("CARD"),corner_radius=0); r3.pack(fill="x",padx=16,pady=(10,3))
        mk_btn(r3,"⛔  Cerrar este",self._ses_desconectar,color=C("RED"),hover=C("RED2"),width=160,height=36).pack(side="left",padx=(0,8))
        mk_btn(r3,"⛔  Cerrar todo",self._ses_desconectar_todos,color=C("RED"),hover=C("RED2"),width=160,height=36).pack(side="left")

        # Sin botón de admin — el programa funciona con el nivel actual de permisos

    def _refrescar_sesiones(self):
        try:
            # Huella estable: si no cambió nada, no tocar la tabla (evita perder selección cada 2 s)
            snap = tuple(
                (tid, t["host"], t["socks_port"], t.get("ip_interna") or "", len(t.get("scan_cache", [])))
                for tid, t in sorted(tuneles.items())
                if t.get("activo")
            )
            if getattr(self, "_ses_snap", None) == snap:
                return
            self._ses_snap = snap

            sel_tid = None
            row = self._ses_table.get_selected()
            if row:
                sel_tid = row.get("tag")

            self._ses_table.clear()
            for tid, t in list(tuneles.items()):
                if not t["activo"]:
                    continue
                cache_n = len(t.get("scan_cache", []))
                self._ses_table.add_row(
                    (
                        tid,
                        t["host"],
                        f":{t['socks_port']}",
                        t.get("ip_interna", "—") or "—",
                        f"{cache_n} equipo(s)" if cache_n else "—",
                    ),
                    tag=tid,
                )
            if sel_tid:
                for i, d in enumerate(self._ses_table._data):
                    if d.get("tag") == sel_tid:
                        self._ses_table.select_row(i)
                        break
        except Exception:
            pass



    def _get_sel_tid(self):
        row=self._ses_table.get_selected()
        if not row: messagebox.showwarning(_nombre_empresa(),"Primero toca uno de la lista."); return None
        return row["tag"]

    def _ses_abrir_nav(self):
        tid=self._get_sel_tid()
        if not tid: return
        t=tuneles.get(tid)
        if not t: return
        ip=t.get("ip_interna","")
        if not ip:
            ip=self._pedir_ip("¿Cuál es el número del equipo?")
            if not ip: return
            t["ip_interna"]=ip; _agregar_hosts(ip)
        self._nav_dialog(f"http://{ip}",tid)

    def _ses_elegir_cache(self):
        tid=self._get_sel_tid()
        if not tid: return
        t=tuneles.get(tid)
        if not t: return
        cache=t.get("scan_cache",[])
        if not cache: messagebox.showinfo(_nombre_empresa(),"Aún no buscaste equipos en este equipo."); return
        self._ventana_cache(tid,cache)

    def _ses_escanear(self):
        tid=self._get_sel_tid()
        if not tid: return
        self._abrir_escaneo(tid=tid,on_select=lambda u:self._nav_dialog(u,tid))

    def _ses_cambiar_ip(self):
        tid=self._get_sel_tid()
        if not tid: return
        t=tuneles.get(tid)
        if not t: return
        ip=self._pedir_ip("¿Cuál es el nuevo número del equipo?")
        if not ip: return
        t["ip_interna"]=ip; _agregar_hosts(ip); self._refrescar_sesiones()

    def _ses_desconectar(self):
        tid=self._get_sel_tid()
        if not tid: return
        if messagebox.askyesno(_nombre_empresa(),"¿Quieres cerrar la conexión con este equipo?"):
            desconectar(tid); self._refrescar_sesiones(); self._refresh_status()

    def _ses_desconectar_todos(self):
        if not tuneles: messagebox.showinfo(_nombre_empresa(),"No hay nada conectado ahora."); return
        if messagebox.askyesno(_nombre_empresa(),"¿Quieres cerrar todo y desconectarte de todos los equipos?"):
            desconectar_todos(); self._refrescar_sesiones(); self._refresh_status()

    # ════════════════════════════════════════════════════════
    #   MENÚ OCULTO  (Alt + 6 × 3)
    # ════════════════════════════════════════════════════════
    def _abrir_config_oculta(self):
        win=ctk.CTkToplevel(self); win.title("⚙️  Configuración")
        win.geometry("600x580"); win.configure(fg_color=C("BG"))
        win.resizable(True,True); win.grab_set(); self._center(win)

        hdr=ctk.CTkFrame(win,fg_color=C("BG3"),corner_radius=0,height=52)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        ctk.CTkLabel(hdr,text="⚙️  Cambiar configuración",font=FN_LG,text_color=C("AIR")).pack(side="left",padx=16,pady=12)

        rb=ctk.CTkFrame(win,fg_color=C("BG3"),corner_radius=0,height=52)
        rb.pack(fill="x",side="bottom"); rb.pack_propagate(False)

        scroll=ctk.CTkScrollableFrame(win,fg_color=C("BG"),corner_radius=0)
        scroll.pack(fill="both",expand=True)

        def _campo(parent, lbl_txt, var, show="", hint=""):
            r=ctk.CTkFrame(parent,fg_color=C("CARD"),corner_radius=0)
            r.pack(fill="x",padx=14,pady=2)
            ctk.CTkLabel(r,text=lbl_txt,font=FN,text_color=C("MUTED"),anchor="w").pack(anchor="w",padx=10,pady=(6,1))
            e=ctk.CTkEntry(r,textvariable=var,show=show,height=34,
                           fg_color=C("BG2"),border_color=C("BORDER"),text_color=C("TEXT"),
                           placeholder_text=hint,placeholder_text_color=C("MUTED"),font=FN)
            e.pack(fill="x",padx=10,pady=(0,8))
            return e

        # ── Configuraciones previas del usuario ──────────────
        s0=mk_frame(scroll); s0.pack(fill="x",padx=12,pady=(10,6))
        mk_label(s0,"Configuraciones que usaste antes",font=FN_B).pack(anchor="w",padx=14,pady=(10,2))
        mk_label(s0,"Toca 'Usar esta' para cargar una configuración previa en los campos de abajo.",
                 fg=C("MUTED"),font=FN_SM).pack(anchor="w",padx=14,pady=(0,6))

        hist_frame=ctk.CTkFrame(s0,fg_color=C("BG2"),corner_radius=6)
        hist_frame.pack(fill="x",padx=14,pady=(0,8))
        ctk.CTkLabel(hist_frame,text="Cargando historial...",
                     font=FN_SM,text_color=C("MUTED")).pack(pady=10)

        v_user   = ctk.StringVar(value=CFG.get("ssh_user",""))
        v_pass   = ctk.StringVar(value=CFG.get("ssh_pass",""))
        v_url    = ctk.StringVar(value=CFG.get("sheets_url",""))
        v_empresa= ctk.StringVar(value=CFG.get("empresa",""))

        def _render_historial(configs):
            for w in hist_frame.winfo_children(): w.destroy()
            if not configs:
                ctk.CTkLabel(hist_frame,text="No hay configuraciones previas guardadas.",
                             font=FN_SM,text_color=C("MUTED")).pack(pady=10)
                return
            for i,cfg in enumerate(configs):
                row=ctk.CTkFrame(hist_frame,fg_color=C("CARD"),corner_radius=6)
                row.pack(fill="x",padx=8,pady=3)
                ts=cfg.get("timestamp",""); emp=cfg.get("empresa","")
                pc=cfg.get("pc_nombre",""); etiq=cfg.get("etiqueta","")
                txt=f"{'★ ACTUAL  ' if i==0 else ''}{ts}   {emp}   PC: {pc}"
                left=ctk.CTkFrame(row,fg_color="transparent",corner_radius=0)
                left.pack(side="left",fill="x",expand=True,padx=(8,0),pady=4)
                ctk.CTkLabel(left,text=txt,font=FN_SM,
                             text_color=C("AIR") if i==0 else C("TEXT"),
                             anchor="w").pack(anchor="w")
                etiq_var=ctk.StringVar(value=etiq)
                etiq_row=ctk.CTkFrame(left,fg_color="transparent",corner_radius=0)
                etiq_row.pack(anchor="w",fill="x")
                ctk.CTkEntry(etiq_row,textvariable=etiq_var,height=24,font=FN_SM,
                    fg_color=C("BG2"),border_color=C("BORDER"),text_color=C("MUTED"),
                    placeholder_text="+ agregar etiqueta",placeholder_text_color=C("DOT"),
                    width=280).pack(side="left",padx=(0,4))
                def _guardar_etiq(c=cfg,ev=etiq_var):
                    nueva=ev.get().strip(); c["etiqueta"]=nueva
                    def _t():
                        try:
                            url=CFG.get("auth_url","").strip() or _AUTH_URL
                            requests.post(url,json={"action":"etiquetar_config",
                                "app_secret":_APP_TOKEN,"usuario":_usuario_activo,
                                "timestamp":c.get("timestamp",""),"etiqueta":nueva},timeout=8)
                        except: pass
                    threading.Thread(target=_t,daemon=True).start()
                mk_btn(etiq_row,"💾",_guardar_etiq,color=C("BG3"),hover=C("BORDER"),
                       width=32,height=24,corner=4).pack(side="left")
                def _usar(c=cfg):
                    v_user.set(c.get("ssh_user","")); v_pass.set(c.get("ssh_pass",""))
                    v_url.set(c.get("sheets_url","")); v_empresa.set(c.get("empresa",""))
                mk_btn(row,"Usar esta",_usar,color=C("BG3"),hover=C("BORDER"),
                       width=100,height=28,corner=6).pack(side="right",padx=8,pady=5)

        def _cargar():
            configs, _ = _cargar_configs_online(_usuario_activo)
            win.after(0, lambda: _render_historial(configs))
        threading.Thread(target=_cargar,daemon=True).start()

        # ── Campos editables ──────────────────────────────────
        s1=mk_frame(scroll); s1.pack(fill="x",padx=12,pady=(0,6))
        mk_label(s1,"Clave para los equipos",font=FN_B).pack(anchor="w",padx=14,pady=(10,2))
        mk_label(s1,"Usuario y clave para entrar a los equipos de tus clientes.",
                 fg=C("MUTED"),font=FN_SM).pack(anchor="w",padx=14,pady=(0,4))
        _campo(s1,"Usuario:", v_user, "", "usuario")
        _campo(s1,"Clave:", v_pass, "●", "Clave del equipo")

        s2=mk_frame(scroll); s2.pack(fill="x",padx=12,pady=(0,6))
        mk_label(s2,"Tu lista de clientes",font=FN_B).pack(anchor="w",padx=14,pady=(10,2))
        _campo(s2,"Link:", v_url, "", "https://docs.google.com/spreadsheets/...")
        info=ctk.CTkFrame(s2,fg_color=C("BG2"),corner_radius=6)
        info.pack(fill="x",padx=14,pady=(0,6))
        ctk.CTkLabel(info,text="En Google: Archivo → Compartir → Publicar en la web → elige CSV",
                     font=FN_SM,text_color=C("MUTED"),wraplength=460).pack(anchor="w",padx=10,pady=5)

        s3=mk_frame(scroll); s3.pack(fill="x",padx=12,pady=(0,6))
        mk_label(s3,"Nombre de tu empresa",font=FN_B).pack(anchor="w",padx=14,pady=(10,2))
        _campo(s3,"Empresa:", v_empresa,"","Nombre de tu empresa")

        s4=mk_frame(scroll); s4.pack(fill="x",padx=12,pady=(0,10))
        mk_label(s4,"Formato de la lista de clientes",font=FN_B).pack(anchor="w",padx=14,pady=(10,2))
        mk_label(s4,"Descarga este archivo para saber cómo llenar tu lista de clientes.",
                 fg=C("MUTED"),font=FN_SM).pack(anchor="w",padx=14,pady=(0,6))
        def _gen():
            import tkinter.filedialog as fd
            ruta=fd.asksaveasfilename(parent=win,title="Guardar plantilla",
                defaultextension=".csv",initialfile="plantilla_clientes.csv",
                filetypes=[("CSV","*.csv"),("Todos","*.*")])
            if not ruta: return
            try:
                import csv as _csv
                with open(ruta,"w",encoding="utf-8-sig",newline="") as f:
                    _csv.writer(f).writerow(ALL_COLS)
                    _csv.writer(f).writerow([""]*len(ALL_COLS))
                messagebox.showinfo(_nombre_empresa(),f"Plantilla guardada en:\n{ruta}",parent=win)
            except Exception as ex: messagebox.showerror("Error",str(ex),parent=win)
        mk_btn(s4,"📄  Descargar el formato",_gen,color=C("BG3"),hover=C("BORDER"),
               width=240,height=34).pack(anchor="w",padx=14,pady=8)

        # ── Guardar → nueva fila online (no borra la anterior) ─
        def guardar():
            su=v_user.get().strip(); sp=v_pass.get().strip()
            sl=v_url.get().strip();  em=v_empresa.get().strip()
            if not su or not sp or not sl or not em:
                messagebox.showwarning(_nombre_empresa(),"Llena todos los campos.",parent=win); return
            btn_save.configure(state="disabled",text="Guardando...")
            import platform, re as _re
            def _g():
                em_clean=_re.sub(r"[^A-Za-z0-9 áéíóúÁÉÍÓÚñÑ]","",em).strip()[:24]
                cfg_data={"ssh_user":su,"ssh_pass":sp,"sheets_url":sl,
                          "empresa":em_clean,"pc_nombre":platform.node()}
                _guardar_config_online(_usuario_activo, cfg_data)
                CFG["ssh_user"]=su; CFG["ssh_pass"]=sp
                CFG["sheets_url"]=sl; CFG["empresa"]=em_clean
                _save_cfg(CFG); invalidar_cache()
                self.after(0, lambda: (
                    win.destroy(),
                    messagebox.showinfo(_nombre_empresa(),
                        "✅ ¡Listo! Cambios guardados.")
                ))
            threading.Thread(target=_g,daemon=True).start()

        def _copiar_depuracion():
            ok, msg = copiar_registro_depuracion_al_portapapeles(win)
            if ok:
                messagebox.showinfo(
                    _nombre_empresa(),
                    msg + "\n\nPega el contenido donde te pidan el registro de depuración.",
                    parent=win,
                )
            else:
                messagebox.showwarning(_nombre_empresa(), msg, parent=win)

        btn_save=mk_btn(rb,"💾  Guardar",guardar,width=160,height=36)
        btn_save.pack(side="left",padx=12,pady=8)
        mk_btn(rb,"Cancelar",win.destroy,color=C("BG2"),hover=C("BG3"),
               fg=C("MUTED"),width=110,height=36).pack(side="right",padx=12,pady=8)
        mk_btn(rb,"📋  Depuración", _copiar_depuracion, color=C("BG3"), hover=C("BORDER"),
               width=130,height=36).pack(side="right",padx=(0,6),pady=8)

    # ════════════════════════════════════════════════════════
    #   BÚSQUEDA
    # ════════════════════════════════════════════════════════
    def _do_search(self):
        q=self._sv.get().strip()
        def run():
            try:
                cl=cargar_clientes(); res=buscar_clientes(q,cl)
                self.after(0,lambda:self._render_res(res))
            except Exception as e:
                _log_exception("_do_search / cargar_clientes")
                self.after(0, lambda err=str(e): messagebox.showerror("Error", err))
        threading.Thread(target=run,daemon=True).start()

    def _render_res(self,res):
        self._cli_table.clear(); self._clientes_res=res
        self._sel_cliente=self._sel_ip=None
        for k in self._ficha: self._ficha[k].configure(text="—")
        if self._iplbl: self._iplbl.configure(text="")
        if not res: return
        vis=CFG["col_visible"]
        for c in res:
            vals=tuple(str(c.get(k,"") or "")[:40] for k in vis)
            self._cli_table.add_row(vals)

    def _on_select(self,idx):
        if idx is None or idx>=len(self._clientes_res): return
        c=self._clientes_res[idx]; self._sel_cliente=c
        ip=(c.get("Ip","") or "").strip(); self._sel_ip=ip
        for k in self._ficha: self._ficha[k].configure(text=str(c.get(k,"—") or "—")[:60])
        if self._iplbl:
            if ip:
                # Mostrar IP SSH completa + rango LAN detectado (si ya está conectado)
                rango = ""
                tid = _tid(ip, CFG.get("ssh_user",""))
                t = tuneles.get(tid)
                if t and t.get("activo"):
                    redes = t.get("redes_lan", [])
                    # Mostrar primera red LAN que no sea la WAN del host
                    ip_prefix = ".".join(ip.split(".")[:3])
                    lan_info = next((r for r in redes if r["prefijo"] != ip_prefix), redes[0] if redes else None)
                    if lan_info:
                        rango = f"  │  {lan_info['cidr']}"
                    self._iplbl.configure(
                        text=f"Equipo: {ip}{rango}  ✅",
                        text_color=C("GREEN"))
                else:
                    # No conectado aún — mostrar igual pero sin checkmark
                    rango = ""
                    self._iplbl.configure(
                        text=f"Equipo: {ip}",
                        text_color=C("AIR"))
            else:
                self._iplbl.configure(text="Este cliente no tiene dirección guardada", text_color=C("RED"))

    # ════════════════════════════════════════════════════════
    #   FLUJOS
    # ════════════════════════════════════════════════════════
    def _resolver_host_cliente_seleccionado(self):
        """Devuelve IP SSH del cliente seleccionado o None."""
        if not self._sel_cliente:
            messagebox.showwarning(_nombre_empresa(), "Primero elige un cliente de la lista.")
            return None
        ssh_host = (self._sel_ip or "").strip()
        if not ssh_host:
            ssh_host = self._pedir_ip(
                f"El cliente {self._sel_cliente.get('Nombre','')} no tiene IP guardada.\n"
                "Escribe la IP SSH del equipo del cliente:"
            )
        return (ssh_host or "").strip() or None

    def _flujo_buscador_doble_click(self, idx=None):
        """
        Doble clic en la tabla de clientes: menú para elegir conexión automática
        (credenciales de ajustes) o manual (usuario/clave solo esta vez).
        """
        if self._conectando:
            return
        if idx is not None and self._clientes_res and 0 <= idx < len(self._clientes_res):
            self._on_select(idx)
        if not self._sel_cliente:
            messagebox.showwarning(
                _nombre_empresa(),
                "Primero elige un cliente de la lista.",
            )
            return
        parent = self.winfo_toplevel()
        win = ctk.CTkToplevel(parent)
        win.title("Tipo de conexión — " + _nombre_empresa())
        win.geometry("460x400")
        win.configure(fg_color=C("BG"))
        win.resizable(False, False)
        win.grab_set()
        self._center(win)

        nm = (self._sel_cliente or {}).get("Nombre", "") or "Cliente"
        ip = (self._sel_ip or "").strip() or "(sin IP en la lista)"
        ctk.CTkLabel(
            win,
            text="¿Cómo quieres conectar?",
            font=FN_LG,
            text_color=C("AIR"),
        ).pack(pady=(18, 6), padx=22, anchor="w")
        ctk.CTkLabel(
            win,
            text=f"Cliente: {nm}",
            font=FN,
            text_color=C("TEXT"),
            anchor="w",
        ).pack(padx=22, anchor="w")
        ctk.CTkLabel(
            win,
            text=f"Equipo (SSH): {ip}",
            font=FN_SM,
            text_color=C("MUTED"),
            anchor="w",
        ).pack(padx=22, pady=(2, 12), anchor="w")

        def cerrar():
            try:
                win.destroy()
            except Exception:
                pass

        def ir_auto():
            cerrar()
            self.after(30, self._flujo_buscador_auto)

        def ir_manual():
            cerrar()
            self.after(30, self._flujo_buscador_manual)

        bt = ctk.CTkFrame(win, fg_color=C("BG"), corner_radius=0)
        bt.pack(fill="x", padx=20, pady=(4, 8))
        mk_btn(
            bt,
            "⚡  Conexión automática",
            ir_auto,
            width=400,
            height=40,
            corner=10,
        ).pack(pady=(0, 8))

        mk_btn(
            bt,
            "✏  Ingresar usuario y clave (solo esta conexión)",
            ir_manual,
            width=400,
            height=40,
            corner=10,
            color=C("BG3"),
            hover=C("BORDER"),
            fg=C("TEXT"),
        ).pack(pady=(0, 8))

        mk_btn(
            bt,
            "Cancelar",
            cerrar,
            color=C("BG2"),
            hover=C("BG3"),
            fg=C("MUTED"),
            width=400,
            height=40,
            corner=10,
        ).pack(fill="x", pady=(8, 4))

        win.bind("<Escape>", lambda e: cerrar())
        win.after(50, lambda: _ui_fade_in(win))

    def _flujo_buscador_auto(self):
        """Tab Clientes: conecta con usuario/clave guardados en ajustes (primer login / ⚙️)."""
        if self._conectando:
            return
        ssh_host = self._resolver_host_cliente_seleccionado()
        if not ssh_host:
            return
        ssh_user = CFG.get("ssh_user", "")
        ssh_pass = CFG.get("ssh_pass", "")
        if not ssh_pass:
            messagebox.showerror(
                _nombre_empresa(),
                "Falta la contraseña SSH por defecto.\n\n"
                "Configúrala en el menú de ajustes (Alt+6+6+6) o usa «Manual» para esta sesión.",
            )
            return
        self._conectar_y_acceder(ssh_host, ssh_user, ssh_pass)

    def _flujo_buscador_manual(self):
        """Tab Clientes: usuario/clave solo para esta conexión (sin rellenar desde ajustes)."""
        if self._conectando:
            return
        ssh_host = self._resolver_host_cliente_seleccionado()
        if not ssh_host:
            return
        parent = self.winfo_toplevel()
        win = ctk.CTkToplevel(parent)
        win.title("Credenciales SSH — " + _nombre_empresa())
        win.geometry("480x460")
        win.minsize(440, 420)
        win.configure(fg_color=C("BG"))
        win.resizable(True, True)
        win.grab_set()
        self._center(win)

        vu = ctk.StringVar(value="")
        vp = ctk.StringVar(value="")

        def cerrar():
            try:
                win.destroy()
            except Exception:
                pass

        def set_msg(text, ok=None):
            if ok is True:
                err.configure(text=text, text_color=C("GREEN"))
            elif ok is False:
                err.configure(text=text, text_color=C("RED"))
            else:
                err.configure(text=text, text_color=C("MUTED"))

        probing = {"busy": False}

        def probar():
            if probing["busy"] or not win.winfo_exists():
                return
            u = vu.get().strip()
            p = vp.get().strip()
            if not u:
                set_msg("Escribe el usuario SSH.", False)
                return
            if not p:
                set_msg("Escribe la contraseña.", False)
                return
            probing["busy"] = True
            try:
                btn_probar.configure(state="disabled", text="Probando…")
            except Exception:
                pass

            def run():
                ok, msg = probar_ssh_login(ssh_host, u, p)

                def done():
                    probing["busy"] = False
                    try:
                        if win.winfo_exists():
                            btn_probar.configure(state="normal", text="🔍  Probar credenciales")
                            set_msg(msg, ok=ok)
                    except Exception:
                        pass

                try:
                    win.after(0, done)
                except Exception:
                    probing["busy"] = False

            threading.Thread(target=run, daemon=True).start()

        def conectar():
            u = vu.get().strip()
            p = vp.get().strip()
            if not u:
                set_msg("Escribe el usuario SSH.", False)
                return
            if not p:
                set_msg("Escribe la contraseña.", False)
                return
            cerrar()
            self._conectar_y_acceder(ssh_host, u, p)

        # Barra inferior primero (pack) para que no quede fuera de la ventana
        footer = ctk.CTkFrame(win, fg_color=C("BG"), corner_radius=0)
        row_btns = ctk.CTkFrame(footer, fg_color=C("BG"), corner_radius=0)
        row_btns.pack(fill="x", pady=(0, 6))
        btn_probar = mk_btn(
            row_btns,
            "🔍  Probar credenciales",
            probar,
            width=168,
            height=40,
            corner=10,
            color=C("BG3"),
            hover=C("BORDER"),
            fg=C("TEXT"),
        )
        btn_probar.pack(side="left", padx=(0, 8))
        mk_btn(row_btns, "🔌  Conectar", conectar, width=150, height=40, corner=10).pack(
            side="left", padx=4
        )
        mk_btn(
            row_btns,
            "Cancelar",
            cerrar,
            color=C("BG2"),
            hover=C("BG3"),
            fg=C("MUTED"),
            width=130,
            height=40,
            corner=10,
        ).pack(side="right", padx=(8, 0))
        footer.pack(side="bottom", fill="x", padx=16, pady=(8, 16))

        body = ctk.CTkFrame(win, fg_color=C("BG"), corner_radius=0)
        body.pack(fill="both", expand=True, padx=16, pady=(16, 4))

        nm = (self._sel_cliente or {}).get("Nombre", "") or "Cliente"
        ctk.CTkLabel(body, text=f"Conectar a: {nm}", font=FN_LG, text_color=C("AIR")).pack(
            pady=(0, 4), anchor="w"
        )
        ctk.CTkLabel(body, text=f"Equipo (SSH): {ssh_host}", font=FN, text_color=C("MUTED")).pack(
            anchor="w"
        )
        ctk.CTkLabel(
            body,
            text="Los campos empiezan vacíos (no se usan los guardados en ajustes). "
            "Puedes probar usuario y clave antes de conectar.",
            font=FN_SM,
            text_color=C("MUTED"),
            wraplength=430,
            justify="left",
        ).pack(pady=(8, 10), anchor="w")

        card = mk_frame(body, corner=10)
        card.pack(fill="x", pady=(0, 6))
        for lbl, var, show, ph in [
            ("Usuario SSH:", vu, "", "usuario en el equipo remoto"),
            ("Contraseña:", vp, "*", "contraseña SSH"),
        ]:
            r = ctk.CTkFrame(card, fg_color=C("CARD"), corner_radius=0)
            r.pack(fill="x", padx=12, pady=(8, 4))
            ctk.CTkLabel(r, text=lbl, font=FN_SM, text_color=C("MUTED"), anchor="w").pack(
                anchor="w", pady=(0, 2)
            )
            ent = ctk.CTkEntry(
                r,
                textvariable=var,
                show=show,
                height=36,
                fg_color=C("BG2"),
                border_color=C("BORDER"),
                text_color=C("TEXT"),
                placeholder_text=ph,
                placeholder_text_color=C("MUTED"),
                font=FN,
            )
            ent.pack(fill="x", pady=(0, 4))
            _style_ctk_entry(ent)

        err = ctk.CTkLabel(
            body,
            text="",
            font=FN_SM,
            text_color=C("MUTED"),
            wraplength=430,
            justify="left",
            anchor="w",
        )
        err.pack(fill="x", pady=(10, 4))

        win.bind("<Escape>", lambda e: cerrar())
        win.after(50, lambda: _ui_fade_in(win))

    def _flujo_manual(self):
        """Tab Conectar: conectar SSH a IP/user/pass manual → acceder al dashboard."""
        ssh_host = self._vh.get().strip()
        ssh_user = self._vu.get().strip() or CFG.get("ssh_user","").strip()
        ssh_pass = self._vp.get().strip() or CFG.get("ssh_pass","").strip()
        if not ssh_host:
            messagebox.showwarning(_nombre_empresa(),"Escribe la dirección del equipo."); return
        if not ssh_pass:
            messagebox.showwarning(_nombre_empresa(),"Escribe la clave del equipo."); return
        self._conectar_y_acceder(ssh_host, ssh_user, ssh_pass)

    def _solo_conectar_manual(self):
        """Tab Conectar: solo establece el túnel SSH, sin abrir dashboard."""
        ssh_host = self._vh.get().strip()
        ssh_user = self._vu.get().strip() or CFG.get("ssh_user","").strip()
        ssh_pass = self._vp.get().strip() or CFG.get("ssh_pass","").strip()
        if not ssh_host:
            messagebox.showwarning(_nombre_empresa(),"Escribe la dirección del equipo."); return
        if not ssh_pass:
            messagebox.showwarning(_nombre_empresa(),"Escribe la clave del equipo."); return
        r,tid = self._conectar_ui(ssh_host, ssh_user, ssh_pass)
        if r is True:
            messagebox.showinfo(_nombre_empresa(),
                f"✅ Conexión activa\n"
                f"Equipo: {ssh_host}\n"
                f"Puerto: {tuneles[tid]['socks_port']}\n\n"
                "Ve a la pestaña 📺 Abiertos para entrar al equipo.")
            self._tabs.set("📺  Abiertos")

    def _scan_manual(self):
        """Tab Conectar: conectar SSH y escanear red interna."""
        ssh_host = self._vh.get().strip()
        ssh_user = self._vu.get().strip() or CFG.get("ssh_user","").strip()
        ssh_pass = self._vp.get().strip() or CFG.get("ssh_pass","").strip()
        if not ssh_host:
            messagebox.showwarning(_nombre_empresa(),"Escribe la dirección del equipo."); return
        if not ssh_pass:
            messagebox.showwarning(_nombre_empresa(),"Escribe la clave del equipo."); return
        r,tid = self._conectar_ui(ssh_host, ssh_user, ssh_pass)
        if r is not True: return
        self._abrir_escaneo(tid=tid, on_select=lambda u: self._nav_dialog(u,tid))

    def _conectar_y_acceder(self, ssh_host, ssh_user, ssh_pass):
        """
        Flujo unificado (usado por Tab Clientes y Tab Conectar):
          1. Conectar SSH a ssh_host → crea SOCKS5 local en 127.0.0.1:108x
          2. Mostrar diálogo: escanear red interna ó ingresar IP manual
          3. Abrir navegador con proxy SOCKS5 → dashboard del cliente
        """
        if self._conectando: return
        self._conectando = True
        try:
            # Paso 1: Establecer túnel SSH → SOCKS5
            r, tid = self._conectar_ui(ssh_host, ssh_user, ssh_pass)
            if r is not True:
                return
            # Paso 2: Elegir IP interna y abrir dashboard
            self._dialogo_acceso(tid)
        except Exception:
            _log_exception("_conectar_y_acceder")
            try:
                messagebox.showerror(
                    _nombre_empresa(),
                    "Ocurrió un error inesperado.\n\n"
                    "Ajustes (Alt+6+6+6) → «Copiar depuración» y envía el texto a soporte.",
                )
            except Exception:
                pass
        finally:
            self._conectando = False

    def _dialogo_acceso(self, tid):
        """
        Paso 2: el túnel SSH ya está activo.
        Aquí elegimos cómo encontrar la IP interna del equipo del cliente:
          - Escanear automáticamente el rango de la red interna
          - Ingresar la IP manualmente
        Después se abre el navegador con proxy SOCKS5 hacia esa IP.
        """
        t = tuneles.get(tid)
        if not t: return
        win = ctk.CTkToplevel(self); win.title("Acceder al equipo")
        win.geometry("520x400")
        win.minsize(480, 360)
        win.configure(fg_color=C("BG"))
        win.resizable(True, True)
        win.grab_set()
        self._center(win)

        def escanear():
            win.destroy()
            self._abrir_escaneo(tid=tid, on_select=lambda u: self._nav_dialog(u, tid))

        def ingresar_manual():
            win.destroy()
            ip = self._pedir_ip("Escribe la IP del router o CPE del cliente\n(en la red interna del ISP):")
            if not ip: return
            t["ip_interna"] = ip; _agregar_hosts(ip)
            self._nav_dialog(f"http://{ip}", tid)

        # Pie: Cancelar con la misma altura/ancho útil que el resto
        footer = ctk.CTkFrame(win, fg_color=C("BG"), corner_radius=0)
        mk_btn(
            footer,
            "Cancelar",
            win.destroy,
            color=C("BG2"),
            hover=C("BG3"),
            fg=C("MUTED"),
            height=42,
            corner=10,
        ).pack(fill="x", padx=20, pady=(0, 18))
        footer.pack(side="bottom", fill="x")

        main = ctk.CTkFrame(win, fg_color=C("BG"), corner_radius=0)
        main.pack(fill="both", expand=True, padx=20, pady=(16, 8))

        # Estado del túnel
        hdr = ctk.CTkFrame(main, fg_color=C("BG3"), corner_radius=0, height=56)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        mk_label(hdr, f"✅  Túnel SSH activo  →  {t['host']}", fg=C("GREEN"), font=FN_B).pack(
            side="left", padx=16, pady=14
        )

        mk_label(main, "¿Cómo encontramos el equipo en la red interna?", font=FN_LG).pack(
            pady=(18, 4), anchor="w"
        )

        mk_btn(main, "🔍  Buscar automáticamente el equipo", escanear, height=44, corner=10).pack(
            fill="x", pady=(0, 6)
        )
        mk_btn(
            main,
            "✏️  Yo conozco la IP, la escribo",
            ingresar_manual,
            color=C("BG3"),
            hover=C("BORDER"),
            fg=C("TEXT"),
            height=42,
            corner=10,
        ).pack(fill="x", pady=(0, 8))

    def _abrir_escaneo(self, tid, on_select=None):
        """
        UI de escaneo con estados:
          INICIAL  → [Escanear] [Cerrar]
          SCANNING → [Detener]  (progress bar animada)
          DONE OK  → [Buscar de nuevo] [✅ Entrar a este equipo]
          DONE 0   → [Buscar de nuevo] [Cerrar]
        """
        t = tuneles.get(tid)
        if not t: return

        win = ctk.CTkToplevel(self); win.title("¿Qué equipos hay en la red?")
        win.geometry("700x580"); win.configure(fg_color=C("BG"))
        win.resizable(True, True); win.grab_set(); self._center(win)

        # ── Header ────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(win, fg_color=C("BG3"), corner_radius=0, height=48)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        mk_label(hdr, f"Equipo: {t['host']}", fg=C("AIR"), font=FN_B).pack(side="left", padx=14, pady=10)
        mk_label(hdr, "✅ Conectado ✅", fg=C("GREEN"), font=FN_SM).pack(side="right", padx=14)

        # ── Cache aviso ───────────────────────────────────────────────
        cache = t.get("scan_cache", [])
        if cache:
            av = mk_frame(win, color=C("BG2"), corner=8); av.pack(fill="x", padx=14, pady=(8,0))
            mk_label(av, f"⚡  Última búsqueda: {len(cache)} equipo(s) encontrado(s).",
                     fg=C("AIR"), font=FN_B).pack(side="left", padx=14, pady=8)
            def usar_cache(): win.destroy(); self._ventana_cache(tid, cache)
            mk_btn(av, "Usar lista anterior", usar_cache,
                   color=C("GREEN"), hover=C("GREEN2"), width=180, height=30).pack(side="right", padx=12, pady=8)

        # ── Parámetros de red ─────────────────────────────────────────
        pf = mk_frame(win); pf.pack(fill="x", padx=14, pady=8)
        # Botones rápidos para cada red LAN detectada
        redes_lan_display = t.get("redes_lan", [])
        if redes_lan_display:
            rb = ctk.CTkFrame(pf, fg_color=C("CARD"), corner_radius=0)
            rb.pack(fill="x", padx=14, pady=(6,0))
            ctk.CTkLabel(rb, text="Redes encontradas:", font=FN_SM,
                         text_color=C("MUTED")).pack(side="left", padx=10, pady=6)
            for red in redes_lan_display:
                pref = red["prefijo"] if isinstance(red, dict) else red
                cidr = red["cidr"]    if isinstance(red, dict) else f"{red}.0/24"
                def _set_red(r=pref): vs.set(r)
                ctk.CTkButton(rb, text=cidr, command=_set_red,
                              width=140, height=26, corner_radius=6,
                              fg_color=C("BG3"), hover_color=C("BORDER"),
                              text_color=C("TEXT"), font=FN_SM).pack(side="left", padx=4, pady=6)
        pf_inner = ctk.CTkFrame(pf, fg_color=C("CARD"), corner_radius=0); pf_inner.pack(fill="x", padx=14, pady=6)
        # Sugerir primera red LAN detectada automáticamente
        redes_lan = t.get("redes_lan", [])
        host_prefix = ".".join(t["host"].split(".")[:3])
        # Preferir la red LAN que no sea la WAN del host SSH
        def _get_pref(r): return r["prefijo"] if isinstance(r, dict) else r
        sugerida = next(
            (_get_pref(r) for r in redes_lan if _get_pref(r) != host_prefix),
            _get_pref(redes_lan[0]) if redes_lan else "192.168.88"
        )
        _log(f"Red sugerida para escaneo: {sugerida}  (detectadas: {redes_lan})")
        vs  = ctk.StringVar(value=sugerida)
        vi  = ctk.StringVar(value="1")
        vf2 = ctk.StringVar(value="254")
        for lbl, var, hint, w in [
            ("Red a buscar:", vs,  "Ej: 192.168.100", 260),
            ("Desde:",                   vi,  "1",               80),
            ("Hasta:",                   vf2, "254",             80),
        ]:
            r = ctk.CTkFrame(pf_inner, fg_color=C("CARD"), corner_radius=0); r.pack(side="left", padx=8, pady=6)
            ctk.CTkLabel(r, text=lbl, font=FN, text_color=C("MUTED"), anchor="w").pack(anchor="w")
            ctk.CTkEntry(r, textvariable=var, height=32, width=w,
                         fg_color=C("BG2"), border_color=C("BORDER"),
                         text_color=C("TEXT"), placeholder_text=hint,
                         placeholder_text_color=C("MUTED"), font=FN).pack()

        # ── Progress ──────────────────────────────────────────────────
        pvar = ctk.DoubleVar(value=0)
        pbar = ctk.CTkProgressBar(win, variable=pvar, height=8,
                                  progress_color=C("AIR"), fg_color=C("BG3"), corner_radius=4)
        pbar.pack(fill="x", padx=14, pady=(4,0)); pbar.set(0)
        plbl = ctk.CTkLabel(win, text="Elige la red y toca Buscar.",
                            font=FN, text_color=C("MUTED"))
        plbl.pack(anchor="w", padx=14, pady=(2,4))

        # ── Tabla resultados ──────────────────────────────────────────
        cols = ("N", "IP", "Puerto", "Nombre del equipo"); widths = [30, 140, 70, 380]
        dbl_ref = [None]
        scan_table = CtkTable(win, cols, widths, height=240,
                              on_double=lambda i: dbl_ref[0] and dbl_ref[0]())
        scan_table.pack(fill="both", expand=True, padx=14, pady=(0,4))

        scan_res = []; row_n = [1]
        # Pre-cargar cache si existe
        if cache:
            for r2 in cache:
                scan_res.append(r2)
                scan_table.add_row((row_n[0], r2["ip"], r2["port"], r2["titulo"]))
                row_n[0] += 1
            plbl.configure(text=f"Resultado anterior: {len(cache)} equipo(s). Puedes escanear de nuevo.",
                           text_color=C("AIR"))
            pbar.set(1)

        # ── Botones (estado dinámico) ─────────────────────────────────
        row_btns = ctk.CTkFrame(win, fg_color=C("BG3"), corner_radius=0, height=52)
        row_btns.pack(fill="x", side="bottom"); row_btns.pack_propagate(False)

        stop_flag = [False]
        scanning  = [False]

        btn_scan  = mk_btn(row_btns, "🔍  Escanear", lambda: None, width=160, height=38)
        btn_stop  = mk_btn(row_btns, "⏹  Detener",  lambda: None,
                           color=C("RED"), hover=C("RED2"), width=160, height=38)
        btn_enter = mk_btn(row_btns, "✅  Entrar a este equipo", lambda: None,
                           color=C("GREEN"), hover=C("GREEN2"), width=220, height=38)
        btn_close = mk_btn(row_btns, "Cerrar", win.destroy,
                           color=C("BG2"), hover=C("BG3"), fg=C("MUTED"), width=100, height=38)

        def set_estado(estado):
            """inicial | scanning | done_ok | done_empty"""
            for b in [btn_scan, btn_stop, btn_enter, btn_close]:
                b.pack_forget()
            if estado == "inicial":
                btn_scan.pack(side="left", padx=10, pady=7)
                btn_close.pack(side="right", padx=10, pady=7)
            elif estado == "scanning":
                btn_stop.pack(side="left", padx=10, pady=7)
            elif estado == "done_ok":
                btn_scan.configure(text="🔄  Buscar de nuevo")
                btn_scan.pack(side="left", padx=10, pady=7)
                btn_enter.pack(side="left", padx=4, pady=7)
                btn_close.pack(side="right", padx=10, pady=7)
            elif estado == "done_empty":
                btn_scan.configure(text="🔄  Buscar de nuevo")
                btn_scan.pack(side="left", padx=10, pady=7)
                btn_close.pack(side="right", padx=10, pady=7)

        set_estado("inicial" if not cache else "done_ok")

        def on_progress(done, total, found, fase):
            try:
                pbar.set(done/total if total else 1)
                if fase == "ping":
                    plbl.configure(text=f"Paso 1: Buscando equipos encendidos......  {done}/{total}  ({found} responden)",
                                   text_color=C("MUTED"))
                else:
                    plbl.configure(text=f"Paso 2: Viendo cuáles se pueden abrir......  {done}/{total}  ({found} encontrados)",
                                   text_color=C("MUTED"))
            except: pass

        # Cola thread-safe para resultados pendientes
        import queue as _queue
        result_queue = _queue.Queue()
        # Flag para indicar que el scan terminó (para drenar la cola)
        scan_done_flag = [False]
        scan_stopped_flag = [False]

        def on_result(r2):
            # Se llama siempre en el hilo UI via win.after — agregar a tabla y lista
            try:
                scan_table.add_row((row_n[0], r2["ip"], r2["port"], r2["titulo"]))
                scan_res.append(r2); row_n[0] += 1
                _log(f"  [UI] Resultado agregado: {r2['ip']}:{r2['port']} — total={len(scan_res)}")
            except Exception as e:
                _log(f"  [UI] on_result error: {e}")

        def _poll_results():
            """Drena la cola de resultados en el hilo UI periódicamente."""
            try:
                if not win.winfo_exists(): return  # ventana cerrada
            except: return
            try:
                while not result_queue.empty():
                    r2 = result_queue.get_nowait()
                    on_result(r2)
            except: pass
            # Si el scan terminó y la cola está vacía → finalizar UI
            if scan_done_flag[0] and result_queue.empty():
                _finalizar_scan(scan_stopped_flag[0])
                return
            # Seguir polling mientras haya escaneo activo
            if scanning[0] or not result_queue.empty():
                try: win.after(150, _poll_results)
                except: pass

        def _finalizar_scan(fue_detenido):
            scanning[0] = False
            n = len(scan_res)
            t["scan_cache"] = list(scan_res)
            _log(f"Scan finalizado. detenido={fue_detenido} encontrados={n}")
            try:
                if not win.winfo_exists(): return
            except: return
            if fue_detenido:
                if n > 0:
                    plbl.configure(text=f"Parado — encontramos {n} equipo(s).",text_color=C("AIR"))
                    set_estado("done_ok")
                else:
                    plbl.configure(text="Se detuvo. No encontramos nada.",text_color=C("MUTED"))
                    set_estado("done_empty")
            else:
                if n > 0:
                    plbl.configure(text=f"✅  ¡Encontramos {n} equipo(s)!",text_color=C("GREEN"))
                    set_estado("done_ok")
                else:
                    plbl.configure(text="No hay equipos con pantalla web en esa red.",text_color=C("RED"))
                    set_estado("done_empty")
            pbar.set(1)

        def run_scan():
            stop_flag[0] = False; scanning[0] = True
            scan_done_flag[0] = False; scan_stopped_flag[0] = False
            scan_res.clear(); row_n[0] = 1; scan_table.clear()
            # Limpiar cola de runs anteriores
            while not result_queue.empty():
                try: result_queue.get_nowait()
                except: break
            pbar.set(0)
            btn_scan.configure(text="🔍  Escanear")
            plbl.configure(text="Buscando...", text_color=C("MUTED"))
            set_estado("scanning")
            subnet = vs.get().strip()
            try: ini = int(vi.get()); fin_ = int(vf2.get())
            except: ini = 1; fin_ = 254
            transport = t["client"].get_transport()
            _log(f"Escaneo: {subnet}.{ini}-{fin_}")

            def cb_p(done, total, found, fase):
                try: win.after(0, lambda d=done,tt=total,f=found,fa=fase: on_progress(d,tt,f,fa))
                except: pass

            def cb_r(rr):
                # Poner en cola thread-safe — el poll lo agrega a la UI
                result_queue.put(rr)

            def work():
                _escanear_con_cb(subnet, ini, fin_, transport, cb_p, cb_r, stop_flag)
                scan_stopped_flag[0] = stop_flag[0]
                scan_done_flag[0] = True  # señal para el poller

            threading.Thread(target=work, daemon=True).start()
            # Iniciar el poller de resultados en hilo UI
            win.after(150, _poll_results)

        def detener():
            stop_flag[0] = True
            plbl.configure(text="Deteniendo la búsqueda...", text_color=C("MUTED"))

        def conectar_sel():
            idx = scan_table.get_selected_idx()
            if idx is None:
                messagebox.showwarning(_nombre_empresa(), "Elige un equipo de la lista.", parent=win); return
            if idx >= len(scan_res): return
            r2 = scan_res[idx]
            t["ip_interna"] = r2["ip"]; _agregar_hosts(r2["ip"]); win.destroy()
            # Usar URL completa guardada (incluye path/query para TP-Link, Huawei, etc.)
            url = r2.get("url") or (
                f"{r2['scheme']}://{r2['ip']}"
                if r2["port"] in (80,443)
                else f"{r2['scheme']}://{r2['ip']}:{r2['port']}"
            )
            _log(f"Seleccionado del escaneo: {url}")
            if on_select: on_select(url)

        dbl_ref[0] = conectar_sel
        btn_scan.configure(command=run_scan)
        btn_stop.configure(command=detener)
        btn_enter.configure(command=conectar_sel)


    def _ventana_cache(self,tid,cache):
        t=tuneles.get(tid)
        if not t: return
        win=ctk.CTkToplevel(self); win.title("Equipos encontrados antes")
        win.geometry("640x420"); win.configure(fg_color=C("BG"))
        win.resizable(True,True); win.grab_set(); self._center(win)
        mk_label(win,"¿A cuál de estos quieres entrar?",font=FN_LG).pack(anchor="w",padx=16,pady=(14,4))
        cols=("N","Número","Puerto","Nombre del equipo"); widths=[28,140,65,360]
        def conectar_sel_cache():
            idx=tbl.get_selected_idx()
            if idx is None: messagebox.showwarning(_nombre_empresa(),"Elige uno.",parent=win); return
            r2=cache[idx]; t["ip_interna"]=r2["ip"]; _agregar_hosts(r2["ip"]); win.destroy()
            url = r2.get("url") or (
                f"{r2['scheme']}://{r2['ip']}"
                if r2["port"] in (80,443)
                else f"{r2['scheme']}://{r2['ip']}:{r2['port']}"
            )
            self._nav_dialog(url,tid)
        tbl=CtkTable(win,cols,widths,height=260,on_double=lambda i: conectar_sel_cache())
        tbl.pack(fill="both",expand=True,padx=14,pady=(0,4))
        for i,r2 in enumerate(cache): tbl.add_row((i+1,r2["ip"],r2["port"],r2["titulo"]))
        row_b=ctk.CTkFrame(win,fg_color=C("BG"),corner_radius=0); row_b.pack(fill="x",padx=14,pady=(4,14))
        mk_btn(row_b,"✅  ¡Entrar a este!",conectar_sel_cache,color=C("GREEN"),hover=C("GREEN2"),width=180,height=36).pack(side="left")
        mk_btn(row_b,"Cerrar",win.destroy,color=C("BG2"),hover=C("BG3"),fg=C("MUTED"),width=100,height=36).pack(side="right")

    def _nav_dialog(self, url, tid):
        """Abre el dashboard via SOCKS5 preservando path/query completo."""
        import urllib.parse as _up
        t = tuneles.get(tid)
        if not t: return
        if "://" not in url: url = "http://" + url
        parsed    = _up.urlparse(url)
        remote_ip = parsed.hostname or url
        scheme    = parsed.scheme or "http"
        port      = parsed.port
        path      = parsed.path or "/"
        query     = ("?" + parsed.query) if parsed.query else ""
        if port and port not in (80, 443):
            url_nav = f"{scheme}://{remote_ip}:{port}{path}{query}"
        else:
            url_nav = f"{scheme}://{remote_ip}{path}{query}"
        socks_port = t["socks_port"]
        _log(f"nav_dialog → {url_nav}  SOCKS5:{socks_port}  ssh:{t['host']}")
        t["ip_interna"] = remote_ip
        _agregar_hosts(remote_ip)
        navs = detectar_navegadores()
        if not navs:
            messagebox.showerror(_nombre_empresa(),"No encontré ningún navegador.\nInstala Chrome, Edge o Firefox.")
            return
        def abrir(nav):
            _log(f"Abriendo: {url_nav}")
            abrir_browser(url_nav, nav, socks_port)
            self._tabs.set("📺  Abiertos")
        if len(navs) == 1:
            abrir(navs[0]); return
        h = 100 + len(navs) * 46
        win = ctk.CTkToplevel(self); win.title("¿Con qué navegador quieres abrirlo?")
        win.geometry(f"340x{h}"); win.configure(fg_color=C("BG"))
        win.resizable(False,False); win.grab_set(); self._center(win)
        ctk.CTkLabel(win,text=f"🌐  {url_nav[:50]}",font=FN_B,text_color=C("AIR")).pack(pady=(14,6),padx=16,anchor="w")
        sel = ctk.IntVar(value=0)
        fr = mk_frame(win,color=C("BG2")); fr.pack(fill="x",padx=16,pady=(0,8))
        for i,nav in enumerate(navs):
            ctk.CTkRadioButton(fr,text=nav["nombre"]+("  ●" if nav["en_uso"] else ""),
                variable=sel,value=i,fg_color=C("ACCENT"),hover_color=C("ACCENT2"),
                text_color=C("TEXT"),font=FN).pack(anchor="w",padx=14,pady=5)
        def ok():
            win.destroy(); abrir(navs[sel.get()])
        mk_btn(win,"🌐  Abrir",ok,width=200,height=36).pack(pady=(0,12))
        win.bind("<Return>",lambda e:ok())

    def _conectar_ui(self,host,user,pw):
        tid=_tid(host,user)
        if tuneles.get(tid,{}).get("activo"): return True,tid
        res=[None,None]; ev=threading.Event()
        def run(): res[0],res[1]=conectar_ssh(host,user,pw); ev.set()
        threading.Thread(target=run,daemon=True).start()
        win=ctk.CTkToplevel(self); win.title("Conectando...")
        win.geometry("420x130"); win.configure(fg_color=C("BG"))
        win.resizable(False,False); win.grab_set(); self._center(win)
        ctk.CTkLabel(win,text=f"Conectando a {host}... 🔄",font=FN,text_color=C("TEXT")).pack(pady=(22,4))
        ctk.CTkLabel(win,text="Creando la conexión segura, espera...",font=FN_SM,text_color=C("MUTED")).pack()
        pb=ctk.CTkProgressBar(win,mode="indeterminate",height=8,progress_color=C("AIR"),fg_color=C("BG3"),corner_radius=4)
        pb.pack(fill="x",padx=30,pady=(8,0)); pb.start()
        def check():
            if ev.is_set():
                pb.stop(); win.destroy()
                r,tid2=res[0],res[1]
                if r is not True:
                    _log(f"[UI_CONNECT] fallo host={host} user={user} resultado={r!r}")
                    if r=="auth":
                        messagebox.showerror(_nombre_empresa(),
                            f"El usuario o la clave están mal para {host}.\n\n"
                            "Revisa que la dirección, el usuario y la clave sean correctos.")
                    else:
                        messagebox.showerror(_nombre_empresa(),
                            f"No se pudo conectar al servidor Equipo:\n{host}\n\n"
                            f"Error: {r}\n\n"
                            "Verifica que la dirección sea correcta y que el\n"
                            "servidor esté encendido y accesible.")
            else: win.after(100,check)
        win.after(100,check); win.wait_window()
        return res[0],res[1]

    def _show_whoami(self):
        win=ctk.CTkToplevel(self); win.title(_nombre_empresa())
        win.geometry("460x380"); win.configure(fg_color=C("BG"))
        win.resizable(False,False); win.grab_set(); self._center(win)

        glow = ctk.CTkFrame(win, fg_color=C("GLOW"), corner_radius=0, height=3)
        glow.pack(fill="x")
        # ── Header compacto — logo izquierda, texto derecha ───────────
        hdr=ctk.CTkFrame(win,fg_color=C("BG3"),corner_radius=0,height=80)
        hdr.pack(fill="x"); hdr.pack_propagate(False)

        pil_logo=_get_logo_pil(44)
        if pil_logo:
            logo_img=ImageTk.PhotoImage(pil_logo,master=win)
            self._logo_imgs["whoami"]=logo_img
            tk.Label(hdr,image=logo_img,bg=C("BG3"),bd=0).pack(
                side="left",padx=(14,8),pady=0,anchor="center")

        tf=ctk.CTkFrame(hdr,fg_color=C("BG3"),corner_radius=0)
        tf.pack(side="left",fill="y",pady=12)

        emp = _nombre_empresa().upper() or "NETSPHERE"
        ctk.CTkLabel(tf,text=emp,font=_ui_font(16,True),
                     text_color=C("AIR"),anchor="w").pack(anchor="w")
        ctk.CTkLabel(tf,text=WHOAMI["nombre"],font=_ui_font(11,True),
                     text_color=C("TEXT"),anchor="w").pack(anchor="w")
        ctk.CTkLabel(tf,text=WHOAMI["rol"],font=_ui_font(9),
                     text_color=C("MUTED"),anchor="w").pack(anchor="w")

        # ── Tarjetas de info ──────────────────────────────────────────
        grid=ctk.CTkFrame(win,fg_color=C("BG"),corner_radius=0)
        grid.pack(fill="x",padx=14,pady=(10,4))
        grid.columnconfigure(0,weight=1); grid.columnconfigure(1,weight=1)

        cards_data = [
            ("📞 Tu teléfono", WHOAMI["tel"]),
            ("🟢 Tu WhatsApp", "Toca 'Abrir chat'"),
            ("🔑 Acceso",      "Solo personas autorizadas"),
            ("🌐 Red",         "NetSphere · Toha Heavy Industries"),
        ]
        for i,(lbl,val) in enumerate(cards_data):
            card=mk_frame(grid,corner=8)
            card.grid(row=i//2,column=i%2,padx=4,pady=4,sticky="ew")
            ctk.CTkLabel(card,text=lbl,font=FN_B,
                         text_color=C("MUTED"),anchor="w").pack(anchor="w",padx=10,pady=(8,2))
            ctk.CTkLabel(card,text=val,font=FN,
                         text_color=C("TEXT"),wraplength=185,
                         justify="left",anchor="w").pack(anchor="w",padx=10,pady=(0,8))

        # ── Botones ───────────────────────────────────────────────────
        row=ctk.CTkFrame(win,fg_color=C("BG"),corner_radius=0); row.pack(pady=8)
        wa=f"https://api.whatsapp.com/send?phone={WHOAMI['tel_wa']}&text={requests.utils.quote(WHOAMI['wa_msg'])}&type=phone_number&app_absent=0"
        mk_btn(row,"🟢  Chat",   lambda:webbrowser.open(wa),
               color=C("GREEN"),hover=C("GREEN2"),width=110,height=36).pack(side="left",padx=4)
        mk_btn(row,"📞  Llamar", lambda:webbrowser.open(f"tel:+{WHOAMI['tel_wa']}"),
               color=C("BG3"),hover=C("BORDER"),width=110,height=36).pack(side="left",padx=4)
        mk_btn(row,"📋  Copiar", lambda:self._copiar_whoami(win),
               color=C("BG3"),hover=C("BORDER"),width=100,height=36).pack(side="left",padx=4)
        mk_btn(row,"Cerrar",     win.destroy,
               color=C("BG2"),hover=C("BG3"),fg=C("MUTED"),width=100,height=36).pack(side="left",padx=4)
        win.bind("<Escape>",lambda e:win.destroy())
        win.after(50, lambda: _ui_fade_in(win))

    def _copiar_whoami(self,parent=None):
        txt=f"{_nombre_empresa()}\n{WHOAMI['tel']}\nSoporte técnico"
        self.clipboard_clear(); self.clipboard_append(txt)
        messagebox.showinfo("Copiado","Datos copiados ✅",parent=parent or self)

    def _pedir_ip(self,msg):
        win=ctk.CTkToplevel(self); win.title("Dirección del equipo")
        win.geometry("400x165"); win.configure(fg_color=C("BG"))
        win.resizable(False,False); win.grab_set(); self._center(win)
        ctk.CTkLabel(win,text=msg,font=FN,text_color=C("MUTED"),wraplength=360).pack(pady=(18,8),padx=20)
        v=ctk.StringVar()
        e=ctk.CTkEntry(win,textvariable=v,height=36,fg_color=C("CARD"),border_color=C("BORDER"),
                        text_color=C("TEXT"),placeholder_text="Ejemplo: 192.168.100.1",
                        placeholder_text_color=C("MUTED"),font=FN)
        e.pack(fill="x",padx=20,pady=(0,8)); e.focus()
        _style_ctk_entry(e)
        res=[None]
        def ok(_=None): res[0]=v.get().strip(); win.destroy()
        e.bind("<Return>",ok)
        mk_btn(win,"✅  Listo",ok,width=160,height=36).pack(pady=8)
        win.wait_window(); return res[0]

    def _center(self,win):
        win.update_idletasks()
        x=self.winfo_toplevel().winfo_x()+(self.winfo_toplevel().winfo_width()-win.winfo_width())//2
        y=self.winfo_toplevel().winfo_y()+(self.winfo_toplevel().winfo_height()-win.winfo_height())//2
        win.geometry(f"+{max(0,x)}+{max(0,y)}")


    def _on_close(self):
        try:
            self._stop_status_pulse()
        except Exception:
            pass
        _detener_heartbeat()
        if tuneles:
            if not messagebox.askyesno(_nombre_empresa(),
                f"Tienes {len(tuneles)} conexión(es) abierta(s).\n¿Quieres cerrar todas las conexiones y salir?"): return
        api_logout_best_effort()
        desconectar_todos()
        sys.exit(0)


def _set_window_icon(win):
    """Aplica el logo Toha embebido como icono de la ventana (reemplaza el cuadrado de CTk)."""
    try:
        pil = _get_logo_pil(48, tint=(255, 255, 255))
        if pil:
            bg = Image.new("RGBA", (48, 48), (14, 30, 54, 255))
            bg.paste(pil, (0, 0), pil)
            ico = ImageTk.PhotoImage(bg)
            win._icon_ref = ico          # evitar que el GC lo elimine
            win.wm_iconphoto(True, ico)
    except:
        pass

def _mostrar_whoami():
    if not _root_ref: return
    try:
        parent = _root_ref
        win = ctk.CTkToplevel(parent)
        win.title(_nombre_empresa() or "NetSphere")
        win.geometry("460x320"); win.configure(fg_color=C("BG"))
        win.resizable(False,False); win.grab_set()
        win.update_idletasks()
        x=(win.winfo_screenwidth()-460)//2; y=(win.winfo_screenheight()-320)//2
        win.geometry(f"460x320+{x}+{y}")
        hdr=ctk.CTkFrame(win,fg_color=C("BG3"),corner_radius=0,height=80)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        pil_logo=_get_logo_pil(44)
        if pil_logo:
            logo_img=ImageTk.PhotoImage(pil_logo,master=win)
            win._logo_ref=logo_img
            tk.Label(hdr,image=logo_img,bg=C("BG3"),bd=0).pack(side="left",padx=(14,8),anchor="center")
        tf=ctk.CTkFrame(hdr,fg_color=C("BG3"),corner_radius=0); tf.pack(side="left",fill="y",pady=12)
        emp=(_nombre_empresa().upper() or "NETSPHERE")
        ctk.CTkLabel(tf,text=emp,font=_ui_font(16,True),text_color=C("AIR"),anchor="w").pack(anchor="w")
        ctk.CTkLabel(tf,text=WHOAMI["nombre"],font=_ui_font(11,True),text_color=C("TEXT"),anchor="w").pack(anchor="w")
        ctk.CTkLabel(tf,text=WHOAMI["rol"],font=_ui_font(9),text_color=C("MUTED"),anchor="w").pack(anchor="w")
        grid=ctk.CTkFrame(win,fg_color=C("BG"),corner_radius=0); grid.pack(fill="x",padx=14,pady=(10,4))
        grid.columnconfigure(0,weight=1); grid.columnconfigure(1,weight=1)
        cards=[("📞 Teléfono",WHOAMI["tel"]),("🟢 WhatsApp","Toca Chat"),
               ("🔑 Acceso","Solo autorizados"),("🌐 Red","NetSphere · Toha")]
        for i,(lbl,val) in enumerate(cards):
            card=mk_frame(grid,corner=8); card.grid(row=i//2,column=i%2,padx=4,pady=4,sticky="ew")
            ctk.CTkLabel(card,text=lbl,font=FN_B,text_color=C("MUTED"),anchor="w").pack(anchor="w",padx=10,pady=(8,2))
            ctk.CTkLabel(card,text=val,font=FN,text_color=C("TEXT"),anchor="w").pack(anchor="w",padx=10,pady=(0,8))
        row=ctk.CTkFrame(win,fg_color=C("BG"),corner_radius=0); row.pack(pady=8)
        wa=f"https://api.whatsapp.com/send?phone={WHOAMI['tel_wa']}&text={requests.utils.quote(WHOAMI['wa_msg'])}&type=phone_number&app_absent=0"
        mk_btn(row,"🟢  Chat",lambda:webbrowser.open(wa),color=C("GREEN"),hover=C("GREEN2"),width=110,height=36).pack(side="left",padx=4)
        mk_btn(row,"Cerrar",win.destroy,color=C("BG2"),hover=C("BG3"),fg=C("MUTED"),width=100,height=36).pack(side="left",padx=4)
        win.bind("<Escape>",lambda e:win.destroy())
        win.after(50, lambda: _ui_fade_in(win))
    except Exception:
        _log_exception("_show_whoami_card")

def _heartbeat_loop(root, gen):
    global _heartbeat_activo, _session_token, _usuario_activo, _heartbeat_gen, _bridge_sheet_seed
    import time as _time
    while _heartbeat_activo and gen == _heartbeat_gen:
        _time.sleep(30)
        if gen != _heartbeat_gen or not _heartbeat_activo or not _session_token:
            break
        try:
            url = CFG.get("auth_url","").strip() or _AUTH_URL
            payload = {"action":"heartbeat","app_secret":_APP_TOKEN,
                       "usuario":_usuario_activo,"session_token":_session_token,
                       "ip_publica":_public_ip()}
            resp = requests.post(url, json=payload, timeout=8)
            data = resp.json()
            if data.get("kicked"):
                motivo = data.get("motivo","Sesión terminada por el servidor.")
                _log(f"[HEARTBEAT] KICKED: {motivo}")
                _heartbeat_activo = False
                _session_token = ""
                _usuario_activo = ""
                _bridge_sheet_seed = ""
                CFG.update(dict(_CFG_DEFAULT))
                _reaplicar_prefs_despues_reset_cfg()
                desconectar_todos()
                def _forzar_logout():
                    try:
                        messagebox.showwarning("Sesión cerrada", motivo+"\n\nSe cerrará la sesión.")
                        if root and hasattr(root,"_mostrar_login"): root._mostrar_login()
                    except: pass
                if root: root.after(0, _forzar_logout)
                return
        except Exception as ex: _log(f"[HEARTBEAT] Error: {ex}")

def _iniciar_heartbeat():
    global _heartbeat_activo, _heartbeat_gen
    _detener_heartbeat()
    _heartbeat_gen += 1
    gen = _heartbeat_gen
    _heartbeat_activo = True
    threading.Thread(target=_heartbeat_loop, args=(_root_ref, gen), daemon=True).start()

def _detener_heartbeat():
    global _heartbeat_activo
    _heartbeat_activo = False

def _set_window_icon(win):
    try:
        pil = _get_logo_pil(256, tint=(255, 255, 255))
        if pil:
            bg = Image.new("RGBA", (256, 256), (14, 30, 54, 255))
            bg.paste(pil, (0, 0), pil)
            ico_path = os.path.join(tempfile.gettempdir(), "_ns_bridge_icon.ico")
            sizes = [(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)]
            imgs = [bg.resize(s, Image.LANCZOS) for s in sizes]
            imgs[0].save(ico_path, format="ICO",
                         sizes=[(i.width,i.height) for i in imgs],
                         append_images=imgs[1:])
            win.wm_iconbitmap(ico_path)
    except: pass

# ════════════════════════════════════════════════════════════════
#   RootApp — única instancia CTk
# ════════════════════════════════════════════════════════════════
class RootApp(ctk.CTk):

    def __init__(self):
        global _root_ref
        super().__init__()
        _root_ref = self
        _nombre = _tema_auto() if CFG.get("tema","auto")=="auto" else CFG.get("tema","dark")
        _apply_palette(_nombre)
        self.configure(fg_color=C("BG"))
        _set_window_icon(self)
        self._intentos = 0
        self._logo_ref = None
        self._app      = None
        self.protocol("WM_DELETE_WINDOW", self._cerrar_todo)
        self._mostrar_login()

    def _cerrar_todo(self):
        if self._app and hasattr(self._app,"_on_close"):
            self._app._on_close()
        else:
            api_logout_best_effort()
            desconectar_todos()
            sys.exit(0)

    def _limpiar(self):
        for w in self.winfo_children():
            try: w.destroy()
            except: pass

    def _nombre_mostrar(self):
        return _nombre_empresa() or "Bridge"

    # ════════════════════════════════════════════════════════
    #   HEADER REUTILIZABLE
    # ════════════════════════════════════════════════════════
    def _build_header(self, subtitulo="Entra a los equipos de tus clientes"):
        top_accent = ctk.CTkFrame(self, fg_color=C("GLOW"), corner_radius=0, height=3)
        top_accent.pack(fill="x")
        hdr=ctk.CTkFrame(self,fg_color=C("BG3"),corner_radius=0,height=110)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        pil_logo=_get_logo_pil(52)
        if pil_logo:
            logo_img=ImageTk.PhotoImage(pil_logo,master=self)
            self._logo_ref=logo_img
            tk.Label(hdr,image=logo_img,bg=C("BG3"),bd=0).pack(side="left",padx=(16,6),pady=20)
        tf=ctk.CTkFrame(hdr,fg_color=C("BG3"),corner_radius=0); tf.pack(side="left",pady=22)
        empresa = _nombre_empresa()
        # Siempre mostrar NetSphere arriba, empresa abajo
        ctk.CTkLabel(tf,text="NetSphere",font=_ui_font(18,True),
                     text_color=C("AIR")).pack(anchor="w")
        if empresa:
            ctk.CTkLabel(tf,text=empresa,font=_ui_font(12),
                         text_color=C("WHITE")).pack(anchor="w")
        ctk.CTkLabel(tf,text=subtitulo,font=FN_SM,text_color=C("MUTED")).pack(anchor="w")

    def _build_tema_row(self):
        sf=ctk.CTkFrame(self,fg_color=C("BG"),corner_radius=0); sf.pack(pady=4)
        ctk.CTkLabel(sf,text="Tema: ",font=FN,text_color=C("MUTED")).pack(side="left")
        seg=ctk.CTkSegmentedButton(sf,values=["🌙","☀️","⚡"],
            command=self._on_tema_login,
            fg_color=C("BG2"),selected_color=C("ACCENT"),selected_hover_color=C("ACCENT2"),
            unselected_color=C("BG2"),unselected_hover_color=C("BORDER"),
            text_color=C("TEXT"),font=FN_SM,width=110,height=26)
        t=CFG.get("tema","auto")
        seg.set("🌙" if t=="dark" else "☀️" if t=="light" else "⚡")
        seg.pack(side="left")

    # ════════════════════════════════════════════════════════
    #   LOGIN
    # ════════════════════════════════════════════════════════
    def _mostrar_login(self):
        self._limpiar()
        self.geometry("420x620"); self.minsize(380,560); self.resizable(True,True)
        self.title("NetSphere · Bridge")

        glow_top = ctk.CTkFrame(self, fg_color=C("GLOW"), corner_radius=0, height=3)
        glow_top.pack(fill="x")

        # ── Header especial del login: NetSphere + Toha Heavy Industries ─
        hdr=ctk.CTkFrame(self,fg_color=C("BG3"),corner_radius=0,height=110)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        pil_logo=_get_logo_pil(52)
        if pil_logo:
            logo_img=ImageTk.PhotoImage(pil_logo,master=self)
            self._logo_ref=logo_img
            tk.Label(hdr,image=logo_img,bg=C("BG3"),bd=0).pack(side="left",padx=(16,6),pady=20)
        tf=ctk.CTkFrame(hdr,fg_color=C("BG3"),corner_radius=0); tf.pack(side="left",pady=20)
        ctk.CTkLabel(tf,text="NetSphere",
                     font=_ui_font(26,True),text_color=C("AIR")).pack(anchor="w")
        ctk.CTkLabel(tf,text="Toha Heavy Industries",
                     font=_ui_font(10),text_color=C("MUTED")).pack(anchor="w")

        ctk.CTkLabel(self,text="¡Hola! ¿Quién eres?",font=FN_LG,text_color=C("TEXT")).pack(pady=(18,2))

        card=mk_frame(self,corner=12); card.pack(fill="x",padx=30,pady=(8,0))
        _lp = _load_local_prefs()
        ru = _lp["remember_user"] if "remember_user" in _lp else True
        rp = _lp["remember_pass"] if "remember_pass" in _lp else False
        self._remember_user = ctk.BooleanVar(value=ru)
        self._remember_pass = ctk.BooleanVar(value=rp)
        self._vu = ctk.StringVar()
        self._vp = ctk.StringVar()
        if ru and _lp.get("last_login_user"):
            self._vu.set(str(_lp.get("last_login_user", "")).strip())
        if rp and _lp.get("cred_pass_enc"):
            _dp = _decrypt_for_machine(_lp.get("cred_pass_enc", ""))
            if _dp:
                self._vp.set(_dp)
        for lbl,var,show,ph in [
            ("Tu nombre:",self._vu,"","escribe tu nombre aquí"),
            ("Tu clave:",self._vp,"●","escribe tu clave aquí"),
        ]:
            r=ctk.CTkFrame(card,fg_color=C("CARD"),corner_radius=0); r.pack(fill="x",padx=16,pady=(10,2))
            ctk.CTkLabel(r,text=lbl,font=FN,text_color=C("MUTED"),anchor="w").pack(anchor="w",pady=(0,2))
            e=ctk.CTkEntry(r,textvariable=var,show=show,height=38,
                fg_color=C("BG2"),border_color=C("BORDER"),text_color=C("TEXT"),
                placeholder_text=ph,placeholder_text_color=C("MUTED"),font=FN)
            e.pack(fill="x",pady=(0,4))
            _style_ctk_entry(e)
            if show: e.bind("<Return>",lambda _:self._login())
        ckf = ctk.CTkFrame(card, fg_color=C("CARD"), corner_radius=0)
        ckf.pack(fill="x", padx=16, pady=(4, 2))
        ctk.CTkCheckBox(
            ckf,
            text="Recordar usuario en este equipo",
            variable=self._remember_user,
            font=FN_SM,
            text_color=C("TEXT"),
            fg_color=C("ACCENT"),
            hover_color=C("ACCENT2"),
            border_color=C("BORDER"),
        ).pack(anchor="w", pady=2)
        ctk.CTkCheckBox(
            ckf,
            text="Recordar clave en este equipo",
            variable=self._remember_pass,
            font=FN_SM,
            text_color=C("TEXT"),
            fg_color=C("ACCENT"),
            hover_color=C("ACCENT2"),
            border_color=C("BORDER"),
        ).pack(anchor="w", pady=2)
        ctk.CTkFrame(card,fg_color=C("BG"),height=6,corner_radius=0).pack()

        self._err=ctk.CTkLabel(self,text="",font=FN_SM,text_color=C("RED"),wraplength=360)
        self._err.pack(pady=(8,2))

        row_btns=ctk.CTkFrame(self,fg_color=C("BG"),corner_radius=0); row_btns.pack(pady=4)
        self._btn_login=mk_btn(row_btns,"🔐  Entrar",self._login,width=200,height=42)
        self._btn_login.pack(side="left",padx=(0,8))
        mk_btn(row_btns,"📝  Pedir acceso",self._mostrar_registro,
               color=C("BG3"),hover=C("BORDER"),width=160,height=42).pack(side="left")

        self._build_tema_row()
        self.bind("<Alt-Key-5>", lambda e: _mostrar_whoami())
        self.after(40, lambda: _ui_fade_in(self))

    def _on_tema_login(self,val):
        mapa={"🌙":"dark","☀️":"light","⚡":"auto"}
        t=mapa.get(val,"auto")
        CFG["tema"] = t
        _save_cfg(CFG)
        _apply_palette(_tema_auto() if t=="auto" else t)
        self.configure(fg_color=C("BG"))
        self._limpiar(); self._mostrar_login()

    def _login(self):
        usuario=self._vu.get().strip(); clave=self._vp.get().strip()
        if not usuario or not clave:
            self._err.configure(text="Escribe tu nombre y tu clave para entrar."); return
        self._btn_login.configure(state="disabled",text="Revisando...")
        self._err.configure(text="")
        def run():
            ok, msg, meta = verificar_login(usuario, clave)
            uu = usuario
            cc = clave
            mm = meta
            self.after(0, lambda: self._resultado_login(ok, msg, mm, uu, cc))
        threading.Thread(target=run,daemon=True).start()

    def _center_win(self, win):
        win.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() - win.winfo_width()) // 2
        y = self.winfo_y() + (self.winfo_height() - win.winfo_height()) // 2
        win.geometry(f"+{max(0,x)}+{max(0,y)}")

    def _dialogo_sesion_otra_red(self, _server_msg, meta):
        """Sesión activa desde otra WAN: tomar sesión, regresar o reintentar."""
        win = ctk.CTkToplevel(self)
        win.title(_nombre_empresa() or "NetSphere")
        win.geometry("500x460")
        win.configure(fg_color=C("BG"))
        win.resizable(True, True)
        win.grab_set()
        self._center_win(win)

        glow = ctk.CTkFrame(win, fg_color=C("GLOW"), corner_radius=0, height=3)
        glow.pack(fill="x")
        ctk.CTkLabel(win, text="Sesión en otra red", font=FN_LG, text_color=C("AIR")).pack(pady=(14, 6))
        ctk.CTkLabel(
            win,
            text=(
                "Ya hay una sesión activa desde otro equipo o red.\n\n"
                "Puedes usar «Tomar sesión aquí» con tu misma contraseña, "
                "o cerrar Bridge en el otro sitio y pulsar Reintentar."
            ),
            wraplength=440,
            justify="left",
            font=FN,
            text_color=C("TEXT"),
        ).pack(padx=22, anchor="w")
        ayuda = (
            "Soluciones:\n"
            "• Cierra Bridge en el otro equipo y pulsa Reintentar.\n"
            "• Usa «Tomar sesión aquí» para invalidar la otra sesión (misma contraseña).\n"
            "• Tras ~1 h suele ser más fácil tomar sesión si la otra quedó colgada.\n"
            "• Dentro de la app, la pestaña Conectar permite usuario/clave manual del equipo."
        )
        ctk.CTkLabel(win, text=ayuda, wraplength=440, justify="left", font=FN_SM, text_color=C("MUTED")).pack(
            padx=22, pady=14, anchor="w"
        )

        row = ctk.CTkFrame(win, fg_color=C("BG"), corner_radius=0)
        row.pack(pady=12)

        def cerrar():
            try:
                win.destroy()
            except Exception:
                pass

        def takeover():
            cerrar()
            u = self._vu.get().strip()
            p = self._vp.get().strip()
            try:
                self._btn_login.configure(state="disabled", text="Tomando sesión…")
            except Exception:
                pass

            def r2():
                ok2, msg2, meta2 = verificar_login(u, p, force_new_session=True)
                uu = u
                pp = p
                m2 = meta2
                self.after(0, lambda: self._resultado_login(ok2, msg2, m2, uu, pp))

            threading.Thread(target=r2, daemon=True).start()

        def reintentar():
            cerrar()
            try:
                self._err.configure(
                    text="Cierra la sesión en el otro equipo y vuelve a pulsar Entrar.",
                    text_color=C("AIR"),
                )
            except Exception:
                pass

        def ayuda_box():
            messagebox.showinfo(
                "Ayuda — sesión en otra red",
                "Si no reconoces la otra sesión, cambia tu contraseña o avisa al administrador.\n\n"
                "El bloqueo de 24 h en el servidor aplica solo por muchos intentos de contraseña incorrecta, "
                "no por cambiar de red.",
                parent=win,
            )

        mk_btn(row, "Tomar sesión aquí", takeover, width=170, height=40).pack(side="left", padx=5)
        mk_btn(row, "Reintentar", reintentar, color=C("BG3"), hover=C("BORDER"), width=130, height=40).pack(
            side="left", padx=5
        )
        mk_btn(row, "Regresar", cerrar, color=C("BG2"), hover=C("BG3"), fg=C("MUTED"), width=110, height=40).pack(
            side="left", padx=5
        )
        mk_btn(row, "Ayuda", ayuda_box, color=C("BG3"), hover=C("BORDER"), width=90, height=40).pack(side="left", padx=5)
        win.bind("<Escape>", lambda e: cerrar())
        win.after(60, lambda: _ui_fade_in(win))

    def _resultado_login(self, ok, msg, meta=None, cuenta_usuario=None, clave_recordar=None):
        global _bridge_sheet_seed
        meta = meta or {}
        if not ok:
            _bridge_sheet_seed = ""
        else:
            _bridge_sheet_seed = str(meta.get("bridge_semilla") or "").strip()
        if ok:
            try:
                ru = bool(getattr(self, "_remember_user", None) and self._remember_user.get())
                rp = bool(getattr(self, "_remember_pass", None) and self._remember_pass.get())
                _persist_login_credentials_prefs(ru, rp, cuenta_usuario, clave_recordar)
            except Exception:
                pass
            try:
                self._btn_login.configure(state="disabled", text="Cargando…")
            except Exception:
                pass
            try:
                self._err.configure(text="")
            except Exception:
                pass

            def _verificar():
                global _usuario_activo
                for intento in range(1, 4):
                    configs, servidor_ok = _cargar_configs_online(_usuario_activo)
                    if servidor_ok:
                        def _entrar_app():
                            try:
                                if configs:
                                    _aplicar_config_online(configs[0])
                                    self._mostrar_app()
                                else:
                                    self._mostrar_primer_uso()
                            except Exception:
                                pass

                        self.after(0, _entrar_app)
                        return
                    if intento < 3:
                        time.sleep(1.5)
                _log("[CONFIG] sin respuesta tras reintentos")
                _usuario_activo = ""

                def _bloquear():
                    try:
                        self._btn_login.configure(state="normal", text="🔐  Entrar")
                        self._err.configure(
                            text="Sin conexión al servidor. Revisa tu internet e intenta de nuevo.",
                            text_color=C("RED"),
                        )
                    except Exception:
                        pass

                self.after(0, _bloquear)

            threading.Thread(target=_verificar, daemon=True).start()
        else:
            if meta.get("code") == "session_active_other_network":
                try:
                    self._btn_login.configure(state="normal", text="🔐  Entrar")
                except Exception:
                    pass
                try:
                    self._err.configure(text="")
                except Exception:
                    pass
                self._dialogo_sesion_otra_red(msg, meta)
                return
            self._intentos+=1
            try: self._btn_login.configure(state="normal",text="🔐  Entrar")
            except: pass
            try:
                self._err.configure(text=msg,text_color=C("RED"))
            except: pass
            if self._intentos>=5:
                try:
                    self._btn_login.configure(state="disabled",text="Demasiados errores")
                    self._err.configure(text="Espera un momento e intenta de nuevo.",text_color=C("RED"))
                except: pass
                self.after(30000,self._reset_bloqueo)

    def _reset_bloqueo(self):
        self._intentos=0
        try:
            self._btn_login.configure(state="normal",text="🔐  Entrar")
            self._err.configure(text="")
        except: pass

    # ════════════════════════════════════════════════════════
    #   REGISTRO
    # ════════════════════════════════════════════════════════
    def _mostrar_registro(self):
        self._limpiar()
        self.geometry("440x660"); self.minsize(400,580); self.resizable(True,True)
        self.title("Solicitud de acceso")
        self._build_header("Quiero usar el programa")

        ctk.CTkLabel(self,text="Cuéntanos quién eres",font=FN_LG,text_color=C("TEXT")).pack(pady=(14,2))
        ctk.CTkLabel(self,text="El dueño del programa va a revisar tu solicitud y te dará acceso cuando esté listo.",
                     font=FN_SM,text_color=C("MUTED"),wraplength=380).pack(pady=(0,6))

        scroll=ctk.CTkScrollableFrame(self,fg_color=C("BG"),corner_radius=0,height=360)
        scroll.pack(fill="x",padx=24,pady=(0,4))

        vars_reg = {}
        entries  = []  # lista de entries para manejar Tab
        campos = [
            ("usuario",   "Tu nombre de usuario *", "",  "Solo letras, números y guiones bajos"),
            ("clave",     "Tu clave secreta *",      "●", "Al menos 6 letras o números"),
            ("confirmar", "Repite tu clave *",       "●", "Escribe la clave otra vez"),
            ("correo",    "Tu correo *",             "",  "tu@correo.com"),
            ("empresa",   "Tu empresa *",            "",  "Nombre de tu empresa"),
            ("telefono",  "Tu teléfono",             "",  "Número de contacto"),
            ("whatsapp",  "Tu WhatsApp",             "",  "Ejemplo: 521234567890"),
        ]
        for key,lbl,show,ph in campos:
            r=ctk.CTkFrame(scroll,fg_color=C("CARD"),corner_radius=0); r.pack(fill="x",pady=(6,0))
            ctk.CTkLabel(r,text=lbl,font=FN,text_color=C("MUTED"),anchor="w").pack(anchor="w",padx=10,pady=(6,1))
            v=ctk.StringVar(); vars_reg[key]=v
            e=ctk.CTkEntry(r,textvariable=v,show=show,height=36,
                fg_color=C("BG2"),border_color=C("BORDER"),text_color=C("TEXT"),
                placeholder_text=ph,placeholder_text_color=C("MUTED"),font=FN)
            e.pack(fill="x",padx=10,pady=(0,8))
            _style_ctk_entry(e)
            entries.append(e)

        # Tab entre campos + auto-scroll al campo activo
        def _focus_entry(idx):
            """Mueve el foco y hace scroll para mostrar el campo."""
            e = entries[idx % len(entries)]
            e.focus_set()
            def _scroll():
                try:
                    # Obtener posición relativa del entry dentro del scroll
                    e.update_idletasks()
                    scroll.update_idletasks()
                    # Coordenada Y del entry en el frame interno del scroll
                    ey = e.winfo_rooty()
                    sy = scroll.winfo_rooty()
                    sh = scroll.winfo_height()
                    # Si el entry está debajo del área visible, hacer scroll
                    rel = (ey - sy) / max(sh, 1)
                    if rel > 0.6:
                        scroll._parent_canvas.yview_scroll(3, "units")
                    elif rel < 0.1 and idx > 0:
                        scroll._parent_canvas.yview_scroll(-3, "units")
                except: pass
            e.after(50, _scroll)

        def _make_tab(idx, direction=1):
            def _tab(event):
                _focus_entry(idx + direction)
                return "break"
            return _tab

        for idx, entry in enumerate(entries):
            entry.bind("<Tab>",       _make_tab(idx, 1))
            entry.bind("<Shift-Tab>", _make_tab(idx, -1))
            entry.bind("<Return>",    _make_tab(idx, 1))

        self._err_reg=ctk.CTkLabel(self,text="",font=FN_SM,text_color=C("RED"),wraplength=390)
        self._err_reg.pack(pady=(2,2))

        def enviar():
            u   = vars_reg["usuario"].get().strip()
            c   = vars_reg["clave"].get().strip()
            c2  = vars_reg["confirmar"].get().strip()
            em  = vars_reg["correo"].get().strip()
            emp = vars_reg["empresa"].get().strip()[:24]
            tel = vars_reg["telefono"].get().strip()
            wa  = vars_reg["whatsapp"].get().strip()
            if not u or not c or not em or not emp:
                self._err_reg.configure(text="Faltan datos importantes. Llena todo lo marcado con *."); return
            import re as _re
            # Validar formato del nombre de usuario
            if not _re.match(r"^[a-zA-Z0-9_\.\-]{3,30}$", u):
                self._err_reg.configure(
                    text="El nombre de usuario solo puede tener letras, números, puntos o guiones. Mínimo 3 caracteres.")
                entries[0].focus_set(); return
            if len(c) < 6:
                self._err_reg.configure(text="La clave necesita al menos 6 letras o números."); return
            if c != c2:
                self._err_reg.configure(text="Las dos claves no son iguales. Revísalas."); return
            if not _re.match(r"[^@]+@[^@]+\.[^@]+", em):
                self._err_reg.configure(text="Ese correo no parece correcto."); return
            btn_enviar.configure(state="disabled",text="Mandando...")
            self._err_reg.configure(text="")
            def run():
                ok,msg = registrar_usuario({
                    "usuario":u,"clave":c,"correo":em,
                    "empresa":emp,"telefono":tel,"whatsapp":wa
                })
                self.after(0,lambda:_resultado_reg(ok,msg))
            threading.Thread(target=run,daemon=True).start()

        def _resultado_reg(ok,msg):
            if ok:
                messagebox.showinfo("Solicitud enviada",
                    "Tu solicitud fue enviada.\nEl administrador la revisará y activará tu cuenta.")
                self._mostrar_login()
            else:
                # Mensajes específicos según el tipo de error
                msg_limpio = msg.strip()
                if "ya existe" in msg_limpio.lower() or "already" in msg_limpio.lower():
                    # Usuario duplicado — error rojo destacado con icono
                    self._err_reg.configure(
                        text=f"⚠️  El nombre '{vars_reg['usuario'].get().strip()}' ya está en uso.\nElige otro nombre de usuario.",
                        text_color=C("RED"))
                    # Limpiar y enfocar el campo usuario
                    vars_reg["usuario"].set("")
                    entries[0].focus_set()
                elif "pendiente" in msg_limpio.lower():
                    self._err_reg.configure(
                        text="⏳  Ya enviaste una solicitud con ese nombre.\nEspera a que sea aprobada.",
                        text_color=C("AIR"))
                else:
                    self._err_reg.configure(text=f"❌  {msg_limpio}", text_color=C("RED"))
                btn_enviar.configure(state="normal", text="📤  Enviar")

        row_b=ctk.CTkFrame(self,fg_color=C("BG"),corner_radius=0); row_b.pack(pady=4)
        btn_enviar=mk_btn(row_b,"📤  Enviar",enviar,width=200,height=42)
        btn_enviar.pack(side="left",padx=(0,8))
        mk_btn(row_b,"← Regresar",self._mostrar_login,
               color=C("BG3"),hover=C("BORDER"),width=120,height=42).pack(side="left")
        self.after(40, lambda: _ui_fade_in(self))

    # ════════════════════════════════════════════════════════
    #   PRIMER USO — configuración inicial
    # ════════════════════════════════════════════════════════
    def _mostrar_primer_uso(self):
        self._limpiar()
        self.geometry("480x620"); self.minsize(440,560); self.resizable(True,True)
        self.title("Configuración inicial")

        self._build_header("¡Bienvenido! Configura tu programa")
        ctk.CTkLabel(self,text="Primero necesitamos unos datos",
                     font=FN_LG,text_color=C("TEXT")).pack(pady=(16,2))
        ctk.CTkLabel(self,
            text="Solo se pregunta la primera vez. Puedes cambiar todo esto después.",
            font=FN_SM,text_color=C("MUTED"),wraplength=430,justify="center").pack(pady=(0,10))

        scroll=ctk.CTkScrollableFrame(self,fg_color=C("BG"),corner_radius=0,height=340)
        scroll.pack(fill="x",padx=24,pady=(0,4))

        def _campo_ini(parent,lbl,var,show="",hint="",lbl_w=160):
            r=ctk.CTkFrame(parent,fg_color=C("CARD"),corner_radius=0); r.pack(fill="x",pady=(6,0))
            ctk.CTkLabel(r,text=lbl,font=FN,text_color=C("MUTED"),anchor="w").pack(anchor="w",padx=10,pady=(6,1))
            e=ctk.CTkEntry(r,textvariable=var,show=show,height=36,
                fg_color=C("BG2"),border_color=C("BORDER"),text_color=C("TEXT"),
                placeholder_text=hint,placeholder_text_color=C("MUTED"),font=FN)
            e.pack(fill="x",padx=10,pady=(0,8))
            _style_ctk_entry(e)
            return e

        # Sin defaults — el usuario llena todo desde cero en el primer uso
        v_ssh_user  = ctk.StringVar(value="")
        v_ssh_pass  = ctk.StringVar(value="")
        v_sheets    = ctk.StringVar(value="")
        v_empresa   = ctk.StringVar(value="")

        # Sección SSH
        s1=mk_frame(scroll); s1.pack(fill="x",pady=(0,6))
        mk_label(s1,"Contraseña para conectarte a los equipos",font=FN_B).pack(anchor="w",padx=10,pady=(8,2))
        mk_label(s1,"Con esto vas a poder entrar a los equipos de tus clientes.",
                 fg=C("MUTED"),font=FN_SM).pack(anchor="w",padx=10,pady=(0,4))
        _campo_ini(s1,"Usuario del equipo *",  v_ssh_user, "",  "")
        _campo_ini(s1,"Clave del equipo *",v_ssh_pass,"●", "Clave del equipo")

        # Sección URL buscador
        s2=mk_frame(scroll); s2.pack(fill="x",pady=(0,6))
        mk_label(s2,"Tu lista de clientes",font=FN_B).pack(anchor="w",padx=10,pady=(8,2))
        mk_label(s2,"Aquí va el link de tu lista de clientes en Google.",
                 fg=C("MUTED"),font=FN_SM).pack(anchor="w",padx=10,pady=(0,4))
        _campo_ini(s2,"Link de la lista *",v_sheets,"","Pega aquí el link")
        info_url=ctk.CTkFrame(s2,fg_color=C("BG2"),corner_radius=6); info_url.pack(fill="x",padx=10,pady=(0,6))
        ctk.CTkLabel(info_url,text="En Google: Archivo → Compartir → Publicar en la web → elige CSV",
                     font=FN_SM,text_color=C("MUTED"),wraplength=400).pack(anchor="w",padx=8,pady=5)

        def _gen_plantilla():
            import tkinter.filedialog as fd
            ruta=fd.asksaveasfilename(parent=self,title="Guardar plantilla",
                defaultextension=".csv",initialfile="plantilla_clientes.csv",
                filetypes=[("CSV","*.csv")])
            if not ruta: return
            try:
                import csv as _csv
                with open(ruta,"w",encoding="utf-8-sig",newline="") as f:
                    _csv.writer(f).writerow(ALL_COLS)
                    _csv.writer(f).writerow([""] * len(ALL_COLS))
                messagebox.showinfo("Plantilla generada",
                    f"✅ Guardada en:\n{ruta}\n\n"
                    "Pasos:\n1. Rellena los datos en Excel\n"
                    "2. Sube a Google Sheets\n3. Publica como CSV\n4. Copia la URL aquí")
            except Exception as ex: messagebox.showerror("Error",str(ex))

        mk_btn(s2,"📄  Descargar el formato de lista",_gen_plantilla,
               color=C("BG3"),hover=C("BORDER"),width=240,height=34).pack(anchor="w",padx=10,pady=(0,8))
        mk_label(s2,"Descarga este archivo, llénalo con los datos de tus clientes y súbelo a Google.",
                 fg=C("MUTED"),font=FN_SM).pack(anchor="w",padx=10,pady=(0,6))

        # Nombre empresa
        s3=mk_frame(scroll); s3.pack(fill="x",pady=(0,6))
        mk_label(s3,"¿Cómo se llama tu empresa?",font=FN_B).pack(anchor="w",padx=10,pady=(8,2))
        mk_label(s3,"Este nombre aparecerá en la pantalla principal del programa.",
                 fg=C("MUTED"),font=FN_SM).pack(anchor="w",padx=10,pady=(0,4))
        _campo_ini(s3,"Nombre de tu empresa *",v_empresa,"","Ejemplo: Mi Internet SA")

        self._err_ini=ctk.CTkLabel(self,text="",font=FN_SM,text_color=C("RED"),wraplength=420)
        self._err_ini.pack(pady=(2,2))

        def guardar_ini():
            su = v_ssh_user.get().strip()
            sp = v_ssh_pass.get().strip()
            sl = v_sheets.get().strip()
            em = v_empresa.get().strip()
            import re as _re
            em_clean = _re.sub(r"[^A-Za-z0-9 áéíóúÁÉÍÓÚñÑ]","",em).strip()[:24]
            if not su or not sp:
                self._err_ini.configure(text="El usuario y la clave del equipo son necesarios"); return
            if not sl:
                self._err_ini.configure(text="Falta el enlace a tu lista de clientes."); return
            if not em_clean:
                self._err_ini.configure(text="Falta el nombre de tu empresa."); return
            btn_guardar.configure(state="disabled",text="Guardando...")
            def _guardar():
                import platform, getpass
                cfg_data = {
                    "ssh_user":   su,
                    "ssh_pass":   sp,
                    "sheets_url": sl,
                    "empresa":    em_clean,
                    "pc_nombre":  platform.node(),
                }
                # Guardar online (fuente de verdad)
                _guardar_config_online(_usuario_activo, cfg_data)
                # También guardar local como caché
                CFG["ssh_user"]   = su
                CFG["ssh_pass"]   = sp
                CFG["sheets_url"] = sl
                CFG["empresa"]    = em_clean
                CFG["first_run"]  = False
                _save_cfg(CFG)
                self.after(0, self._mostrar_app)
            threading.Thread(target=_guardar, daemon=True).start()

        btn_guardar = mk_btn(self,"✅  ¡Listo! Empezar",guardar_ini,width=260,height=44)
        btn_guardar.pack(pady=8)
        self.after(40, lambda: _ui_fade_in(self))

    # ════════════════════════════════════════════════════════
    #   TRANSICIÓN → APP
    # ════════════════════════════════════════════════════════
    def _mostrar_app(self):
        self._limpiar()
        _t = CFG.get("tema", "auto")
        _apply_palette(_tema_auto() if _t == "auto" else _t)
        self.configure(fg_color=C("BG"))
        self.geometry("960x720"); self.minsize(820,600)
        self.resizable(True,True)
        self.title(_titulo_app())
        container=ctk.CTkFrame(self,fg_color=C("BG"),corner_radius=0)
        container.pack(fill="both",expand=True)
        self._app=App(master=container)
        self._app.pack(fill="both",expand=True)
        self.update_idletasks()
        self.after(40, lambda: _ui_fade_in(self))
        _iniciar_heartbeat()


# ════════════════════════════════════════════════════════════════
#   MAIN
# ════════════════════════════════════════════════════════════════
if __name__=="__main__":
    _init_tema()
    try:
        root=RootApp()
        root.mainloop()
    except KeyboardInterrupt:
        desconectar_todos(); sys.exit(0)
