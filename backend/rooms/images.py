# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Normalize uploaded question images: downscale + re-encode to WebP.

Kept separate from the view so the Pillow logic is unit-testable without HTTP.
Both display contexts (beamer/presenter and the participant smartphone page)
are browsers, so WebP is safe and materially smaller than JPEG/PNG.
"""
import io
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError

_META_KEYS = ("exif", "icc_profile", "xmp")

# Upload gate before normalization (#280). Phone photos easily exceed 5 MB;
# normalize_image() downsizes them to IMAGE_MAX_EDGE and re-encodes as WebP,
# so the stored file stays small. Pillow's MAX_IMAGE_PIXELS check (raised as
# DecompressionBombError → InvalidImageError) still guards the decode.
# Shared by the upload view and the JSON import of embedded images (#290).
MAX_IMAGE_BYTES = 20 * 1024 * 1024
# Animated GIF/WebP are stored as uploaded (not transcoded), so they keep
# the old, tighter limit.
MAX_ANIMATED_IMAGE_BYTES = 5 * 1024 * 1024


class InvalidImageError(Exception):
    """Raised when the uploaded bytes cannot be decoded as an image."""


def _needs_lossless(img):
    """Diagrams/screenshots/logos → lossless; photos → lossy.

    Decided on the *original* image: transparency, or a small distinct-color
    count (flat graphics). Downscaling with LANCZOS adds interpolated colors,
    so this must run before the resize.
    """
    if img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info):
        return True
    # getcolors returns None once the image has more than `maxcolors` colors.
    return img.getcolors(maxcolors=256) is not None


def normalize_image(django_file):
    """Return a normalized WebP ContentFile, or the original file if animated.

    Raises InvalidImageError for undecodable input.
    """
    django_file.seek(0)
    try:
        img = Image.open(django_file)
        img.load()
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        SyntaxError,
        Image.DecompressionBombError,
    ) as exc:
        raise InvalidImageError(str(exc)) from exc

    # Animated images (GIF / animated WebP): pass through unchanged. The view
    # applies a tighter 5 MB limit to them; transcoding animation is out of
    # scope.
    if getattr(img, "is_animated", False):
        django_file.seek(0)
        return django_file

    # Apply and then drop EXIF orientation; strip remaining metadata.
    img = ImageOps.exif_transpose(img)
    for key in _META_KEYS:
        img.info.pop(key, None)

    lossless = _needs_lossless(img)

    # Downscale only — thumbnail() never enlarges.
    max_edge = getattr(settings, "IMAGE_MAX_EDGE", 1600)
    img.thumbnail((max_edge, max_edge), Image.LANCZOS)

    if lossless:
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA")
        save_kwargs = {"format": "WEBP", "lossless": True}
    else:
        if img.mode != "RGB":
            img = img.convert("RGB")
        quality = getattr(settings, "IMAGE_WEBP_QUALITY", 80)
        save_kwargs = {"format": "WEBP", "quality": quality, "method": 6}

    buffer = io.BytesIO()
    img.save(buffer, **save_kwargs)
    buffer.seek(0)

    stem = Path(getattr(django_file, "name", "") or "image").stem or "image"
    return ContentFile(buffer.read(), name=f"{stem}.webp")


_ANIMATED_EXTENSIONS = {"GIF": "gif", "WEBP": "webp", "PNG": "png"}


def image_format(raw):
    """Pillow's format name for image bytes, or None if undecodable."""
    try:
        with Image.open(io.BytesIO(raw)) as img:
            return img.format
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        return None


def store_image_bytes(data, filename, user):
    """Normalize image bytes from an import and save them as an upload of
    ``user``; None if they are too large or not a usable image.

    Same rules as the upload view: MAX_IMAGE_BYTES before normalizing,
    animated GIF/WebP/PNG stored untranscoded up to MAX_ANIMATED_IMAGE_BYTES.
    Shared by the JSON import (#290) and the question import (#336).
    """
    from .models import UploadedImage

    if not data or len(data) > MAX_IMAGE_BYTES:
        return None
    stem = Path(filename or "").stem[:80] or "image"
    original = ContentFile(data, name=f"{stem}.img")
    try:
        normalized = normalize_image(original)
    except InvalidImageError:
        return None
    if normalized is original:
        if len(data) > MAX_ANIMATED_IMAGE_BYTES:
            return None
        ext = _ANIMATED_EXTENSIONS.get(image_format(data))
        if ext is None:
            return None
        normalized = ContentFile(data, name=f"{stem}.{ext}")
    uploaded = UploadedImage(uploader=user)
    uploaded.file.save(normalized.name, normalized, save=True)
    return uploaded
