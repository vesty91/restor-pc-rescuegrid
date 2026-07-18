#!/usr/bin/env python3
"""Génère un ZIP de release propre à partir du fichier VERSION.

Exclusions : .venv, .env, .secret_key, bases, storage, volumes, logs,
__pycache__, .git, et autres artefacts locaux.

Usage (depuis la racine du projet) :
  python scripts/make_release_zip.py
"""
from __future__ import annotations

import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip() or "0.0.0-dev"
OUT = ROOT / f"restor-pc-rescuegrid-v{VERSION}.zip"

SKIP_DIR_NAMES = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    "volumes",
    "storage",
    "logs",
    "node_modules",
    ".idea",
    ".vscode",
}
SKIP_FILE_NAMES = {
    ".env",
    ".secret_key",
    ".last_deployed_commit",
}
SKIP_SUFFIXES = {".db", ".pyc", ".log", ".zip", ".7z"}


def should_skip(path: Path) -> bool:
    rel_parts = path.relative_to(ROOT).parts
    if any(part in SKIP_DIR_NAMES for part in rel_parts[:-1]):
        return True
    if path.name in SKIP_FILE_NAMES:
        return True
    if path.suffix.lower() in SKIP_SUFFIXES:
        return True
    if path.name.startswith("Intervention_"):
        return True
    return False


def main() -> None:
    if OUT.exists():
        OUT.unlink()
    count = 0
    with zipfile.ZipFile(OUT, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            if path.resolve() == OUT.resolve():
                continue
            if should_skip(path):
                continue
            arcname = path.relative_to(ROOT).as_posix()
            zf.write(path, arcname)
            count += 1
    print(f"OK : {OUT.name} ({count} fichiers)")


if __name__ == "__main__":
    main()
