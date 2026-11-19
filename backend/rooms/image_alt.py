"""AI alt-text suggestion for uploaded images (vision model, explicit click only)."""

import io
import re

from basicbar_integrations import ai
from django.conf import settings
from PIL import Image, ImageOps

MAX_EDGE = 1024
MAX_ALT = 150

SYSTEM = (
    "You write alt text for images in teaching material. Describe the image "
    "factually and concisely in one sentence of at most 150 characters, in the "
    "requested language. Do not begin with 'Image of', 'Picture of' or similar. "
    'Reply as JSON: {"alt": "..."}.'
)
_LANGUAGES = {"de": "German", "en": "English"}
_PREFIX = re.compile(
    r"^\s*(?:Bild\s+(?:von|eines|einer)|(?:An\s+)?Image\s+of|Picture\s+of)\s+",
    re.IGNORECASE,
)


def vision_enabled() -> bool:
    return ai.is_enabled() and settings.AI_VISION


def _encode(img) -> tuple[bytes, str]:
    img.file.open("rb")
    try:
        raw = Image.open(img.file)
        raw.load()
    finally:
        img.file.close()
    pic = ImageOps.exif_transpose(raw)
    pic.thumbnail((MAX_EDGE, MAX_EDGE))
    buf = io.BytesIO()
    if pic.mode in ("RGBA", "LA") or (pic.mode == "P" and "transparency" in pic.info):
        pic.convert("RGBA").save(buf, "PNG")
        return buf.getvalue(), "image/png"
    pic.convert("RGB").save(buf, "JPEG", quality=85)
    return buf.getvalue(), "image/jpeg"


def _clean(text: str) -> str:
    text = _PREFIX.sub("", str(text or "").strip()).strip()
    if len(text) > MAX_ALT:
        cut = text[:MAX_ALT]
        space = cut.rfind(" ")
        text = (cut[:space] if space > 0 else cut).rstrip(" ,;:-")
    return text[:1].upper() + text[1:]


def suggest_alt(img, lang: str) -> str:
    data, mime = _encode(img)
    reply = ai.chat_json(
        SYSTEM,
        f"Describe this image. Language: {_LANGUAGES.get(lang, 'English')}.",
        images=[(data, mime)],
        model=settings.AI_VISION_MODEL or None,
    )
    alt = _clean(reply.get("alt") if isinstance(reply, dict) else "")
    if not alt:
        raise ai.AIError("Empty alt text")
    return alt
