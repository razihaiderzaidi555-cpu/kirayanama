"""Lucky Draw + referral system (SAFE version: all tokens free, winners always real).

Public:  /r/<code>      -> capture referral, redirect to register
         /lucky-draw    -> wheel page, token balance, share links, winners
"""
import random
from datetime import datetime, timedelta

from flask import Blueprint, render_template, request, redirect, url_for, session, g, abort, jsonify
from flask_login import current_user, login_required

from models import (db, User, TokenLedger, Draw, WheelSpin, token_balance,
                    ensure_referral_code, wheel_spins_total, wheel_spins_24h)
from translations import get_text

bp = Blueprint("lucky", __name__)

# Wheel rules (owner-approved 2026-09-30):
SPINS_PER_DAY = 3          # max spins per user per rolling 24 hours
RENT_SPINS_GOAL = 1000     # cumulative spins at which a renter wins free rent
WHEEL_RENT_TITLE = "🎡 وہیل: 1000 اسپن مکمل"  # marks the one-time wheel rent prize
# Segment indices on the 8-slice wheel that show the rent prize:
RENT_SEGMENTS = (3, 7)


def T(key):
    return get_text(key, getattr(g, "lang", "ur"))


@bp.route("/r/<code>")
def referral(code):
    """Capture a referral code in the session, then send to registration."""
    code = (code or "").strip().upper()
    user = User.query.filter_by(referral_code=code).first() if code else None
    if user:
        session["ref_code"] = user.referral_code
        session["ref_name"] = user.name
    return redirect(url_for("auth.register"))


def _ref_link(user):
    ensure_referral_code(user)
    return url_for("lucky.referral", code=user.referral_code, _external=True)


@bp.route("/lucky-draw")
def lucky_draw():
    balance = 0
    ref_link = ""
    ref_code = ""
    if current_user.is_authenticated:
        ensure_referral_code(current_user)
        db.session.commit()
        balance = token_balance(current_user.id)
        ref_code = current_user.referral_code or ""
        ref_link = _ref_link(current_user)

    winners = (Draw.query.filter_by(status="drawn")
               .order_by(Draw.drawn_at.desc()).limit(10).all())
    latest = winners[0] if winners else None

    # participants: users holding at least one token
    participants = (db.session.query(TokenLedger.user_id)
                    .distinct().count())
    total_tokens = (db.session.query(db.func.coalesce(db.func.sum(TokenLedger.tokens), 0))
                    .scalar() or 0)

    return render_template(
        "public/lucky_draw.html",
        balance=balance, ref_link=ref_link, ref_code=ref_code,
        winners=winners, latest=latest,
        participants=participants, total_tokens=int(total_tokens),
        spins_total=wheel_spins_total(current_user.id) if current_user.is_authenticated else 0,
        spins_left_today=(SPINS_PER_DAY - wheel_spins_24h(current_user.id)) if current_user.is_authenticated else SPINS_PER_DAY,
        spins_per_day=SPINS_PER_DAY, rent_spins_goal=RENT_SPINS_GOAL,
    )


@bp.route("/lucky-draw/spin", methods=["POST"])
@login_required
def spin():
    """Server-authoritative wheel spin.

    Enforces max 3 spins per rolling 24h. Records every spin. Awards one
    month of free rent (Draw record) the first time a renter reaches
    1000 cumulative spins. Returns the wheel segment the client must land on.
    """
    if not current_user.is_active:
        abort(403)
    used_24h = wheel_spins_24h(current_user.id)
    if used_24h >= SPINS_PER_DAY:
        return jsonify({"ok": False, "error": "limit",
                        "message": T("draw_limit_reached")}), 429

    db.session.add(WheelSpin(user_id=current_user.id))
    db.session.commit()
    total = wheel_spins_total(current_user.id)
    spins_left = SPINS_PER_DAY - used_24h - 1

    won_rent = False
    already_won = Draw.query.filter_by(winner_id=current_user.id,
                                       title=WHEEL_RENT_TITLE).first()
    if (current_user.role == "renter" and total >= RENT_SPINS_GOAL
            and not already_won):
        db.session.add(Draw(title=WHEEL_RENT_TITLE, status="drawn",
                            winner_id=current_user.id,
                            drawn_at=datetime.utcnow(),
                            prize="prize_1month"))
        db.session.commit()
        won_rent = True

    segment = random.choice(RENT_SEGMENTS) if won_rent else random.choice(
        [i for i in range(8) if i not in RENT_SEGMENTS])

    return jsonify({
        "ok": True,
        "segment": segment,
        "total_spins": total,
        "spins_left_today": spins_left,
        "spins_to_rent": max(0, RENT_SPINS_GOAL - total),
        "won_rent": won_rent,
        "is_renter": current_user.role == "renter",
    })


def run_weighted_draw(title, prize_key="prize_1month"):
    """Pick ONE real winner, weighted by token balance. Admins can't win.

    Returns the new Draw record, or None when nobody is eligible.
    """
    balances = {}
    rows = (db.session.query(TokenLedger.user_id,
                             db.func.sum(TokenLedger.tokens).label("t"))
            .group_by(TokenLedger.user_id).all())
    for uid, total in rows:
        if total and total > 0:
            u = User.query.get(uid)
            if u and u.is_active and not u.is_admin():
                balances[uid] = int(total)
    if not balances:
        return None
    winner_id = random.choices(list(balances.keys()),
                               weights=list(balances.values()), k=1)[0]
    draw = Draw(title=title or T("draw_default_title"), status="drawn",
                winner_id=winner_id, drawn_at=datetime.utcnow(),
                prize=prize_key)
    db.session.add(draw)
    db.session.commit()
    return draw
