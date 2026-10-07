"""W2: auth routes — register / login / logout. Blueprint 'auth', no url_prefix."""
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, session
from flask_login import login_user, logout_user, current_user, login_required

from models import (db, User, next_public_id, CITIES, award_tokens,
                    award_referral_tokens, ensure_referral_code, TOKEN_SIGNUP_BONUS)
from punjab_divisions import resolve_location, is_valid_location
from translations import get_text

bp = Blueprint("auth", __name__)


def T(key):
    return get_text(key, getattr(g, "lang", "ur"))


def _home_for(user):
    if user.role in ("landlord", "dealer", "admin"):
        return url_for("landlord.dashboard")
    if user.role == "hostel_owner":
        return url_for("hostel.dashboard")
    return "/"


def _safe_next(nxt, default="/"):
    # only allow local paths; block protocol-relative '//evil' style too
    if nxt and nxt.startswith("/") and not nxt.startswith("//"):
        return nxt
    return default


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(_home_for(current_user))
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        phone = (request.form.get("phone") or "").strip()
        email = (request.form.get("email") or "").strip().lower() or None
        password = request.form.get("password") or ""
        role = request.form.get("role") or "renter"
        division = request.form.get("division") or ""
        district = request.form.get("district") or ""
        tehsil = request.form.get("tehsil") or ""
        city = request.form.get("city") or ""  # legacy flat slug
        if role not in ("landlord", "renter"):
            role = "renter"  # public signup: only renter/landlord (dealer via admin)
        if is_valid_location(division, district, tehsil):
            user_city, user_division, user_district = tehsil, division, district
        elif city:
            # Back-compat: old clients post only `city`.
            rdiv, rdist, rteh = resolve_location(city=city)
            user_city, user_division, user_district = rteh or rdist, rdiv, rdist
        else:
            user_city, user_division, user_district = "", "", ""
        if not name:
            flash(T("name_req"))
        elif not phone:
            flash(T("phone_req"))
        elif len(password) < 6:
            flash(T("pw_short"))
        elif User.query.filter_by(phone=phone).first():
            flash(T("phone_taken"))
        elif email and User.query.filter_by(email=email).first():
            flash(T("email_taken"))
        else:
            user = User(public_id=next_public_id(), name=name,
                        phone=phone, email=email, role=role, city=user_city,
                        division=user_division, district=user_district)
            user.set_password(password)
            db.session.add(user)
            db.session.flush()  # get user.id before referral handling
            ensure_referral_code(user)
            # lucky-draw: free signup bonus for the new user
            award_tokens(user.id, TOKEN_SIGNUP_BONUS, "signup_bonus")
            # lucky-draw: credit the referrer (if any), capped monthly
            ref_code = (session.pop("ref_code", "") or "").strip().upper()
            session.pop("ref_name", None)
            if ref_code:
                referrer = User.query.filter_by(referral_code=ref_code).first()
                if referrer and referrer.id != user.id:
                    user.referred_by = referrer.id
                    award_referral_tokens(referrer.id)
            db.session.commit()
            login_user(user)
            flash("%s, %s! %s: %s" % (T("welcome"), user.name, T("your_id"), user.public_id))
            return redirect(_home_for(user))
    ref_name = session.get("ref_name") if request.method == "GET" else None
    from punjab_divisions import DIVISIONS
    return render_template("auth/register.html", cities=CITIES, ref_name=ref_name,
                           divisions=DIVISIONS)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(_safe_next(request.args.get("next"), _home_for(current_user)))
    if request.method == "POST":
        phone = (request.form.get("phone") or "").strip()
        password = request.form.get("password") or ""
        user = User.query.filter_by(phone=phone).first()
        if user and user.is_active and user.check_password(password):
            login_user(user)
            nxt = request.form.get("next") or request.args.get("next")
            return redirect(_safe_next(nxt, _home_for(user)))
        flash(T("bad_login"))
    return render_template("auth/login.html")


@bp.route("/logout")
def logout():
    logout_user()
    flash(T("logged_out"))
    return redirect("/")


@bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower() or None
        if email and User.query.filter(User.email == email, User.id != current_user.id).first():
            flash(T("email_taken"))
        else:
            current_user.email = email
            db.session.commit()
            flash(T("profile_saved"))
            return redirect(url_for("auth.profile"))
    return render_template("auth/profile.html")


# ---------- Email-OTP password recovery (FREE — Gmail SMTP, no SMS charges) ----------
OTP_EXPIRY_MIN = 10
OTP_MAX_PER_HOUR = 3
OTP_MAX_ATTEMPTS = 5


def _send_otp(user):
    """Generate a 6-digit OTP, store its hash, email it. Returns True if sent."""
    import secrets
    from datetime import datetime, timedelta
    from werkzeug.security import generate_password_hash
    from models import PasswordReset
    from mailer import send_email
    code = "%06d" % secrets.randbelow(1000000)
    pr = PasswordReset(
        user_id=user.id,
        code_hash=generate_password_hash(code),
        expires_at=datetime.utcnow() + timedelta(minutes=OTP_EXPIRY_MIN),
    )
    db.session.add(pr)
    db.session.commit()
    body = T("otp_body").format(code=code, minutes=OTP_EXPIRY_MIN)
    return send_email(user.email, T("otp_subject"), body)


@bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    """Step 1: enter phone number -> OTP emailed (if email on file)."""
    from datetime import datetime, timedelta
    from models import PasswordReset
    if request.method == "POST":
        phone = (request.form.get("phone") or "").strip()
        user = User.query.filter_by(phone=phone).first()
        if not user:
            flash(T("forgot_no_account"))
        elif not user.email:
            flash(T("forgot_no_email"))
        else:
            hour_ago = datetime.utcnow() - timedelta(hours=1)
            recent = (PasswordReset.query.filter_by(user_id=user.id)
                      .filter(PasswordReset.created_at > hour_ago).count())
            if recent >= OTP_MAX_PER_HOUR:
                flash(T("otp_rate_limited"))
                return redirect(url_for("auth.forgot_password"))
            if _send_otp(user):
                session["pw_reset_uid"] = user.id
                flash(T("otp_sent"))
                return redirect(url_for("auth.forgot_verify"))
            flash(T("otp_send_failed"))
    return render_template("auth/forgot.html")


@bp.route("/forgot-password/verify", methods=["GET", "POST"])
def forgot_verify():
    """Step 2: enter the 6-digit OTP from email."""
    from datetime import datetime
    from werkzeug.security import check_password_hash
    from models import PasswordReset
    uid = session.get("pw_reset_uid")
    if not uid:
        return redirect(url_for("auth.forgot_password"))
    if request.method == "POST":
        code = (request.form.get("code") or "").strip()
        pr = (PasswordReset.query.filter_by(user_id=uid, used=False)
              .order_by(PasswordReset.created_at.desc()).first())
        if not pr or pr.expires_at < datetime.utcnow():
            flash(T("otp_expired"))
            return redirect(url_for("auth.forgot_password"))
        pr.attempts = (pr.attempts or 0) + 1
        if pr.attempts > OTP_MAX_ATTEMPTS:
            pr.used = True
            db.session.commit()
            flash(T("otp_too_many"))
            return redirect(url_for("auth.forgot_password"))
        if check_password_hash(pr.code_hash, code):
            pr.used = True
            db.session.commit()
            session["pw_reset_verified"] = uid
            session.pop("pw_reset_uid", None)
            return redirect(url_for("auth.forgot_reset"))
        db.session.commit()
        flash(T("otp_wrong"))
    return render_template("auth/forgot_verify.html")


@bp.route("/forgot-password/reset", methods=["GET", "POST"])
def forgot_reset():
    """Step 3: set a new password (only after OTP verified)."""
    uid = session.get("pw_reset_verified")
    if not uid:
        return redirect(url_for("auth.forgot_password"))
    if request.method == "POST":
        pw = request.form.get("password") or ""
        pw2 = request.form.get("password2") or ""
        if len(pw) < 6:
            flash(T("pw_short"))
        elif pw != pw2:
            flash(T("pw_mismatch"))
        else:
            user = User.query.get(uid)
            if user:
                user.set_password(pw)
                db.session.commit()
            session.pop("pw_reset_verified", None)
            flash(T("pw_reset_done"))
            return redirect(url_for("auth.login"))
    return render_template("auth/forgot_reset.html")
