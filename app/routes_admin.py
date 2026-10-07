"""W4 admin blueprint. Routes: /admin (dashboard), /admin/users,
/admin/listings, /admin/payments, /admin/settings, /admin/monitoring + POST actions."""
from functools import wraps
from datetime import datetime
import os

from models import (db, User, Listing, ContactRequest, Setting, get_setting,
                    SUSPICIOUS_MIN_VIEWS, SUSPICIOUS_MIN_CANCELLATIONS,
                    Draw, TokenLedger, token_balance, award_tokens, TOKEN_DEAL_ENTRY,
                    Hostel, hostel_free_slots, hostel_proof_files, UsedTrx,
                    hostel_proof_types, HOSTEL_SECURITY_FEE, VisitStat,
                    visit_stats)
from routes_lucky import run_weighted_draw
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, g, send_file, current_app
from flask_login import login_required, current_user
from translations import get_text

bp = Blueprint("admin", __name__, url_prefix="/admin")


def _t(key):
    return get_text(key, getattr(g, "lang", "ur"))


def admin_required(f):
    @wraps(f)
    @login_required
    def wrapper(*args, **kwargs):
        if not current_user.is_admin():
            abort(403)
        return f(*args, **kwargs)
    return wrapper


@bp.route("/")
@admin_required
def dashboard():
    stats = {
        "users": User.query.count(),
        "pending_listings": Listing.query.filter_by(status="pending").count(),
        "pending_hostels": Hostel.query.filter_by(status="pending").count(),
        "in_review": ContactRequest.query.filter(
            ContactRequest.status.in_(["in_review", "needs_review"])).count(),
        "unlocked": ContactRequest.query.filter_by(status="unlocked").count(),
        "approved_listings": Listing.query.filter_by(status="approved").count(),
        "pending_photos": Listing.query.filter_by(photo_status="pending").count(),
        "flagged_listings": (Listing.query
                             .filter(Listing.view_count >= SUSPICIOUS_MIN_VIEWS)
                             .filter(~Listing.contact_requests
                                     .any(ContactRequest.status == "unlocked"))
                             .count()),
        "warned_users": User.query.filter(User.warnings > 0).count(),
    }
    vstats = visit_stats()
    stats.update({"visitors_total": vstats["total"],
                  "visitors_today": vstats["today"],
                  "visitors_week": vstats["week"]})
    return render_template("admin/dashboard.html", stats=stats)


@bp.route("/backup")
@admin_required
def backup():
    """Download a copy of the database (SQLite)."""
    path = _backup_db_path()
    if path is None:
        flash(_t("backup_postgres_note"), "err")
        return redirect(url_for("admin.dashboard"))
    if not os.path.exists(path):
        flash(_t("backup_missing"), "err")
        return redirect(url_for("admin.dashboard"))
    return send_file(path, as_attachment=True,
                     download_name="kirayanama-backup.db")


@bp.route("/cron-backup")
def cron_backup():
    """Token-authenticated DB download for the weekly auto-backup cron.

    No login needed — the long random BACKUP_KEY (server env only, never in
    git) acts as the credential. Wrong/missing key -> 404 (no info leak).
    """
    key = os.environ.get("BACKUP_KEY")
    if not key or request.args.get("key") != key:
        abort(404)
    path = _backup_db_path()
    if path is None or not os.path.exists(path):
        abort(404)
    return send_file(path, as_attachment=True,
                     download_name="kirayanama-backup.db")


def _backup_db_path():
    """Return the SQLite file path, or None for non-sqlite DBs."""
    uri = current_app.config["SQLALCHEMY_DATABASE_URI"]
    if not uri.startswith("sqlite:///"):
        return None
    return uri.replace("sqlite:///", "", 1)


@bp.route("/users")
@admin_required
def users():
    all_users = User.query.order_by(User.id.desc()).all()
    return render_template("admin/users.html", users=all_users)


@bp.route("/users/<int:uid>/toggle", methods=["POST"])
@admin_required
def toggle_user(uid):
    u = User.query.get_or_404(uid)
    u.is_active = not u.is_active
    db.session.commit()
    flash(_t("user_toggled"))
    return redirect(url_for("admin.users"))


@bp.route("/users/<int:uid>/dealer", methods=["POST"])
@admin_required
def dealer_manage(uid):
    """Grant/revoke dealer status, toggle the verified badge, set share %."""
    u = User.query.get_or_404(uid)
    action = request.form.get("action") or ""
    if action == "make_dealer":
        u.role = "dealer"
        flash(_t("dealer_granted"))
    elif action == "remove_dealer":
        u.role = "landlord"
        u.dealer_verified = False
        flash(_t("dealer_revoked"))
    elif action == "verify_badge":
        u.dealer_verified = True
        flash(_t("badge_granted"))
    elif action == "unverify_badge":
        u.dealer_verified = False
        flash(_t("badge_revoked"))
    elif action == "set_share":
        try:
            share = float(request.form.get("dealer_share") or 0)
        except (TypeError, ValueError):
            share = 0
        u.dealer_share = max(0.0, min(30.0, share))
        flash(_t("share_saved"))
    db.session.commit()
    return redirect(url_for("admin.users"))


@bp.route("/users/<int:uid>/warn", methods=["POST"])
@admin_required
def warn_user(uid):
    """Issue an anti-bypass warning (escalates to deactivation)."""
    u = User.query.get_or_404(uid)
    u.warnings = (u.warnings or 0) + 1
    db.session.commit()
    flash(_t("warned_msg"))
    return redirect(url_for("admin.monitoring"))


@bp.route("/listings")
@admin_required
def listings():
    pending = Listing.query.filter_by(status="pending").order_by(Listing.created_at.desc()).all()
    rest = (Listing.query.filter(Listing.status != "pending")
            .order_by(Listing.created_at.desc()).all())
    return render_template("admin/listings.html", pending=pending, rest=rest)


@bp.route("/listings/<int:lid>/approve", methods=["POST"])
@admin_required
def approve_listing(lid):
    listing = Listing.query.get_or_404(lid)
    listing.status = "approved"
    db.session.commit()
    flash(_t("approved_msg"))
    return redirect(url_for("admin.listings"))


@bp.route("/listings/<int:lid>/reject", methods=["POST"])
@admin_required
def reject_listing(lid):
    listing = Listing.query.get_or_404(lid)
    listing.status = "rejected"
    db.session.commit()
    flash(_t("rejected_msg"))
    return redirect(url_for("admin.listings"))


# ---------------- Hostels (Phase 2, 2026-10-07) ----------------

@bp.route("/hostels")
@admin_required
def hostels():
    pending = (Hostel.query.filter_by(status="pending")
               .order_by(Hostel.created_at.desc()).all())
    rest = (Hostel.query.filter(Hostel.status != "pending")
            .order_by(Hostel.created_at.desc()).all())
    # Per-district counts + remaining free slots.
    districts = {}
    for h in Hostel.query.all():
        districts.setdefault(h.district, {"total": 0})["total"] += 1
    district_rows = [
        {"district": slug,
         "total": info["total"],
         "free_left": hostel_free_slots(slug)}
        for slug, info in sorted(districts.items())
    ]
    return render_template("admin/hostels.html", pending=pending, rest=rest,
                           district_rows=district_rows,
                           proof_files_of=hostel_proof_files,
                           proof_types_of=hostel_proof_types,
                           fee_amount=HOSTEL_SECURITY_FEE)


@bp.route("/photos")
@admin_required
def photo_review():
    """Photo review queue — listings whose photos await approval."""
    pending = (Listing.query.filter_by(photo_status="pending")
               .order_by(Listing.created_at.desc()).all())
    return render_template("admin/photos.html", pending=pending)


@bp.route("/photos/<int:lid>/approve", methods=["POST"])
@admin_required
def approve_photos(lid):
    listing = Listing.query.get_or_404(lid)
    listing.photo_status = "approved"
    listing.photo_flag = ""
    db.session.commit()
    flash(_t("photo_approved_msg"))
    return redirect(url_for("admin.photo_review"))


@bp.route("/photos/<int:lid>/reject", methods=["POST"])
@admin_required
def reject_photos(lid):
    listing = Listing.query.get_or_404(lid)
    listing.photo_status = "rejected"
    reason = (request.form.get("reason") or "").strip()
    if reason:
        listing.rejection_reason = reason
    db.session.commit()
    flash(_t("photo_rejected_msg"))
    return redirect(url_for("admin.photo_review"))


@bp.route("/hostels/<int:hid>/approve", methods=["POST"])
@admin_required
def approve_hostel(hid):
    hostel = Hostel.query.get_or_404(hid)
    hostel.status = "approved"
    hostel.rejection_reason = ""
    db.session.commit()
    flash(_t("approved_msg"))
    return redirect(url_for("admin.hostels"))


@bp.route("/hostels/<int:hid>/reject", methods=["POST"])
@admin_required
def reject_hostel(hid):
    hostel = Hostel.query.get_or_404(hid)
    hostel.status = "rejected"
    hostel.rejection_reason = (request.form.get("reason") or "").strip()
    db.session.commit()
    flash(_t("rejected_msg"))
    return redirect(url_for("admin.hostels"))


@bp.route("/hostels/<int:hid>/suspend", methods=["POST"])
@admin_required
def suspend_hostel(hid):
    hostel = Hostel.query.get_or_404(hid)
    hostel.status = "suspended"
    db.session.commit()
    flash(_t("suspended_msg"))
    return redirect(url_for("admin.hostels"))


@bp.route("/hostels/<int:hid>/unsuspend", methods=["POST"])
@admin_required
def unsuspend_hostel(hid):
    hostel = Hostel.query.get_or_404(hid)
    hostel.status = "approved"
    db.session.commit()
    flash(_t("unsuspended_msg"))
    return redirect(url_for("admin.hostels"))


@bp.route("/hostels/<int:hid>/verify-fee", methods=["POST"])
@admin_required
def verify_hostel_fee(hid):
    """Admin looked at the Rs 2000 fee screenshot -> mark fee paid."""
    hostel = Hostel.query.get_or_404(hid)
    if hostel.fee_due and hostel.fee_screenshot and not hostel.fee_paid:
        hostel.fee_paid = True
        hostel.fee_paid_at = datetime.utcnow()
        # Claim the typed TID so it can't be replayed on another fee/deal.
        if hostel.fee_tid and UsedTrx.query.get(hostel.fee_tid) is None:
            db.session.add(UsedTrx(trx_id=hostel.fee_tid, hostel_id=hostel.id,
                                   side="hostel_fee"))
        db.session.commit()
        flash(_t("fee_verified_msg"))
    return redirect(url_for("admin.hostels"))


@bp.route("/payments")
@admin_required
def payments():
    queue = (ContactRequest.query.filter_by(status="in_review")
             .order_by(ContactRequest.created_at.desc()).all())
    recent = (ContactRequest.query.filter(ContactRequest.status.in_(["unlocked", "rejected"]))
              .order_by(ContactRequest.created_at.desc()).limit(10).all())
    return render_template("admin/payments.html", queue=queue, recent=recent)


@bp.route("/payments/<int:rid>/verify", methods=["POST"])
@admin_required
def verify_payment(rid):
    req = ContactRequest.query.get_or_404(rid)
    if req.status in ("in_review", "needs_review"):
        from payment_guard import unlock_request
        unlock_request(req)  # dealer snapshot + tokens + notify included
        db.session.commit()
        flash(_t("verified_msg"))
    return redirect(url_for("admin.payments"))


@bp.route("/payments/<int:rid>/reject", methods=["POST"])
@admin_required
def reject_payment(rid):
    req = ContactRequest.query.get_or_404(rid)
    if req.status in ("in_review", "needs_review"):
        req.status = "rejected"
        db.session.commit()
        flash(_t("rejected_msg"))
    return redirect(url_for("admin.payments"))


@bp.route("/monitoring")
@admin_required
def monitoring():
    """Anti-bypass monitoring: per-listing views-vs-unlocks, per-user cancellations."""
    listings = Listing.query.order_by(Listing.view_count.desc()).all()
    rows = []
    for l in listings:
        reqs = ContactRequest.query.filter_by(listing_id=l.id).all()
        started = len([r for r in reqs if r.status != "cancelled"])
        unlocks = len([r for r in reqs if r.status == "unlocked"])
        cancelled = len([r for r in reqs if r.status == "cancelled"])
        suspicious = (l.view_count or 0) >= SUSPICIOUS_MIN_VIEWS and unlocks == 0
        rows.append({
            "listing": l, "views": l.view_count or 0, "started": started,
            "unlocks": unlocks, "cancelled": cancelled, "suspicious": suspicious,
        })

    users = User.query.filter(User.role.in_(("landlord", "dealer", "renter"))).all()
    user_rows = []
    for u in users:
        canc = (ContactRequest.query
                .filter(ContactRequest.status == "cancelled",
                        db.or_(ContactRequest.renter_id == u.id,
                               ContactRequest.landlord_id == u.id))
                .count())
        user_rows.append({
            "user": u, "cancellations": canc,
            "suspicious": canc >= SUSPICIOUS_MIN_CANCELLATIONS,
        })
    user_rows.sort(key=lambda r: r["cancellations"], reverse=True)

    return render_template("admin/monitoring.html", rows=rows, user_rows=user_rows,
                           min_views=SUSPICIOUS_MIN_VIEWS,
                           min_cancels=SUSPICIOUS_MIN_CANCELLATIONS)


@bp.route("/luckydraw")
@admin_required
def luckydraw():
    """Admin lucky-draw panel: ranked token holders, past draws, run button."""
    holders = (db.session.query(User,
                                db.func.coalesce(db.func.sum(TokenLedger.tokens), 0).label("bal"))
               .join(TokenLedger, TokenLedger.user_id == User.id)
               .group_by(User.id)
               .having(db.func.sum(TokenLedger.tokens) > 0)
               .order_by(db.desc("bal")).limit(50).all())
    draws = Draw.query.order_by(Draw.created_at.desc()).limit(10).all()
    return render_template("admin/luckydraw.html", holders=holders, draws=draws)


@bp.route("/luckydraw/run", methods=["POST"])
@admin_required
def luckydraw_run():
    """Run one weighted-random draw. Skipping is allowed — just don't press it."""
    title = (request.form.get("title") or "").strip() or _t("draw_default_title")
    draw = run_weighted_draw(title)
    if not draw:
        flash(_t("draw_no_players"))
    else:
        flash(_t("draw_done") % {"name": draw.winner.name})
    return redirect(url_for("admin.luckydraw"))


@bp.route("/settings", methods=["GET", "POST"])
@admin_required
def settings():
    if request.method == "POST":
        for key in ("jazzcash_number", "easypaisa_number", "upaisa_number", "hbl_account"):
            val = (request.form.get(key) or "").strip()
            s = Setting.query.get(key)
            if s is None:
                s = Setting(key=key, value=val)
                db.session.add(s)
            else:
                s.value = val
        db.session.commit()
        flash(_t("settings_saved"))
        return redirect(url_for("admin.settings"))
    return render_template(
        "admin/settings.html",
        jazzcash_number=get_setting("jazzcash_number"),
        easypaisa_number=get_setting("easypaisa_number"),
        upaisa_number=get_setting("upaisa_number"),
        hbl_account=get_setting("hbl_account"),
        alert_token=get_setting("alert_token"),
    )


@bp.route("/visitors/reset", methods=["POST"])
@login_required
def visitors_reset():
    if not getattr(current_user, "is_admin", False):
        abort(403)
    VisitStat.query.delete()
    db.session.commit()
    flash(_t("visitors_reset_done"))
    return redirect(url_for("admin.dashboard"))
