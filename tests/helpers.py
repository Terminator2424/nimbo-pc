"""Ayudas compartidas por las pruebas."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from nimbo import db as database
from nimbo.lab import create_lab
from nimbo.scanner import ScanOptions, scan


class TempCase(unittest.TestCase):
    def setUp(self) -> None:
        # Registra toda conexión SQLite que se abra y, al terminar la prueba, exige que estén cerradas:
        # en Windows una base abierta impide borrar la carpeta temporal y la prueba falla.
        self._conns: list[sqlite3.Connection] = []
        real_connect = database.connect

        def tracking(*a, **k):
            c = real_connect(*a, **k)
            self._conns.append(c)
            return c

        patcher = mock.patch.object(database, "connect", tracking)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._assert_no_open_connections)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.work = self.tmp / "work"  # lo que se escanea
        self.work.mkdir()
        self.conn = database.connect(self.tmp / "test.db")
        self.addCleanup(self.conn.close)

    def _assert_no_open_connections(self) -> None:
        leaked = []
        for c in self._conns:
            try:
                c.execute("select 1")
                leaked.append(c)
            except sqlite3.ProgrammingError:
                pass  # cerrada: correcto
        for c in leaked:  # se cierran para que la limpieza pueda continuar, y se reporta el fallo
            c.close()
        self.assertEqual(leaked, [], "Una conexión SQLite quedó abierta (en Windows bloquea el borrado de archivos)")

    def scan_dir(self, root: Path | None = None, **kw):
        return scan(self.conn, ScanOptions(roots=[root or self.work], **kw))

    def make_lab(self) -> Path:
        lab = self.work / "lab"
        create_lab(lab)
        return lab

    def write(self, rel: str, data: bytes = b"x") -> Path:
        p = self.work / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return p
