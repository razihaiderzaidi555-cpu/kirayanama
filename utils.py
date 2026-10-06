"""Shared helpers: secure image upload with resize + phone-number detection."""
import os
import re
import uuid
from werkzeug.utils import secure_filename
from PIL import Image

ALLOWED_EXT = {"png", "jpg", "jpeg", "webp"}
MAX_DIM = 1280

# Urdu / Arabic-Indic digits -> ASCII, so ۰۳۰۱۲۳۴۵۶۷۸ can't dodge the filter.
_URDU_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

_PHONE_PATTERNS = [
    # Pakistani mobile: 0301-2345678, 0301 2345678, 03012345678
    re.compile(r"(?<!\d)03\d{2}[\s\-]?\(?\d{3}\)?[\s\-]?\d{4}(?!\d)"),
    # International: +92 301 2345678, 0092-301-2345678
    re.compile(r"(?<!\d)(?:\+92|0092)[\s\-]?3\d{2}[\s\-]?\d{3}[\s\-]?\d{4}(?!\d)"),
]


def normalize_digits(text):
    """Map Urdu/Arabic-Indic digits to ASCII so filters can't be dodged."""
    return (text or "").translate(_URDU_DIGITS)


def find_phone_numbers(text):
    """Return a list of phone-number-like strings found in text (deduped).

    Used to auto-reject listings that try to bypass the contact-unlock flow
    by hiding a phone number in the title/description.
    """
    text = normalize_digits(text)
    found = []
    for pat in _PHONE_PATTERNS:
        for m in pat.finditer(text):
            num = m.group(0)
            if num not in found:
                found.append(num)
    return found


def save_upload(file_storage, subdir, upload_root):
    """Save an uploaded image, resize if huge. Returns filename or raises ValueError."""
    if not file_storage or not file_storage.filename:
        raise ValueError("no file")
    ext = file_storage.filename.rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_EXT:
        raise ValueError("only png/jpg/webp allowed")
    name = f"{uuid.uuid4().hex}.{ext}"
    dest_dir = os.path.join(upload_root, subdir)
    os.makedirs(dest_dir, exist_ok=True)
    path = os.path.join(dest_dir, secure_filename(name))
    file_storage.save(path)
    try:
        img = Image.open(path)
        img.thumbnail((MAX_DIM, MAX_DIM))
        img.save(path)
    except Exception:
        pass
    return name
