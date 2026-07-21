"""Validation et normalisation du logo atelier (upload admin)."""
from __future__ import annotations

import io
import logging

logger = logging.getLogger(__name__)

# Formats raster acceptés en entrée (ré-encodés en PNG en sortie).
_ALLOWED_FORMATS = frozenset({"PNG", "JPEG", "WEBP", "GIF", "BMP", "TIFF"})
# Plafond dimensions (anti décompression bomb + perf PDF).
_MAX_EDGE_PX = 1024
_MAX_PIXELS = 20_000_000


def process_logo_image(content: bytes, *, max_edge: int = _MAX_EDGE_PX) -> bytes:
    """
    Ouvre l'image avec Pillow, vérifie le décodage réel, retire l'EXIF,
    redimensionne si besoin, et renvoie un PNG propre.

    Lève ValueError si le fichier n'est pas une image raster sûre.
    """
    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
    except ImportError as exc:  # pragma: no cover
        raise ValueError("Pillow non installé — impossible de valider le logo") from exc

    # Défense décompression bomb (Pillow lit aussi Image.MAX_IMAGE_PIXELS).
    Image.MAX_IMAGE_PIXELS = _MAX_PIXELS

    try:
        img = Image.open(io.BytesIO(content))
        img.load()
    except UnidentifiedImageError as exc:
        raise ValueError("Fichier image illisible ou format non supporté") from exc
    except Exception as exc:
        logger.warning("Décodage logo impossible : %s", exc)
        raise ValueError("Fichier image illisible ou format non supporté") from exc

    fmt = (img.format or "").upper()
    if fmt == "JPG":
        fmt = "JPEG"
    if fmt not in _ALLOWED_FORMATS:
        raise ValueError(f"Format image refusé ({fmt or 'inconnu'}) — PNG/JPEG/WEBP uniquement")

    # Oriente selon EXIF puis supprime métadonnées en ré-encodant.
    img = ImageOps.exif_transpose(img)

    if img.mode in ("P", "LA", "PA"):
        img = img.convert("RGBA")
    elif img.mode not in ("RGB", "RGBA", "L"):
        img = img.convert("RGB")

    if max(img.size) > max_edge:
        img.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)

    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    data = out.getvalue()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Échec normalisation PNG")
    return data
