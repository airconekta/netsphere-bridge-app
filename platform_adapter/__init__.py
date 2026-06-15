import sys

from .base import BasePlatformAdapter
from .unix import UnixPlatformAdapter
from .windows import WindowsPlatformAdapter


def get_platform_adapter(log_func=None):
    if sys.platform.startswith("win"):
        return WindowsPlatformAdapter(log_func=log_func)
    if sys.platform.startswith("linux") or sys.platform == "darwin":
        return UnixPlatformAdapter(log_func=log_func)
    return BasePlatformAdapter(log_func=log_func)
