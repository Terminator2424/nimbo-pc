"""Guarda la clave de API cifrada con la cuenta de Windows (DPAPI): no queda en texto plano en config.json.

Orden de búsqueda: variable de entorno NIMBO_API_KEY -> clave cifrada en config.json (solo Windows).
En otros sistemas no se guarda nada: se usa la variable de entorno.
"""

from __future__ import annotations

import base64
import ctypes
import os
from typing import Protocol

from . import config as cfg

ENV_VAR = "NIMBO_API_KEY"


class Backend(Protocol):
    def protect(self, data: bytes) -> bytes: ...
    def unprotect(self, data: bytes) -> bytes: ...


class DPAPIBackend:
    """Windows Data Protection API: solo el mismo usuario de Windows en este PC puede descifrar."""

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]  # noqa: RUF012

    def _blob(self, data: bytes):
        buf = ctypes.create_string_buffer(data, len(data))
        return self._Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    def _call(self, fn_name: str, data: bytes) -> bytes:
        crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
        blob_in, _keepalive = self._blob(data)
        blob_out = self._Blob()
        fn = getattr(crypt32, fn_name)
        ok = (
            fn(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out))
            if fn_name == "CryptUnprotectData"
            else fn(ctypes.byref(blob_in), "Nimbo", None, None, None, 0, ctypes.byref(blob_out))
        )
        if not ok:
            raise OSError(f"{fn_name} falló")
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            kernel32.LocalFree(blob_out.pbData)

    def protect(self, data: bytes) -> bytes:
        return self._call("CryptProtectData", data)

    def unprotect(self, data: bytes) -> bytes:
        return self._call("CryptUnprotectData", data)


def default_backend() -> Backend | None:
    return DPAPIBackend() if os.name == "nt" else None


def get_key(backend: Backend | None = None) -> str | None:
    env = os.environ.get(ENV_VAR, "").strip()
    if env:
        return env
    backend = backend or default_backend()
    blob = (cfg.load_user_config().get("ai") or {}).get("key_enc")
    if not blob or backend is None:
        return None
    try:
        return backend.unprotect(base64.b64decode(blob)).decode("utf-8")
    except (OSError, ValueError):
        return None


def has_key(backend: Backend | None = None) -> bool:
    return bool(get_key(backend))


def set_key(key: str, backend: Backend | None = None) -> bool:
    """True si se guardó cifrada. False si este sistema no tiene cifrado (usa la variable de entorno)."""
    backend = backend or default_backend()
    if backend is None:
        return False
    ai = dict(cfg.load_user_config().get("ai") or {})
    ai["key_enc"] = base64.b64encode(backend.protect(key.strip().encode("utf-8"))).decode("ascii")
    cfg.save_user_config({"ai": ai})
    return True


def clear_key() -> None:
    ai = dict(cfg.load_user_config().get("ai") or {})
    ai.pop("key_enc", None)
    cfg.save_user_config({"ai": ai})
