import os
import shutil
import subprocess
import time

from .base import BasePlatformAdapter


class WindowsPlatformAdapter(BasePlatformAdapter):
    BROWSERS = [
        ("Google Chrome", "chrome.exe", "chromium", [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]),
        ("Microsoft Edge", "msedge.exe", "chromium", [
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        ]),
        ("Firefox", "firefox.exe", "firefox", [
            r"C:\Program Files\Mozilla Firefox\firefox.exe",
            r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
        ]),
        ("Brave", "brave.exe", "chromium", [
            r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        ]),
    ]

    def is_admin(self):
        try:
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False

    def set_system_socks_proxy(self, socks_port):
        try:
            import ctypes
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                0,
                winreg.KEY_SET_VALUE,
            )
            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, f"socks=127.0.0.1:{socks_port}")
            winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, "localhost;127.0.0.1;<local>")
            winreg.CloseKey(key)
            ctypes.windll.wininet.InternetSetOptionW(0, 39, 0, 0)
            ctypes.windll.wininet.InternetSetOptionW(0, 37, 0, 0)
            self._log(f"Proxy sistema configurado: socks=127.0.0.1:{socks_port}")
            return True
        except Exception as exc:
            self._log(f"Error configurando proxy sistema: {exc}")
            return False

    def clear_system_proxy(self):
        try:
            import ctypes
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                0,
                winreg.KEY_SET_VALUE,
            )
            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)
            winreg.CloseKey(key)
            ctypes.windll.wininet.InternetSetOptionW(0, 39, 0, 0)
            ctypes.windll.wininet.InternetSetOptionW(0, 37, 0, 0)
            self._log("Proxy sistema desactivado")
            return True
        except Exception as exc:
            self._log(f"Error limpiando proxy sistema: {exc}")
            return False

    def detect_browsers(self):
        active = set(self._list_process_names())
        result = []
        for name, exe, kind, paths in self.BROWSERS:
            for p in paths:
                p = os.path.expandvars(p)
                if os.path.exists(p):
                    result.append(
                        {"nombre": name, "exe": exe, "tipo": kind, "path": p, "en_uso": exe.lower() in active}
                    )
                    break
        return result

    def open_browser(self, url, nav, socks_port, create_firefox_profile=None):
        if not url.startswith("http"):
            url = f"http://{url}"

        if nav.get("en_uso") and nav.get("exe"):
            try:
                subprocess.run(["taskkill", "/F", "/IM", nav["exe"]], capture_output=True, timeout=3)
                time.sleep(1.2)
            except Exception:
                pass

        if self.is_admin() and self.set_system_socks_proxy(socks_port):
            if nav["tipo"] == "chromium":
                cmd = [
                    nav["path"],
                    "--new-window",
                    url,
                    "--ignore-certificate-errors",
                    "--allow-running-insecure-content",
                ]
            elif nav["tipo"] == "firefox":
                cmd = [nav["path"], "-new-window", url]
            else:
                cmd = [nav["path"], url]
            subprocess.Popen(cmd)
            return True

        if nav["tipo"] == "chromium":
            cmd = [
                nav["path"],
                f"--proxy-server=socks5://127.0.0.1:{socks_port}",
                "--proxy-bypass-list=<-loopback>",
                "--ignore-certificate-errors",
                "--ignore-urlfetcher-cert-requests",
                "--disable-web-security",
                "--allow-running-insecure-content",
                "--new-window",
                url,
            ]
        elif nav["tipo"] == "firefox" and create_firefox_profile:
            profile = create_firefox_profile(socks_port)
            cmd = [nav["path"], "-profile", profile, "-no-remote", "-new-instance", url]
        else:
            cmd = [nav["path"], url]
        subprocess.Popen(cmd)
        return True
