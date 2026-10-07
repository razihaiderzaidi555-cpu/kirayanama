"""Hostel owner system (Phase 2, 2026-10-07). Blueprint 'hostel', no url_prefix.

Flow: public registration (name/phone/password + CNIC + hostel name/district/
address + >=1 photo) -> CNIC copy + >=2 ownership proofs -> optional
security-fee screenshot (only after the district's 50 free slots are used up;
amount = hostel_fee_amount admin setting) -> admin approval queue (approval
sets reg_expires_at = +365 days) -> public browse/detail.
Yearly renewal (2026-10-07): every registration expires after a year and must
be renewed at the then-current rate; expired hostels are hidden from browse
until renewed.
"""
import json
import os
import re
from datetime import datetime, date
from functools import wraps

from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, g, current_app)
from flask_login import login_user, logout_user, current_user, login_required

from models import (db, User, Hostel, HostelPhoto, UsedTrx, next_public_id,
                    hostel_free_slots, hostel_fee_due_for, hostel_proof_files,
                    hostel_proof_types, HOSTEL_PROOF_TYPES, hostel_fee_amount,
                    hostel_is_expired, hostel_renewal_expiry,
                    hostel_show_welcome_notice,
                    ensure_referral_code, get_setting)
from punjab_divisions import district_slugs, DIVISIONS
from translations import get_text
from utils import save_upload, find_phone_numbers, normalize_digits
from payment_guard import verify_payment_screenshot
from utils import save_upload, find_phone_numbers

bp = Blueprint("hostel", __name__)


def T(key):
    return get_text(key, getattr(g, "lang", "ur"))


def hostel_owner_required(view):
    """login_required + role must be hostel_owner or admin."""
    @wraps(view)
    @login_required
    def wrapper(*args, **kwargs):
        if current_user.role not in ("hostel_owner", "admin"):
            flash(T("hostel_owner_only"))
            return redirect("/")
        return view(*args, **kwargs)
    return wrapper


def _get_hostel_or_403(hid):
    hostel = Hostel.query.get_or_404(hid)
    if (current_user.role != "admin" and hostel.owner_id != current_user.id):
        from flask import abort
        abort(403)
    return hostel


def _phone_hit(hostel):
    """Existing anti-fraud phone scan on hostel name/address text."""
    for field in (hostel.hostel_name_ur, hostel.hostel_name_en, hostel.address):
        hits = find_phone_numbers(field or "")
        if hits:
            return hits[0]
    return None


def _save_hostel_photos(hostel, make_first_primary=False):
    base = len(hostel.photos)
    saved = 0
    for i, f in enumerate(request.files.getlist("photos")):
        if not f or not f.filename:
            continue
        try:
            filename = save_upload(f, "hostels",
                                   current_app.config["UPLOAD_FOLDER"])
        except ValueError:
            flash(T("photo_bad"))
            continue
        hostel.photos.append(HostelPhoto(
            filename=filename,
            is_primary=(make_first_primary and base + saved == 0),
            sort_order=base + saved))
        saved += 1
    return saved


# ---------------- registration ----------------

@bp.route("/hostel/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("hostel.dashboard"))
    districts = sorted(district_slugs())
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        phone = (request.form.get("phone") or "").strip()
        password = request.form.get("password") or ""
        cnic = (request.form.get("cnic") or "").strip()
        hostel_name_ur = (request.form.get("hostel_name_ur") or "").strip()
        hostel_name_en = (request.form.get("hostel_name_en") or "").strip()
        district = (request.form.get("district") or "").strip()
        address = (request.form.get("address") or "").strip()
        fee_due = hostel_fee_due_for(district) if district else False
        err = None
        if not name:
            err = T("name_req")
        elif not phone:
            err = T("phone_req")
        elif len(password) < 6:
            err = T("pw_short")
        elif not cnic:
            err = T("cnic_req")
        elif not hostel_name_ur:
            err = T("hostel_name_req")
        elif district not in districts:
            err = T("district_req")
        elif not address:
            err = T("address_req")
        elif User.query.filter_by(phone=phone).first():
            err = T("phone_taken")
        if err:
            flash(err)
        else:
            user = User(public_id=next_public_id(), name=name, phone=phone,
                        role="hostel_owner", district=district)
            user.set_password(password)
            db.session.add(user)
            db.session.flush()
            ensure_referral_code(user)
            # marketing-agent attribution (cousin plan): ?ref=CODE link
            from models import claim_agent_ref
            claim_agent_ref(user)
            hostel = Hostel(
                owner_id=user.id,
                hostel_name_ur=hostel_name_ur,
                hostel_name_en=hostel_name_en,
                district=district,
                address=address,
                owner_cnic=cnic,
                status="pending",
                fee_due=fee_due,
            )
            # Same anti-fraud phone scan as listings: auto-reject on a hit.
            hit = _phone_hit(hostel)
            if hit:
                hostel.status = "rejected"
                hostel.rejection_reason = T("rejection_phone_reason")
            db.session.add(hostel)
            db.session.flush()
            saved = _save_hostel_photos(hostel, make_first_primary=True)
            db.session.commit()
            login_user(user)
            flash(T("hostel_registered_ok").format(pid=user.public_id))
            if saved == 0:
                flash(T("photo_required"))
            return redirect(url_for("hostel.docs", hid=hostel.id))
    return render_template("hostel/register.html", districts=districts,
                           divisions=DIVISIONS)


# ---------------- owner: docs / photos / fee ----------------

@bp.route("/hostel/<int:hid>/docs", methods=["GET", "POST"])
@hostel_owner_required
def docs(hid):
    hostel = _get_hostel_or_403(hid)
    if request.method == "POST":
        cnic_file = request.files.get("cnic_copy")
        proofs = [f for f in request.files.getlist("proof_files")
                  if f and f.filename]
        proof_types = [t for t in request.form.getlist("proof_types")
                       if t in HOSTEL_PROOF_TYPES]
        if not cnic_file or not cnic_file.filename:
            flash(T("hostel_cnic_req"))
        elif len(proofs) < 2:
            flash(T("hostel_docs_min"))
        else:
            try:
                hostel.cnic_copy = save_upload(
                    cnic_file, "hostel_docs",
                    current_app.config["UPLOAD_FOLDER"])
            except ValueError:
                flash(T("photo_bad"))
                return render_template(
                    "hostel/docs.html", hostel=hostel,
                    proof_files=hostel_proof_files(hostel),
                    proof_types_sel=hostel_proof_types(hostel),
                    proof_types_all=HOSTEL_PROOF_TYPES)
            saved = []
            for f in proofs:
                try:
                    saved.append(save_upload(
                        f, "hostel_docs",
                        current_app.config["UPLOAD_FOLDER"]))
                except ValueError:
                    flash(T("photo_bad"))
            if len(saved) < 2:
                flash(T("hostel_docs_min"))
            else:
                hostel.proof_files = json.dumps(saved)
                hostel.proof_types = json.dumps(proof_types)
                db.session.commit()
                flash(T("hostel_docs_saved"))
                return redirect(url_for("hostel.dashboard"))
    return render_template("hostel/docs.html", hostel=hostel,
                           proof_files=hostel_proof_files(hostel),
                           proof_types_sel=hostel_proof_types(hostel),
                           proof_types_all=HOSTEL_PROOF_TYPES)


@bp.route("/hostel/<int:hid>/photos", methods=["GET", "POST"])
@hostel_owner_required
def photos(hid):
    hostel = _get_hostel_or_403(hid)
    if request.method == "POST":
        saved = _save_hostel_photos(hostel)
        if saved:
            db.session.commit()
            flash(T("photos_saved"))
        else:
            flash(T("photo_required"))
        return redirect(url_for("hostel.photos", hid=hid))
    return render_template("hostel/photos.html", hostel=hostel)


@bp.route("/hostel/<int:hid>/fee", methods=["GET", "POST"])
@hostel_owner_required
def fee(hid):
    hostel = _get_hostel_or_403(hid)
    amt = hostel_fee_amount()
    # Yearly renewal: an expired registration can always be renewed here at
    # the CURRENT rate. The first-50-free quota applies to first registration
    # only — never to renewals.
    is_renewal = request.args.get("renew") == "1" and hostel_is_expired(hostel)
    if not is_renewal and (not hostel.fee_due or hostel.fee_paid):
        return redirect(url_for("hostel.dashboard"))

    def _form():
        if is_renewal:
            page_title = T("renewal_fee_title")
            page_msg = T("renewal_fee_msg").format(amount=amt)
        else:
            page_title = T("hostel_fee_due_title")
            page_msg = T("hostel_fee_due_msg").format(amount=amt)
        return render_template(
            "hostel/fee.html", hostel=hostel,
            page_title=page_title, page_msg=page_msg,
            fee_info=T("hostel_fee_info").format(amount=amt),
            fee_amount=amt, is_renewal=is_renewal,
            jazzcash=get_setting("jazzcash_number"),
            easypaisa=get_setting("easypaisa_number"),
            upaisa=get_setting("upaisa_number"),
            hbl=get_setting("hbl_account"))

    if request.method == "POST":
        if is_renewal:
            # Fresh payment state for the renewal attempt — the old
            # screenshot/TID must not block the admin-manual-verify path.
            hostel.fee_screenshot = None
            hostel.fee_paid = False
            hostel.fee_verified = False
            hostel.fee_review_reason = ""
            hostel.fee_tid = ""
            hostel.fee_company = ""
            hostel.fee_paid_at = None
        # --- typed Transaction ID: required, 8-20 digits, globally unique ---
        tid = normalize_digits((request.form.get("tid") or "").strip())
        if not re.fullmatch(r"\d{8,20}", tid):
            flash(T("tid_invalid"))
            return _form()
        claimed = UsedTrx.query.get(tid)
        if claimed is not None and claimed.hostel_id != hostel.id:
            # Same TID already paid for another deal/fee -> replay attempt.
            flash(T("tid_reused"))
            return _form()
        shot = request.files.get("screenshot")
        if not shot or not shot.filename:
            flash(T("shot_no_file"))
            return _form()
        try:
            name = save_upload(
                shot, "fees", current_app.config["UPLOAD_FOLDER"])
        except ValueError:
            flash(T("shot_bad_file"))
            return _form()
        hostel.fee_screenshot = name
        # --- automatic fee verification (fail-open: any crash -> admin review) ---
        # OCR checks the exact expected amount (current admin-set rate) + one
        # of Razi's payment identifiers; the TYPED tid takes precedence over
        # any OCR-extracted TrxID for the uniqueness claim.
        companies = [(key, get_setting(key + "_number" if key != "hbl" else "hbl_account"))
                     for key in ("jazzcash", "easypaisa", "upaisa", "hbl")]
        img_path = os.path.join(
            current_app.config["UPLOAD_FOLDER"], "fees", name)
        try:
            ok, _ocr_trx, reason, company = verify_payment_screenshot(
                img_path, amt, companies, require_trx_id=False)
        except Exception:  # noqa: BLE001 - guard must never break uploads
            ok, _ocr_trx, reason, company = False, None, "ocr_error", None
        hostel.fee_tid = tid
        hostel.fee_company = company or ""
        if ok:
            # Fresh (or this hostel's own re-upload): claim the typed TID.
            if claimed is None:
                db.session.add(UsedTrx(trx_id=tid, hostel_id=hostel.id,
                                       side="hostel_fee"))
            hostel.fee_paid = True
            hostel.fee_verified = True
            hostel.fee_review_reason = ""
            hostel.fee_paid_at = datetime.utcnow()
            if is_renewal:
                # Renewal extends from the later of old expiry / today, so an
                # early renewal never loses remaining days.
                base = hostel.reg_expires_at
                hostel.reg_expires_at = hostel_renewal_expiry(
                    max(base, date.today()) if base else None)
            db.session.commit()
            if is_renewal:
                flash(T("renewal_done").format(date=hostel.reg_expires_at))
            else:
                flash(T("fee_auto_verified"))
        else:
            # Fail-open: screenshot stays queued for the admin with a reason.
            hostel.fee_verified = False
            hostel.fee_review_reason = reason or "ocr_error"
            db.session.commit()
            flash(T("fee_needs_review"))
        return redirect(url_for("hostel.dashboard"))
    return _form()


# ---------------- owner dashboard ----------------

@bp.route("/hostel/<int:hid>/dismiss-renewal-reminder", methods=["POST"])
@hostel_owner_required
def dismiss_renewal_reminder(hid):
    """Owner dismissed the phase-2 pre-expiry reminder — it reappears
    the next day."""
    hostel = _get_hostel_or_403(hid)
    hostel.renewal_dismissed_at = datetime.utcnow()
    db.session.commit()
    return redirect(url_for("hostel.dashboard"))


@bp.route("/hostel/dashboard")
@hostel_owner_required
def dashboard():
    hostels = (Hostel.query
               .filter_by(owner_id=current_user.id)
               .order_by(Hostel.created_at.desc()).all())
    district_slots = {h.district: hostel_free_slots(h.district)
                      for h in hostels}
    return render_template("hostel/dashboard.html", hostels=hostels,
                           district_slots=district_slots,
                           fee_amount=hostel_fee_amount(),
                           show_welcome_notice=hostel_show_welcome_notice(
                               current_user))


# ---------------- public browse + detail ----------------

def _visible_hostels_q():
    """Approved AND registration not expired. Expired hostels stay hidden
    (same as suspended) until the owner renews."""
    today = date.today()
    return (Hostel.query.filter_by(status="approved")
            .filter(db.or_(Hostel.reg_expires_at.is_(None),
                           Hostel.reg_expires_at >= today)))


@bp.route("/hostels")
def browse():
    district = (request.args.get("district") or "").strip()
    q = _visible_hostels_q()
    if district:
        q = q.filter_by(district=district)
    hostels = q.order_by(Hostel.created_at.desc()).all()
    return render_template("hostel/browse.html", hostels=hostels,
                           districts=sorted(district_slugs()),
                           active_district=district)


@bp.route("/hostels/<district>")
def browse_district(district):
    if district not in district_slugs():
        from flask import abort
        abort(404)
    hostels = (_visible_hostels_q().filter_by(district=district)
               .order_by(Hostel.created_at.desc()).all())
    return render_template("hostel/browse.html", hostels=hostels,
                           districts=sorted(district_slugs()),
                           active_district=district)


@bp.route("/hostel/view/<int:hid>")
def detail(hid):
    hostel = Hostel.query.get_or_404(hid)
    if hostel.status != "approved" or hostel_is_expired(hostel):
        from flask import abort
        abort(404)
    return render_template("hostel/detail.html", hostel=hostel)
