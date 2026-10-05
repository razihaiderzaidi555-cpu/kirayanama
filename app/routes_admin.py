"""W4 admin blueprint. Routes: /admin (dashboard), /admin/users,
/admin/listings, /admin/payments, /admin/settings, /admin/monitoring + POST actions."""
from functools import wraps
from datetime import datetime

from models import (db, User, Listing, ContactRequest, Setting, get_setting,
                    SUSPICIOUS_MIN_VIEWS, SUSPICIOUS_MIN_CANCELLATIONS,
                    Draw, TokenLedger, token_balance, award_tokens, TOKEN_DEAL_ENTRY)
from routes_lucky import run_weighted_draw
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, g
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
        "in_review": ContactRequest.query.filter_by(status="in_review").count(),
        "unlocked": ContactRequest.query.filter_by(status="unlocked").count(),
        "approved_listings": Listing.query.filter_by(status="approved").count(),
        "flagged_listings": (Listing.query
                             .filter(Listing.view_count >= SUSPICIOUS_MIN_VIEWS)
                             .filter(~Listing.contact_requests
                                     .any(ContactRequest.status == "unlocked"))
                             .count()),
        "warned_users": User.query.filter(User.warnings > 0).count(),
    }
    return render_template("admin/dashboard.html", stats=stats)


@bp.route("/backup")
@admin_required
def backup():
    """Download a copy of the database (SQLite). Weekly auto-backup runs on PA."""
    import os
    from flask import current_app, send_file
    uri = current_app.config["SQLALCHEMY_DATABASE_URI"]
    if not uri.startswith("sqlite:///"):
        flash(_t("backup_postgres_note"), "err")
        return redirect(url_for("admin.dashboard"))
    db_path = uri.replace("sqlite:///", "", 1)
    if not os.path.exists(db_path):
        flash(_t("backup_missing"), "err")
        return redirect(url_for("admin.dashboard"))
    return send_file(db_path, as_attachment=True,
                     download_name="kirayanama-backup.db")


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
    if req.status == "in_review":
        req.status = "unlocked"
        req.verified_at = datetime.utcnow()
        # Snapshot dealer economics at unlock time.
        owner = req.listing.landlord if req.listing else None
        if owner and owner.is_dealer() and owner.is_active:
            req.dealer_id = owner.id
            req.dealer_earning = req.dealer_cut
        # Lucky-draw hook: both sides earn free tokens on a completed deal.
        award_tokens(req.renter_id, TOKEN_DEAL_ENTRY, "deal_entry")
        award_tokens(req.landlord_id, TOKEN_DEAL_ENTRY, "deal_entry")
        db.session.commit()
        try:
            from mailer import notify_unlocked
            notify_unlocked(req)
        except Exception:
            pass
        flash(_t("verified_msg"))
    return redirect(url_for("admin.payments"))


@bp.route("/payments/<int:rid>/reject", methods=["POST"])
@admin_required
def reject_payment(rid):
    req = ContactRequest.query.get_or_404(rid)
    if req.status == "in_review":
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
    )
