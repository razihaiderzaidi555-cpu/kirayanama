"""W3 — contact / dual-lock escrow flow."""
import os
import re

from models import db, User, Listing, ContactRequest, UsedTrx, get_setting
from utils import save_upload, normalize_digits
from payment_guard import verify_payment_screenshot, unlock_request
from translations import get_text
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, abort, g
from flask_login import login_required, current_user
from datetime import datetime

bp = Blueprint("contact", __name__)


def T(key):
    return get_text(key, getattr(g, "lang", "ur"))


def _get_request_or_403(rid):
    cr = ContactRequest.query.get_or_404(rid)
    if current_user.id not in (cr.renter_id, cr.landlord_id) and not current_user.is_admin():
        abort(403)
    return cr


@bp.route("/contact/<int:listing_id>", methods=["POST"])
@login_required
def contact(listing_id):
    listing = Listing.query.get_or_404(listing_id)
    if listing.status != "approved" or listing.photo_status != "approved":
        abort(404)
    if listing.landlord_id == current_user.id:
        abort(400)
    existing = ContactRequest.query.filter_by(
        listing_id=listing.id, renter_id=current_user.id
    ).filter(ContactRequest.status != "rejected").first()
    if existing:
        return redirect(url_for("contact.request_detail", rid=existing.id))
    cr = ContactRequest(
        listing_id=listing.id,
        renter_id=current_user.id,
        landlord_id=listing.landlord_id,
        status="pending_yes",
        renter_yes_at=datetime.utcnow(),
    )
    db.session.add(cr)
    db.session.commit()
    try:
        from mailer import notify_new_request
        notify_new_request(cr)
    except Exception:
        pass
    return redirect(url_for("contact.request_detail", rid=cr.id))


@bp.route("/my-requests")
@login_required
def my_requests():
    """Renter's own contact requests (outgoing) — newest first."""
    reqs = (ContactRequest.query
            .filter_by(renter_id=current_user.id)
            .order_by(ContactRequest.created_at.desc()).all())
    return render_template("contact/my_requests.html", requests=reqs)


@bp.route("/request/<int:rid>")
@login_required
def request_detail(rid):
    from models import Rating
    cr = _get_request_or_403(rid)
    is_renter = current_user.id == cr.renter_id
    is_landlord = current_user.id == cr.landlord_id
    my_rating = (Rating.query.filter_by(contact_request_id=cr.id).first()
                 if is_renter and cr.status == "unlocked" else None)
    return render_template(
        "contact/request.html",
        cr=cr,
        listing=cr.listing,
        is_renter=is_renter,
        is_landlord=is_landlord,
        my_rating=my_rating,
        jazzcash=get_setting("jazzcash_number"),
        easypaisa=get_setting("easypaisa_number"),
        upaisa=get_setting("upaisa_number"),
        hbl=get_setting("hbl_account"),
    )


@bp.route("/request/<int:rid>/confirm", methods=["POST"])
@login_required
def confirm(rid):
    cr = _get_request_or_403(rid)
    if current_user.id != cr.landlord_id:
        abort(403)
    if cr.status == "pending_yes":
        cr.landlord_yes_at = datetime.utcnow()
        cr.status = "awaiting_payment"
        db.session.commit()
        try:
            from mailer import notify_landlord_confirmed
            notify_landlord_confirmed(cr)
        except Exception:
            pass
        flash("landlord_yes_ok", "ok")
    return redirect(url_for("contact.request_detail", rid=cr.id))


@bp.route("/request/<int:rid>/location", methods=["POST"])
@login_required
def save_location(rid):
    """Landlord pins the property location on the map AFTER the deal unlocks.
    Only the renter of this deal can see it (on the request page)."""
    cr = _get_request_or_403(rid)
    if current_user.id != cr.landlord_id:
        abort(403)
    if cr.status != "unlocked":
        abort(400)
    try:
        lat = float(request.form.get("lat", ""))
        lng = float(request.form.get("lng", ""))
    except (TypeError, ValueError):
        flash("location_invalid", "err")
        return redirect(url_for("contact.request_detail", rid=cr.id))
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        flash("location_invalid", "err")
        return redirect(url_for("contact.request_detail", rid=cr.id))
    cr.listing.location_lat = lat
    cr.listing.location_lng = lng
    db.session.commit()
    flash("location_saved", "ok")
    return redirect(url_for("contact.request_detail", rid=cr.id))


@bp.route("/request/<int:rid>/cancel", methods=["POST"])
@login_required
def cancel(rid):
    """Renter or landlord cancels an in-flight request (feeds anti-bypass monitoring)."""
    cr = _get_request_or_403(rid)
    if current_user.id not in (cr.renter_id, cr.landlord_id):
        abort(403)
    if cr.status in ("pending_yes", "awaiting_payment"):
        cr.status = "cancelled"
        cr.cancelled_at = datetime.utcnow()
        db.session.commit()
        flash("request_cancelled", "ok")
    return redirect(url_for("contact.request_detail", rid=cr.id))


@bp.route("/request/<int:rid>/payment", methods=["POST"])
@login_required
def payment(rid):
    cr = _get_request_or_403(rid)
    is_renter = current_user.id == cr.renter_id
    is_landlord = current_user.id == cr.landlord_id
    if not (is_renter or is_landlord):
        abort(403)
    if cr.status not in ("awaiting_payment", "needs_review"):
        abort(400)
    # --- typed Transaction ID: required, 8-20 digits, globally unique ---
    side = "renter" if is_renter else "landlord"
    tid = normalize_digits((request.form.get("tid") or "").strip())
    if not re.fullmatch(r"\d{8,20}", tid):
        flash(T("tid_invalid"), "err")
        return redirect(url_for("contact.request_detail", rid=cr.id))
    claimed = UsedTrx.query.get(tid)
    if claimed is not None and not (claimed.contact_request_id == cr.id and
                                    claimed.side == side):
        # Same TID already paid for another deal/side -> replay attempt.
        flash(T("tid_reused"), "err")
        return redirect(url_for("contact.request_detail", rid=cr.id))
    file = request.files.get("screenshot")
    if not file or not file.filename:
        flash("shot_no_file", "err")
        return redirect(url_for("contact.request_detail", rid=cr.id))
    try:
        name = save_upload(file, "payments", current_app.config["UPLOAD_FOLDER"])
    except ValueError:
        flash("shot_bad_file", "err")
        return redirect(url_for("contact.request_detail", rid=cr.id))
    # --- automatic payment verification (fail-open: any crash -> review) ---
    # OCR checks amount + identifier; the TYPED tid takes precedence over any
    # OCR-extracted TrxID for the uniqueness claim.
    identifiers = [get_setting(k) for k in
                   ("jazzcash_number", "easypaisa_number", "upaisa_number",
                    "hbl_account")]
    img_path = os.path.join(current_app.config["UPLOAD_FOLDER"], "payments", name)
    try:
        ok, ocr_trx, reason = verify_payment_screenshot(
            img_path, cr.commission, identifiers, require_trx_id=False)
    except Exception:  # noqa: BLE001 - guard must never break uploads
        ok, ocr_trx, reason = False, None, "ocr_error"
    if ok:
        # Fresh (or this side's own re-upload): claim the typed TID.
        if claimed is None:
            db.session.add(UsedTrx(trx_id=tid, contact_request_id=cr.id,
                                   side=side))
        if is_renter:
            cr.renter_verified = True
            cr.renter_review_reason = ""
        else:
            cr.landlord_verified = True
            cr.landlord_review_reason = ""
        flash(T("shot_auto_verified"), "ok")
    else:
        if is_renter:
            cr.renter_verified = False
            cr.renter_review_reason = reason or "ocr_error"
        else:
            cr.landlord_verified = False
            cr.landlord_review_reason = reason or "ocr_error"
        flash(T("shot_needs_review"), "err")
    if is_renter:
        cr.renter_shot = name
        cr.renter_paid_at = datetime.utcnow()
    else:
        cr.landlord_shot = name
        cr.landlord_paid_at = datetime.utcnow()
    _refresh_payment_status(cr)
    db.session.commit()
    return redirect(url_for("contact.request_detail", rid=cr.id))


def _refresh_payment_status(cr):
    """Recompute the overall request status after a screenshot upload.

    - both sides auto-verified -> unlocked immediately (dual-YES + both-paid
      logic preserved; just no human in the loop anymore),
    - any uploaded-but-unverified side -> 'needs_review' (admin queue),
    - otherwise a side is still pending -> 'awaiting_payment'.
    """
    if cr.renter_verified and cr.landlord_verified:
        unlock_request(cr)
    elif ((cr.renter_shot and not cr.renter_verified) or
          (cr.landlord_shot and not cr.landlord_verified)):
        cr.status = "needs_review"
    elif cr.renter_shot or cr.landlord_shot:
        cr.status = "awaiting_payment"


@bp.route("/request/<int:rid>/rate", methods=["POST"])
@login_required
def rate_landlord(rid):
    """Renter rates the landlord after the deal unlocks — one rating per deal."""
    from models import Rating
    cr = _get_request_or_403(rid)
    if current_user.id != cr.renter_id:
        abort(403)
    if cr.status != "unlocked":
        abort(400)
    if Rating.query.filter_by(contact_request_id=cr.id).first():
        flash("already_rated", "err")
        return redirect(url_for("contact.request_detail", rid=cr.id))
    try:
        stars = int(request.form.get("stars", "0"))
    except (TypeError, ValueError):
        stars = 0
    if stars < 1 or stars > 5:
        flash("stars_invalid", "err")
        return redirect(url_for("contact.request_detail", rid=cr.id))
    comment = (request.form.get("comment") or "").strip()[:500] or None
    db.session.add(Rating(
        contact_request_id=cr.id,
        listing_id=cr.listing_id,
        renter_id=cr.renter_id,
        landlord_id=cr.landlord_id,
        stars=stars,
        comment=comment,
    ))
    db.session.commit()
    flash("rating_saved", "ok")
    return redirect(url_for("contact.request_detail", rid=cr.id))
