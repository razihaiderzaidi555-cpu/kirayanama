"""W2: auth routes — register / login / logout. Blueprint 'auth', no url_prefix."""
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, session
from flask_login import login_user, logout_user, current_user

from models import (db, User, next_public_id, CITIES, award_tokens,
                    award_referral_tokens, ensure_referral_code, TOKEN_SIGNUP_BONUS)
from translations import get_text

bp = Blueprint("auth", __name__)


def T(key):
    return get_text(key, getattr(g, "lang", "ur"))


def _home_for(user):
    if user.role in ("landlord", "dealer", "admin"):
        return url_for("landlord.dashboard")
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
        password = request.form.get("password") or ""
        role = request.form.get("role") or "renter"
        city = request.form.get("city") or ""
        if role not in ("landlord", "renter", "dealer"):
            role = "renter"
        if city not in CITIES:
            city = ""
        if not name:
            flash(T("name_req"))
        elif not phone:
            flash(T("phone_req"))
        elif len(password) < 6:
            flash(T("pw_short"))
        elif User.query.filter_by(phone=phone).first():
            flash(T("phone_taken"))
        else:
            user = User(public_id=next_public_id(), name=name,
                        phone=phone, role=role, city=city)
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
    return render_template("auth/register.html", cities=CITIES, ref_name=ref_name)


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
