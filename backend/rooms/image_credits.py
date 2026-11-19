"""Image credits (#336): license catalogue and helpers to collect the credits
of the images a question shows (text HTML in both content languages, option
images).

Deliberately free of module-level model imports: ``models`` imports the
license catalogue from here.
"""

from collections.abc import Iterable
from urllib.parse import unquote

from django.conf import settings

from .sanitize import clean_media_url

# key -> short label ("" = the client supplies/translates the text)
LICENSES = {
    "cc-by": "CC BY",
    "cc-by-sa": "CC BY-SA",
    "cc-by-nd": "CC BY-ND",
    "cc-by-nc": "CC BY-NC",
    "cc-by-nc-sa": "CC BY-NC-SA",
    "cc-by-nc-nd": "CC BY-NC-ND",
    "cc0": "CC0",
    "pd": "",
    "other": "",
}
LICENSE_CHOICES = [(key, key) for key in LICENSES]
VERSION_RE = r"^\d+(\.\d+)?$"

_CC_BASE = "https://creativecommons.org/"


def license_url(key, version):
    if key == "cc0":
        return _CC_BASE + "publicdomain/zero/1.0/"
    if key == "pd":
        return _CC_BASE + "publicdomain/mark/1.0/"
    if key.startswith("cc-"):
        url = f"{_CC_BASE}licenses/{key[3:]}/"
        return f"{url}{version}/" if version else url
    return ""


def license_label(key, version):
    label = LICENSES.get(key, "")
    if not label:
        return ""
    if key == "cc0":
        return f"{label} 1.0"
    return f"{label} {version}" if version else label


def has_credit(img):
    return bool(img.credit_author or img.credit_license)


def credit_dict(img, src):
    return {
        "id": img.id,
        "src": src,
        "author": img.credit_author,
        "title": img.credit_title,
        "source": img.credit_source,
        "license": img.credit_license,
        "license_label": license_label(img.credit_license, img.credit_license_version),
        "license_url": license_url(img.credit_license, img.credit_license_version),
        "version": img.credit_license_version,
        "text": img.credit_license_text,
        "has_credit": has_credit(img),
    }


def media_name_for_src(src):
    """The stored file name behind a media URL, or None.

    A src that is not one of this instance's media URLs (external, legacy,
    traversal) yields None.
    """
    if not src or clean_media_url(src) != src:
        return None
    prefix = "/" + settings.MEDIA_URL.strip("/") + "/"
    if not src.startswith(prefix):
        return None
    return unquote(src[len(prefix):]) or None


def question_image_srcs(question):
    """Image srcs of a question: text_de/text_en first, then option images;
    order of occurrence, deduped."""
    from .transfer import _html_image_srcs

    srcs = []
    for lang in ("de", "en"):
        srcs += _html_image_srcs(getattr(question, f"text_{lang}"))
    srcs += [o.image for o in question.options.all() if o.image]
    return list(dict.fromkeys(srcs))


def images_by_src(srcs: Iterable[str]):
    """{src: UploadedImage} for every resolvable src, in one query."""
    from .models import UploadedImage

    names = {}
    for src in srcs:
        name = media_name_for_src(src)
        if name:
            names[src] = name
    if not names:
        return {}
    by_name = {img.file.name: img for img in UploadedImage.objects.filter(file__in=set(names.values()))}
    return {src: by_name[n] for src, n in names.items() if n in by_name}


def credits_for_question(question, images, *, include_empty=False):
    out = []
    for src in question_image_srcs(question):
        img = images.get(src)
        if img is None or not (include_empty or has_credit(img)):
            continue
        out.append(credit_dict(img, src))
    return out


def credits_for_questions(questions):
    questions = list(questions)
    all_srcs = [s for q in questions for s in question_image_srcs(q)]
    images = images_by_src(all_srcs)
    result = {}
    for q in questions:
        entries = credits_for_question(q, images)
        if entries:
            result[q.id] = entries
    return result
