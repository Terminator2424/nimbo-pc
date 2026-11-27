"""Fase 2: reglas que deciden a dónde va cada archivo y generan el PLAN (sin mover nada).

Esquema de carpetas (propuesto, 'mixto'):
  Imágenes\\Capturas\\AAAA-MM        capturas de pantalla
  Imágenes\\WhatsApp\\AAAA-MM        fotos de WhatsApp   |  Videos\\WhatsApp\\AAAA-MM
  Imágenes\\Fotos\\AAAA\\AAAA-MM     fotos de cámara     |  Imágenes\\Otras imágenes\\AAAA
  Videos\\AAAA   Música\\Sin clasificar
  Documentos\\PDFs\\AAAA   Documentos\\Textos   Documentos\\Libros
  Documentos\\Hojas de cálculo   Documentos\\Presentaciones
  Descargas\\Instaladores   Descargas\\Comprimidos
Lo que no tiene regla clara (código, modelos, emuladores, atajos, temporales...) NO se mueve.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from . import config as cfg
from .pathutil import clean_path, is_under, norm
from .learning import match_rule
from .protect import Protection
from .scanner import _CLOUD_MASK, _is_link, classify, origin_hint

MIN_CONFIDENCE = 0.6
SKIP_NAMES = {"desktop.ini", "thumbs.db", ".ds_store"}
_DATE_RE = re.compile(r"(20\d{2})[-_.]?(0[1-9]|1[0-2])[-_.]?(0[1-9]|[12]\d|3[01])")


@dataclass
class Layout:
    pictures: Path
    videos: Path
    music: Path
    documents: Path
    downloads: Path
    quarantine: Path
    projects: Path

    @classmethod
    def from_system(cls) -> Layout:
        k = cfg.known_dir
        # Proyectos fuera de Documentos: allí OneDrive los sincronizaría (node_modules, .git...)
        return cls(
            k("Pictures"),
            k("Videos"),
            k("Music"),
            k("Documents"),
            k("Downloads"),
            cfg.data_dir() / "cuarentena",
            Path.home() / "Proyectos",
        )

    @classmethod
    def from_root(cls, root: Path) -> Layout:  # para el laboratorio / pruebas
        r = Path(root)
        return cls(
            r / "Imagenes",
            r / "Videos",
            r / "Musica",
            r / "Documentos",
            r / "Descargas",
            r / "_Cuarentena",
            r / "Proyectos",
        )


@dataclass
class Move:
    src: str
    dst: str
    reason: str
    confidence: float
    category: str
    size: int = 0
    mtime_ns: int = 0


@dataclass
class Plan:
    moves: list[Move] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    dry_run: bool = True

    def to_json(self) -> str:
        return json.dumps(
            {
                "version": 1,
                "created": datetime.now().isoformat(timespec="seconds"),
                "dry_run": self.dry_run,
                "moves": [asdict(m) for m in self.moves],
                "skipped": self.skipped,
            },
            indent=2,
            ensure_ascii=False,
        )

    @classmethod
    def from_json(cls, text: str) -> Plan:
        d = json.loads(text)
        return cls([Move(**m) for m in d["moves"]], d.get("skipped", []), d.get("dry_run", True))


def date_from_name(name: str) -> datetime | None:
    m = _DATE_RE.search(name)
    if not m:
        return None
    try:
        return datetime(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return None


def decide(name: str, mtime_ns: int, layout: Layout, inbox_kind: str):
    """(destino, motivo, confianza, categoría) o (None, motivo_de_omisión, 0, categoría)."""
    ext, cat = classify(name)
    hint = origin_hint(name)
    dt = date_from_name(name) or datetime.fromtimestamp(mtime_ns / 1e9)
    y, ym = f"{dt.year}", f"{dt.year}-{dt.month:02d}"
    L = layout
    if cat == "imagenes":
        if ext in (".svg", ".ico"):
            return None, "recurso gráfico, no es una foto", 0, cat
        if hint == "captura":
            return L.pictures / "Capturas" / ym, "nombre de captura de pantalla", 0.95, cat
        if hint == "whatsapp":
            return L.pictures / "WhatsApp" / ym, "nombre típico de WhatsApp", 0.95, cat
        if hint == "camara":
            return L.pictures / "Fotos" / y / ym, "nombre típico de cámara", 0.9, cat
        return L.pictures / "Otras imágenes" / y, "imagen sin origen claro", 0.7, cat
    if cat == "videos":
        if hint == "whatsapp":
            return L.videos / "WhatsApp" / ym, "nombre típico de WhatsApp", 0.95, cat
        return L.videos / y, "extensión de video", 0.85, cat
    if cat == "musica":
        return L.music / "Sin clasificar", "extensión de audio (artista/álbum llega en la Fase 5)", 0.8, cat
    if cat == "documentos":
        if ext == ".pdf":
            return L.documents / "PDFs" / y, "extensión .pdf", 0.9, cat
        if ext in (".epub", ".mobi"):
            return L.documents / "Libros", "libro electrónico", 0.85, cat
        return L.documents / "Textos", f"documento {ext}", 0.8, cat
    if cat == "hojas_de_calculo":
        return L.documents / "Hojas de cálculo", f"hoja de cálculo {ext}", 0.85, cat
    if cat == "presentaciones":
        return L.documents / "Presentaciones", f"presentación {ext}", 0.85, cat
    if cat == "comprimidos":
        return L.downloads / "Comprimidos", f"archivo comprimido {ext}", 0.8, cat
    if cat == "ejecutables":
        if inbox_kind != "downloads":
            return None, "ejecutable en el Escritorio: puede ser un programa", 0, cat
        if ext in (".exe", ".msi", ".msix", ".appx", ".apk"):
            return L.downloads / "Instaladores", f"instalador {ext} en Descargas", 0.8, cat
        return None, "script: se revisa a mano", 0, cat
    if cat == "temporales":
        return None, "descarga incompleta o temporal", 0, cat
    return None, f"sin regla clara ({cat}): se revisa a mano", 0, cat


def _inbox_kind(inbox: Path, layout: Layout) -> str:
    return "downloads" if norm(str(inbox)) == norm(str(layout.downloads)) else "desktop"


def build_plan(
    inbox: list[Path],
    layout: Layout,
    protection: Protection,
    deep: bool = False,
    settle_seconds: float = 60,
    now: float | None = None,
    rules: list[dict] | None = None,
) -> Plan:
    """Lee las carpetas de entrada en vivo (solo lectura) y propone movimientos."""
    plan = Plan()
    now = now if now is not None else time.time()
    dest_roots = [norm(str(p)) for p in (layout.pictures, layout.videos, layout.music, layout.documents)]
    dest_roots += [norm(str(layout.downloads / s)) for s in ("Instaladores", "Comprimidos")]

    def skip(path: str, why: str, cat: str | None = None) -> None:
        item = {"src": clean_path(path), "reason": why}
        if cat:
            item["category"] = cat
        plan.skipped.append(item)

    for box in inbox:
        if not box.is_dir():
            continue
        kind = _inbox_kind(box, layout)
        stack = [str(box)]
        while stack:
            cur = stack.pop()
            try:
                entries = list(os.scandir(cur))
            except OSError as exc:
                skip(cur, f"no se pudo leer: {exc}")
                continue
            for e in entries:
                full = os.path.join(cur, e.name)
                try:
                    if _is_link(e):
                        skip(full, "enlace simbólico o unión: no se sigue")
                        continue
                    if e.is_dir(follow_symlinks=False):
                        if (
                            deep
                            and not any(is_under(norm(full), d) for d in dest_roots)
                            and not protection.blocked_reason(os.path.join(full, "x"), str(box))
                        ):
                            stack.append(full)
                        continue
                    if not e.is_file(follow_symlinks=False):
                        continue
                    if e.name.lower() in SKIP_NAMES or e.name.startswith("."):
                        continue
                    st = e.stat(follow_symlinks=False)
                except OSError as err:
                    skip(full, f"no se pudo leer: {err}")
                    continue
                if getattr(st, "st_file_attributes", 0) & _CLOUD_MASK:
                    skip(full, "solo en la nube (moverlo lo descargaría)")
                    continue
                why = protection.blocked_reason(full, str(box))
                if why:
                    skip(full, why)
                    continue
                if now - st.st_mtime_ns / 1e9 < settle_seconds:
                    skip(full, "muy reciente: puede estar descargándose o en uso")
                    continue
                rule_dest = match_rule(rules, e.name) if rules else None
                if rule_dest:
                    dst_dir, reason, conf, cat = (
                        Path(rule_dest),
                        "regla tuya o aprendida de tus correcciones",
                        0.95,
                        classify(e.name)[1],
                    )
                else:
                    dst_dir, reason, conf, cat = decide(e.name, st.st_mtime_ns, layout, kind)
                if dst_dir is None:
                    skip(full, reason, cat)
                    continue
                if conf < MIN_CONFIDENCE:
                    skip(full, f"confianza baja ({conf})")
                    continue
                if norm(cur) == norm(str(dst_dir)):
                    continue  # ya está en su sitio
                plan.moves.append(
                    Move(
                        clean_path(full),
                        clean_path(str(dst_dir / e.name)),
                        reason,
                        conf,
                        cat,
                        st.st_size,
                        st.st_mtime_ns,
                    )
                )
    plan.moves.sort(key=lambda m: (m.category, m.src))
    return plan
