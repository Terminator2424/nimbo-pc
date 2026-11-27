"""Laboratorio: carpeta desordenada FALSA para probar sin riesgo.

Solo escribe en una carpeta nueva/vacía o en un laboratorio previo (tiene marcador).
"""

from __future__ import annotations

import os
import random
import shutil
from datetime import datetime
from pathlib import Path

MARKER = ".nimbo-lab"


class LabError(Exception):
    pass


def create_lab(path: str | Path, force: bool = False, seed: int = 42) -> dict[str, int]:
    root = Path(path)
    if root.exists() and any(root.iterdir()):
        if not (root / MARKER).exists():
            raise LabError(f"{root} no está vacía y no es un laboratorio de Nimbo. Elige una carpeta nueva.")
        if not force:
            raise LabError(f"{root} ya es un laboratorio. Usa --force para recrearlo.")
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    (root / MARKER).write_text("Carpeta de pruebas de Nimbo. Se puede borrar.\n", encoding="utf-8")

    rng = random.Random(seed)  # nosec B311 - datos falsos reproducibles, sin uso criptográfico
    counter = {"files": 0, "bytes": 0}

    def put(rel: str, data: bytes, when: tuple[int, int, int] | None = None) -> None:
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        if when:
            ts = datetime(when[0], when[1], when[2], 12, 0).timestamp()
            os.utime(target, (ts, ts))
        counter["files"] += 1
        counter["bytes"] += len(data)

    def blob(n: int) -> bytes:
        return rng.randbytes(n)

    foto = blob(180_000)
    tarea = b"%PDF-1.4 tarea de calculo " + blob(40_000)
    cancion = blob(300_000)
    notas = ("notas de clase\n" * 200).encode()

    put("Descargas/VSCodeSetup-x64.exe", blob(250_000), (2025, 9, 3))
    put("Descargas/SteamSetup.exe", blob(120_000), (2024, 2, 11))
    put("Descargas/Captura de pantalla 2025-03-01 120000.png", blob(90_000), (2025, 3, 1))
    put("Descargas/Screenshot_2025-04-02-18-20-11.png", blob(80_000), (2025, 4, 2))
    put("Descargas/IMG-20250301-WA0012.jpg", foto, (2025, 3, 1))
    put("Descargas/IMG-20250301-WA0012 (1).jpg", foto, (2025, 3, 2))
    put("Descargas/tarea.pdf", tarea, (2025, 5, 10))
    put("Descargas/tarea (1).pdf", tarea, (2025, 5, 11))
    put("Descargas/cancion_descargada.mp3", cancion, (2023, 7, 7))
    put("Descargas/pelicula.mkv.crdownload", blob(60_000), (2024, 12, 1))
    put("Descargas/proyecto_final.zip", blob(200_000), (2025, 6, 20))
    put("Descargas/vacio.txt", b"", (2025, 1, 1))
    put("Descargas/archivo_sin_extension", blob(2_000), (2022, 1, 1))

    put("Escritorio/foto_perfil.jpg", foto, (2024, 8, 8))
    put("Escritorio/notas.txt", notas, (2025, 1, 15))
    put("Escritorio/Copia de notas.txt", notas, (2025, 1, 16))
    put("Escritorio/Steam.lnk", b"lnk" * 100, (2024, 2, 12))

    put("Documentos/Universidad/calculo/parcial1.docx", blob(35_000), (2025, 4, 1))
    put("Documentos/Universidad/calculo/formulas.pdf", blob(30_000), (2025, 3, 20))
    put("Documentos/Universidad/fisica/lab1.xlsx", blob(12_000), (2025, 4, 8))
    put("Documentos/Universidad/presentacion.pptx", blob(150_000), (2025, 6, 2))
    put("Documentos/Finanzas/presupuesto.xlsx", blob(12_800), (2025, 2, 1))
    put("Documentos/CV_2025.docx", blob(28_000), (2025, 1, 5))
    put("Documentos/contrato.pdf", blob(60_000), (2024, 11, 30))
    put("Documentos/recibo_luz.pdf", blob(25_000), (2025, 7, 1))

    put("Imagenes/Fotos de WhatsApp/IMG-20250301-WA0012.jpg", foto, (2025, 3, 1))
    put("Imagenes/DSC_0042.jpg", blob(250_000), (2023, 12, 25))
    put("Imagenes/PXL_20240615_101010.jpg", blob(300_000), (2024, 6, 15))
    put("Imagenes/Screenshot 2025-02-02.png", blob(70_000), (2025, 2, 2))
    put("Imagenes/Vacaciones/playa1.jpg", blob(220_000), (2024, 1, 10))
    put("Imagenes/Vacaciones/playa2.jpg", blob(210_000), (2024, 1, 10))

    put("Videos/clip_gol.mp4", blob(700_000), (2024, 5, 5))
    put("Videos/tutorial.mkv", blob(850_000), (2025, 2, 20))

    put("Musica/Artista - cancion1.mp3", blob(320_000), (2022, 3, 3))
    put("Musica/Artista - cancion2.mp3", blob(340_000), (2022, 3, 3))
    put("Musica/duplicada/cancion_descargada.mp3", cancion, (2023, 7, 8))

    put("Juegos/Emuladores/roms/juego.gba", blob(64_000), (2023, 1, 1))
    put("IA/modelos/modelo-chico.gguf", blob(500_000), (2025, 8, 8))

    put("Proyectos/mi-app/package.json", b'{"name":"mi-app"}', (2025, 5, 1))
    put("Proyectos/mi-app/index.js", b"console.log(1)", (2025, 5, 1))
    put("Proyectos/mi-app/node_modules/lib/x.js", blob(5_000), (2025, 5, 1))
    return counter
