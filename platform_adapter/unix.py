import os
import shutil
import subprocess

from .base import BasePlatformAdapter


class UnixPlatformAdapter(BasePlatformAdapter):
    CANDIDATES = [
        ("Google Chrome", "google-chrome", "chromium"),
        ("Chromium", "chromium", "chromium"),
        ("Microsoft Edge", "microsoft-edge", "chromium"),
        ("Brave", "brave-browser", "chromium"),
        ("Firefox", "firefox", "firefox"),
    ]

    def is_admin(self):
        try:
            return os.geteuid() == 0
        except Exception:
            return False

    def detect_browsers(self):
        active = set(self._list_process_names())
        result = []
        for name, exe, kind in self.CANDIDATES:
            path = shutil.which(exe)
            if path:
                result.append(
                    {"nombre": name, "exe": os.path.basename(path), "tipo": kind, "path": path, "en_uso": exe in active}
                )
        return result

    def open_browser(self, url, nav, socks_port, create_firefox_profile=None):
        if not url.startswith("http"):
            url = f"http://{url}"

        if nav["tipo"] == "chromium":
            cmd = [nav["path"], f"--proxy-server=socks5://127.0.0.1:{socks_port}", "--new-window", url]
        elif nav["tipo"] == "firefox" and create_firefox_profile:
            profile = create_firefox_profile(socks_port)
            cmd = [nav["path"], "-profile", profile, "-no-remote", "-new-instance", url]
        else:
            cmd = [nav["path"], url]
        subprocess.Popen(cmd)
        return True
