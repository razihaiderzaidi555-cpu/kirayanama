"""Lucky Draw + referral system (SAFE version: all tokens free, winners always real).

Public:  /r/<code>      -> capture referral, redirect to register
         /lucky-draw    -> wheel page, token balance, share links, winners
"""
import random
from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, session, g, abort
from flask_login import current_user

from models import db, User, TokenLedger, Draw, token_balance, ensure_referral_code
from translations import get_text

bp = Blueprint("lucky", __name__)


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
    )


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
