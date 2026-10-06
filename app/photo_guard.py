"""OCR-based phone-number detection in listing photos.

Anti commission-bypass: landlords must not put their phone number inside
listing photos (a photo with a number lets renters contact them directly,
skipping the 15%+15% unlock flow).

If the `tesseract` binary is not installed, every check is skipped silently
and the manual photo-review queue (Listing.photo_status) remains the
protection. OCR must NEVER break photo uploads.
"""
import logging
import os
import re
import shutil

from utils import normalize_digits

log = logging.getLogger(__name__)

# Pakistani phone shapes (mirrors the text filter in utils.find_phone_numbers).
_PHONE_PATTERNS = [
    re.compile(r"(?<!\d)03\d{9}(?!\d)"),            # 03012345678
    re.compile(r"(?<!\d)\+92\s?3\d{9}(?!\d)"),       # +92 3001234567
    re.compile(r"(?<!\d)0\d{2,4}[-\s]?\d{6,7}(?!\d)"),  # 041-8712345, 051 1234567
]


def tesseract_available():
    """True when the tesseract OCR binary is on PATH."""
    return shutil.which("tesseract") is not None


def ocr_image_text(image_path):
    """Return OCR text for an image, or None when OCR is unavailable/fails."""
    if not tesseract_available():
        log.info("photo_guard: tesseract binary not found — skipping OCR for %s",
                 image_path)
        return None
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        log.info("photo_guard: pytesseract/PIL not installed — skipping OCR")
        return None
    try:
        with Image.open(image_path) as im:
            return pytesseract.image_to_string(im)
    except Exception as exc:  # noqa: BLE001 - OCR must never break uploads
        log.warning("photo_guard: OCR failed for %s: %s", image_path, exc)
        return None


def find_phone_in_text(text):
    """Return the first phone-like match in text, else None."""
    text = normalize_digits(text)
    for pat in _PHONE_PATTERNS:
        m = pat.search(text)
        if m:
            return m.group(0)
    return None


def find_phone_in_image(image_path):
    """Return the matched phone string from a photo, or None.

    Never raises — a crashing OCR must not break uploads.
    """
    try:
        text = ocr_image_text(image_path)
    except Exception as exc:  # noqa: BLE001
        log.warning("photo_guard: OCR crashed for %s: %s", image_path, exc)
        return None
    if not text:
        return None
    return find_phone_in_text(text)


def scan_photo_paths(paths):
    """Scan saved photo files; return the first matched phone number or None."""
    for p in paths:
        if not p or not os.path.isfile(p):
            continue
        hit = find_phone_in_image(p)
        if hit:
            log.warning("photo_guard: phone-like text %r detected in %s", hit, p)
            return hit
    return None
