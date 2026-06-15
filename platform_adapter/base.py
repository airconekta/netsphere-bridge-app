import os
import subprocess
import sys
import webbrowser


class BasePlatformAdapter:
    def __init__(self, log_func=None):
        self._log = log_func or (lambda msg: None)

    def is_admin(self):
        return False

    def get_hosts_path(self):
        return r"C:\Windows\System32\drivers\etc\hosts" if os.name == "nt" else "/etc/hosts"

    def add_hosts_alias(self, ip, alias, marker):
        hosts_file = self.get_hosts_path()
        try:
            with open(hosts_file, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            filtered = [line for line in lines if marker not in line]
            filtered.append(f"{ip}  {alias}  {marker}\n")
            with open(hosts_file, "w", encoding="utf-8") as f:
                f.writelines(filtered)
            return True
        except Exception as exc:
            self._log(f"No se pudo escribir hosts ({hosts_file}): {exc}")
            return False

    def clear_hosts_alias(self, marker):
        hosts_file = self.get_hosts_path()
        try:
            with open(hosts_file, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            filtered = [line for line in lines if marker not in line]
            if len(filtered) != len(lines):
                with open(hosts_file, "w", encoding="utf-8") as f:
                    f.writelines(filtered)
            return True
        except Exception:
            return False

    def set_system_socks_proxy(self, socks_port):
        return False

    def clear_system_proxy(self):
        return False

    def _list_process_names(self):
        try:
            if os.name == "nt":
                out = subprocess.check_output(
                    ["tasklist", "/fo", "csv", "/nh"], text=True, stderr=subprocess.DEVNULL
                )
                return [line.split(",")[0].strip('"').lower() for line in out.splitlines() if line]
            out = subprocess.check_output(["ps", "-A", "-o", "comm="], text=True, stderr=subprocess.DEVNULL)
            return [os.path.basename(line.strip()).lower() for line in out.splitlines() if line.strip()]
        except Exception:
            return []

    def detect_browsers(self):
        return []

    def open_browser(self, url, nav, socks_port, create_firefox_profile=None):
        if not url.startswith("http"):
            url = f"http://{url}"
        try:
            webbrowser.open(url)
            return True
        except Exception as exc:
            self._log(f"No se pudo abrir navegador por fallback: {exc}")
            return False
