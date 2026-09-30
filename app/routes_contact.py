"""W3 — contact / dual-lock escrow flow."""
from models import db, User, Listing, ContactRequest, get_setting
from utils import save_upload
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, abort
from flask_login import login_required, current_user
from datetime import datetime

bp = Blueprint("contact", __name__)


def _get_request_or_403(rid):
    cr = ContactRequest.query.get_or_404(rid)
    if current_user.id not in (cr.renter_id, cr.landlord_id) and not current_user.is_admin():
        abort(403)
    return cr


@bp.route("/contact/<int:listing_id>", methods=["POST"])
@login_required
def contact(listing_id):
    listing = Listing.query.get_or_404(listing_id)
    if listing.status != "approved":
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
    return redirect(url_for("contact.request_detail", rid=cr.id))


@bp.route("/request/<int:rid>")
@login_required
def request_detail(rid):
    cr = _get_request_or_403(rid)
    is_renter = current_user.id == cr.renter_id
    is_landlord = current_user.id == cr.landlord_id
    return render_template(
        "contact/request.html",
        cr=cr,
        listing=cr.listing,
        is_renter=is_renter,
        is_landlord=is_landlord,
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
        flash("landlord_yes_ok", "ok")
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
    if cr.status != "awaiting_payment":
        abort(400)
    file = request.files.get("screenshot")
    if not file or not file.filename:
        flash("shot_no_file", "err")
        return redirect(url_for("contact.request_detail", rid=cr.id))
    try:
        name = save_upload(file, "payments", current_app.config["UPLOAD_FOLDER"])
    except ValueError:
        flash("shot_bad_file", "err")
        return redirect(url_for("contact.request_detail", rid=cr.id))
    if is_renter:
        cr.renter_shot = name
        cr.renter_paid_at = datetime.utcnow()
    else:
        cr.landlord_shot = name
        cr.landlord_paid_at = datetime.utcnow()
    if cr.renter_shot and cr.landlord_shot:
        cr.status = "in_review"
    db.session.commit()
    flash("shot_saved", "ok")
    return redirect(url_for("contact.request_detail", rid=cr.id))
