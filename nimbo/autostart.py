"""Fase 6: iniciar Nimbo con Windows (clave Run del usuario; no pide administrador)."""

from __future__ import annotations

import os
import sys

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE = "Nimbo"


def command_line() -> str:
    if getattr(sys, "frozen", False):  # empaquetado con PyInstaller
        return f'"{sys.executable}" --tray'
    exe = sys.executable
    pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    return f'"{pyw if os.path.exists(pyw) else exe}" -m nimbo ui --tray'


def is_enabled() -> bool:
    if os.name != "nt":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, VALUE)
        return True
    except OSError:
        return False


def set_enabled(on: bool) -> bool:
    """True si quedó como se pidió."""
    if os.name != "nt":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if on:
                winreg.SetValueEx(k, VALUE, 0, winreg.REG_SZ, command_line())
            else:
                try:
                    winreg.DeleteValue(k, VALUE)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False
