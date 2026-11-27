"""Red de seguridad: ningún archivo del proyecto debe contener claves o secretos."""

import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATTERNS = {
    "clave de Google/Gemini": re.compile(r"AIza[0-9A-Za-z_\-]{35}"),
    "clave tipo sk-": re.compile(r"\bsk-[A-Za-z0-9]{24,}"),
    "token de GitHub": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    "clave AWS": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "clave privada": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
}


def tracked_files() -> list[Path]:
    try:
        out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, timeout=30, check=True)  # noqa: S607
        files = [ROOT / line for line in out.stdout.splitlines()]
        if not files:
            raise OSError("git no lista archivos")
    except (OSError, subprocess.SubprocessError):
        files = [p for p in ROOT.rglob("*") if p.is_file() and ".git" not in p.parts]
    return [
        f
        for f in files
        if f.suffix.lower() in {".py", ".md", ".txt", ".json", ".yml", ".yaml", ".toml", ".ps1", ".bat", ".cfg"}
    ]


class NoSecretsTests(unittest.TestCase):
    def test_no_secret_patterns_in_repo(self):
        hits = []
        for f in tracked_files():
            if f.name == "test_no_secrets.py" or not f.exists():
                continue
            text = f.read_text(encoding="utf-8", errors="ignore")
            hits += [f"{f.relative_to(ROOT)}: {name}" for name, rx in PATTERNS.items() if rx.search(text)]
        self.assertEqual(hits, [], "Posible secreto en el repositorio")

    def test_detector_catches_a_fake_key(self):
        fake = "AIza" + "x" * 35
        self.assertTrue(PATTERNS["clave de Google/Gemini"].search(f"key={fake}"))
        self.assertTrue(PATTERNS["clave privada"].search("-----BEGIN RSA PRIVATE KEY-----"))


if __name__ == "__main__":
    unittest.main()
