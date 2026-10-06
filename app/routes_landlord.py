"""W2: landlord dashboard — my listings CRUD + incoming contact requests.
Blueprint 'landlord', url_prefix '/dashboard'."""
from functools import wraps

from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, current_app, g)
from flask_login import login_required, current_user

from models import (db, User, Listing, ListingPhoto, ContactRequest,
                    next_public_id, CITIES, PROPERTY_TYPES,
                    token_balance, ensure_referral_code)
from punjab_divisions import (DIVISIONS, division_slugs, resolve_location,
                              is_valid_location)
from utils import save_upload, find_phone_numbers
from translations import get_text

bp = Blueprint("landlord", __name__, url_prefix="/dashboard")

OPEN_REQUEST_STATUSES = ["pending_yes", "awaiting_payment", "in_review"]
LISTER_ROLES = ("landlord", "dealer", "admin")  # who may create listings


def T(key):
    return get_text(key, getattr(g, "lang", "ur"))


def lister_required(view):
    """login_required + role must be landlord, dealer or admin."""
    @wraps(view)
    @login_required
    def wrapper(*args, **kwargs):
        if current_user.role not in LISTER_ROLES:
            flash(T("landlord_only"))
            return redirect("/")
        return view(*args, **kwargs)
    return wrapper


# Backwards-compatible alias (same behavior).
landlord_required = lister_required


def _to_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _has_uploaded_photos():
    """True if the POST contains at least one non-empty photo file."""
    return any(f and f.filename for f in request.files.getlist("photos"))


def _save_photos(listing, make_first_primary):
    """Save uploaded photos (first saved one becomes primary if asked).

    Returns the absolute paths of the files actually saved (for photo_guard).
    """
    import os
    saved = []
    base = len(listing.photos)
    idx = 0
    upload_root = current_app.config["UPLOAD_FOLDER"]
    for f in request.files.getlist("photos"):
        if not f or not f.filename:
            continue
        try:
            filename = save_upload(
                f, "listings",
                upload_root=upload_root)
        except ValueError:
            flash(T("photo_bad"))
            continue
        listing.photos.append(ListingPhoto(
            filename=filename,
            is_primary=(make_first_primary and idx == 0),
            sort_order=base + idx,
        ))
        saved.append(os.path.join(upload_root, "listings", filename))
        idx += 1
    return saved


def _apply_photo_checks(listing, new_paths):
    """Automatic photo moderation: person detection + OCR phone scan.

    - Person visible in any new photo -> photo auto-REJECTED with an Urdu
      reason for the landlord; listing stays hidden until a clean photo is
      uploaded. No admin action needed.
    - Phone-like text in a photo -> flagged 'pending' for admin review
      (background queue, /admin/photos).
    - Clean -> auto 'approved'. No admin action needed.
    Never raises — uploads must not break.
    """
    if not new_paths:
        return
    try:
        from person_guard import scan_photo_paths as _person_scan
        if _person_scan(new_paths):
            listing.photo_status = "rejected"
            listing.photo_flag = "person_detected"
            listing.rejection_reason = T("rejection_person_reason")
            return
    except Exception:  # noqa: BLE001 - guard must never break the flow
        pass
    try:
        from photo_guard import scan_photo_paths as _ocr_scan
        hit = _ocr_scan(new_paths)
    except Exception:  # noqa: BLE001
        hit = None
    if hit:
        listing.photo_status = "pending"
        listing.photo_flag = "phone_detected"
    else:
        listing.photo_status = "approved"
        listing.photo_flag = ""


def _read_listing_form():
    division = request.form.get("division") or ""
    district = request.form.get("district") or ""
    tehsil = request.form.get("tehsil") or ""
    city = request.form.get("city") or ""  # legacy district/tehsil slug
    if not is_valid_location(division, district, tehsil):
        # Back-compat: old clients/tests post only `city`.
        division, district, tehsil = resolve_location(city=city)
    return {
        "title_ur": (request.form.get("title_ur") or "").strip(),
        "title_en": (request.form.get("title_en") or "").strip(),
        "desc_ur": (request.form.get("desc_ur") or "").strip(),
        "desc_en": (request.form.get("desc_en") or "").strip(),
        "division": division,
        "city": district,  # Listing.city stores the DISTRICT slug
        "tehsil": tehsil,
        "area": (request.form.get("area") or "").strip(),
        "exact_address": (request.form.get("exact_address") or "").strip(),
        "property_type": (request.form.get("property_type")
                          if request.form.get("property_type") in PROPERTY_TYPES else "house"),
        "bedrooms": _to_int(request.form.get("bedrooms")),
        "bathrooms": _to_int(request.form.get("bathrooms")),
        "area_sqft": _to_int(request.form.get("area_sqft")),
        "monthly_rent": _to_int(request.form.get("monthly_rent")),
    }


def _validate_listing_form(data):
    if not data["title_ur"]:
        return T("title_req")
    if data["monthly_rent"] <= 0:
        return T("rent_req")
    return None


def _detect_bypass_number(data):
    """Scan title/description for hidden phone numbers (bypass attempt).

    Returns the matched number string, or None if clean.
    """
    for field in ("title_ur", "title_en", "desc_ur", "desc_en"):
        hits = find_phone_numbers(data.get(field) or "")
        if hits:
            return hits[0]
    return None


def _apply_phone_scan(listing, data):
    """Auto-reject listings that sneak a phone number into text.

    Returns True when the listing was auto-rejected.
    """
    hit = _detect_bypass_number(data)
    if hit:
        listing.status = "rejected"
        listing.rejection_reason = T("rejection_phone_reason")
        return True
    return False


@bp.route("")
@landlord_required
def dashboard():
    listings = (Listing.query
                .filter_by(landlord_id=current_user.id)
                .order_by(Listing.created_at.desc()).all())
    open_reqs = (ContactRequest.query
                 .filter(ContactRequest.landlord_id == current_user.id,
                         ContactRequest.status.in_(OPEN_REQUEST_STATUSES))
                 .count())
    # Dealer earnings (zero for plain landlords — template hides the cards).
    dealer_stats = None
    if current_user.is_dealer():
        closed = (ContactRequest.query
                  .filter_by(dealer_id=current_user.id, status="unlocked").all())
        dealer_stats = {
            "closed_deals": len(closed),
            "total_earned": sum(r.dealer_earning or 0 for r in closed),
        }
    # Lucky-draw: token balance + referral link card.
    ensure_referral_code(current_user)
    db.session.commit()
    ref_link = url_for("lucky.referral", code=current_user.referral_code,
                       _external=True)
    return render_template("landlord/dashboard.html",
                           listings=listings, open_reqs=open_reqs,
                           dealer_stats=dealer_stats,
                           token_balance=token_balance(current_user.id),
                           ref_link=ref_link)


@bp.route("/listings/new", methods=["GET", "POST"])
@landlord_required
def listing_new():
    if request.method == "POST":
        data = _read_listing_form()
        err = _validate_listing_form(data)
        if not err and not _has_uploaded_photos():
            err = T("photo_required")
        if err:
            flash(err)
        else:
            listing = Listing(landlord_id=current_user.id, status="pending", **data)
            new_paths = _save_photos(listing, make_first_primary=True)
            _apply_photo_checks(listing, new_paths)
            if _apply_phone_scan(listing, data):
                flash(T("listing_rejected_phone"))
            elif listing.photo_flag == "person_detected":
                flash(T("rejection_person_reason"))
            else:
                flash(T("listing_saved"))
            db.session.add(listing)
            db.session.commit()
            return redirect(url_for("landlord.dashboard"))
    return render_template("landlord/listing_form.html", listing=None,
                           cities=CITIES, ptypes=PROPERTY_TYPES,
                           divisions=DIVISIONS)


@bp.route("/listings/<int:listing_id>/edit", methods=["GET", "POST"])
@landlord_required
def listing_edit(listing_id):
    listing = Listing.query.get(listing_id)
    if not listing:
        flash(T("listing_notfound"))
        return redirect(url_for("landlord.dashboard"))
    if listing.landlord_id != current_user.id and current_user.role != "admin":
        flash(T("not_owner"))
        return redirect(url_for("landlord.dashboard"))
    if request.method == "POST":
        data = _read_listing_form()
        err = _validate_listing_form(data)
        if not err and not listing.photos and not _has_uploaded_photos():
            err = T("photo_required")
        if err:
            flash(err)
        else:
            for k, v in data.items():
                setattr(listing, k, v)
            new_paths = _save_photos(listing, make_first_primary=not listing.photos)
            # new photos -> automatic photo checks decide the final status
            _apply_photo_checks(listing, new_paths)
            if _apply_phone_scan(listing, data):
                # A number snuck in via edit -> kill the listing, needs re-review.
                flash(T("listing_rejected_phone"))
            elif listing.photo_flag == "person_detected":
                flash(T("rejection_person_reason"))
            else:
                flash(T("edit_saved"))
            db.session.commit()
            return redirect(url_for("landlord.dashboard"))
    return render_template("landlord/listing_form.html", listing=listing,
                           cities=CITIES, ptypes=PROPERTY_TYPES,
                           divisions=DIVISIONS)


@bp.route("/listings/<int:listing_id>/close", methods=["POST"])
@landlord_required
def listing_close(listing_id):
    """Landlord marks a listing as rented out — hidden from public browse."""
    listing = Listing.query.get_or_404(listing_id)
    if listing.landlord_id != current_user.id and current_user.role != "admin":
        flash(T("not_owner"))
        return redirect(url_for("landlord.dashboard"))
    listing.is_closed = True
    db.session.commit()
    flash(T("listing_closed"))
    return redirect(url_for("landlord.dashboard"))


@bp.route("/listings/<int:listing_id>/reopen", methods=["POST"])
@landlord_required
def listing_reopen(listing_id):
    listing = Listing.query.get_or_404(listing_id)
    if listing.landlord_id != current_user.id and current_user.role != "admin":
        flash(T("not_owner"))
        return redirect(url_for("landlord.dashboard"))
    listing.is_closed = False
    db.session.commit()
    flash(T("listing_reopened"))
    return redirect(url_for("landlord.dashboard"))


@bp.route("/requests")
@landlord_required
def requests_inbox():
    reqs = (ContactRequest.query
            .filter_by(landlord_id=current_user.id)
            .order_by(ContactRequest.created_at.desc()).all())
    return render_template("landlord/requests.html", requests=reqs)
