"""Automatic payment-screenshot verification (anti-fraud, zero admin workload).

When a party uploads a payment screenshot, OCR runs on it and that side's
payment is AUTO-APPROVED only when ALL of these hold:

  1. the expected 15%-commission amount appears in the OCR text
     (digits matched exactly after Urdu/Arabic-Indic digit normalization),
  2. one of Razi's own payment identifiers appears
     (easypaisa/jazzcash/upaisa number or HBL account, from admin settings),
  3. a transaction ID is extracted AND was never used before
     (UsedTrx table kills replay fraud: one screenshot can't unlock two
     sides/deals).

Anything else -> 'needs_review' with a reason code, shown in the existing
admin payments queue (/admin/payments).

OCR must NEVER break uploads: on any crash the screenshot is accepted for
manual review (fail-open -> 'needs_review' / 'ocr_error').

RESIDUAL RISK (honest): a fully photoshopped fake screenshot can still pass
OCR — the text is genuinely "there". True bank-level verification needs a
JazzCash/EasyPaisa merchant API account later.
"""
import logging
import re
import shutil

from utils import normalize_digits

log = logging.getLogger(__name__)

# Reason codes returned on failure (rendered via t('reason_' + code)).
REASONS = ("amount_mismatch", "identifier_missing", "trx_missing",
           "trx_reused", "ocr_error")

# Transaction-ID shapes seen on JazzCash/EasyPaisa/UPaisa receipts.
_TRX_PATTERNS = [
    re.compile(
        r"(?:trx\s*id|transaction\s*(?:id|no\.?|number)|"
        r"reference\s*(?:no\.?|number|id)|ref\.?\s*(?:no\.?|number)|tid)"
        r"\s*[:#\-]?\s*(\d{6,})",
        re.IGNORECASE),
]


def tesseract_available():
    """True when the tesseract OCR binary is on PATH."""
    return shutil.which("tesseract") is not None


def ocr_text(image_path):
    """Return OCR text for an image, or None when unavailable. Never raises."""
    if not tesseract_available():
        return None
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(image_path) as im:
            return pytesseract.image_to_string(im)
    except Exception as exc:  # noqa: BLE001 - OCR must never break uploads
        log.warning("payment_guard: OCR failed for %s: %s", image_path, exc)
        return None


def find_amount(text, expected_amount):
    """True when the exact expected amount appears as a full number in text.

    Commas are stripped ("2,250" -> "2250"); substring matches of longer
    numbers ("12250" vs 2250) do NOT count.
    """
    try:
        want = str(int(expected_amount))
    except (TypeError, ValueError):
        return False
    text = normalize_digits(text or "")
    for group in re.findall(r"[\d,]+", text):
        if group.replace(",", "") == want:
            return True
    return False


def find_identifier(text, identifiers):
    """Return the first own payment identifier found in text, else None.

    Both sides are flattened (spaces/dashes removed) so "0311-5021212"
    matches the stored "03115021212".
    """
    text = normalize_digits(text or "")
    flat = re.sub(r"[\s\-,]", "", text)
    for ident in identifiers or []:
        ident = re.sub(r"[\s\-]", "", normalize_digits(str(ident or "")))
        if not ident:
            continue
        if re.search(r"(?<!\d)" + re.escape(ident) + r"(?!\d)", flat):
            return ident
    return None


def extract_trx_id(text):
    """Return the first transaction ID found in text, else None."""
    text = normalize_digits(text or "")
    for pat in _TRX_PATTERNS:
        m = pat.search(text)
        if m:
            return m.group(1)
    return None


def verify_payment_screenshot(image_path, expected_amount, identifiers):
    """Verify one payment screenshot.

    Returns (ok, trx_id, reason): ok=True only when amount + identifier +
    fresh transaction ID all hold. Never raises — any failure, including an
    OCR crash, returns ok=False with a reason code (fail-open to manual
    review).
    """
    try:
        text = ocr_text(image_path)
    except Exception as exc:  # noqa: BLE001
        log.warning("payment_guard: OCR crashed for %s: %s", image_path, exc)
        return False, None, "ocr_error"
    if not text:
        return False, None, "ocr_error"
    if not find_amount(text, expected_amount):
        return False, None, "amount_mismatch"
    if not find_identifier(text, identifiers):
        return False, None, "identifier_missing"
    trx = extract_trx_id(text)
    if not trx:
        return False, None, "trx_missing"
    return True, trx, ""


def unlock_request(cr):
    """Mark a contact request unlocked — shared by auto-verification and the
    admin manual-verify button. Dealer snapshot + lucky-draw tokens included."""
    from datetime import datetime
    from models import award_tokens, TOKEN_DEAL_ENTRY
    cr.status = "unlocked"
    cr.verified_at = datetime.utcnow()
    owner = cr.listing.landlord if cr.listing else None
    if owner and owner.is_dealer() and owner.is_active:
        cr.dealer_id = owner.id
        cr.dealer_earning = cr.dealer_cut
    award_tokens(cr.renter_id, TOKEN_DEAL_ENTRY, "deal_entry")
    award_tokens(cr.landlord_id, TOKEN_DEAL_ENTRY, "deal_entry")
    try:
        from mailer import notify_unlocked
        notify_unlocked(cr)
    except Exception:
        pass
