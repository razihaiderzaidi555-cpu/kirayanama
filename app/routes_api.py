"""Read-only JSON APIs for automation (maria's WhatsApp alert cron).

GET /api/payment-events?since=<ISO8601>&token=<token>
    Lists payment screenshot submissions (both sides of every deal) created
    after `since`, oldest first. Auth is a shared token stored in the
    `alert_token` admin setting (auto-generated on boot, visible on the admin
    settings page so Razi can copy it into the cron).
"""
from datetime import datetime

from flask import Blueprint, jsonify, request

from models import ContactRequest, db, get_setting

bp = Blueprint("api", __name__, url_prefix="/api")


def _parse_since(raw):
    """Parse ISO8601 -> naive UTC datetime, or None when invalid."""
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.replace(tzinfo=None)


@bp.route("/payment-events")
def payment_events():
    token = request.args.get("token", "")
    if not token or token != get_setting("alert_token"):
        return jsonify({"error": "forbidden"}), 403
    since = _parse_since(request.args.get("since", ""))
    if since is None:
        return jsonify({"error": "bad or missing since; use ISO8601"}), 400

    events = []
    crs = (ContactRequest.query
           .filter(db.or_(ContactRequest.renter_paid_at.isnot(None),
                          ContactRequest.landlord_paid_at.isnot(None)))
           .all())
    for cr in crs:
        for side in ("renter", "landlord"):
            paid_at = getattr(cr, f"{side}_paid_at")
            if not paid_at or paid_at <= since:
                continue
            user = cr.renter if side == "renter" else cr.landlord
            verified = getattr(cr, f"{side}_verified")
            events.append({
                "event_id": f"{cr.id}-{side}",
                "created_at": paid_at.isoformat(),
                "deal_id": cr.id,
                "side": side,
                "payer_name": user.name if user else "",
                "amount": cr.commission,
                "tid": getattr(cr, f"{side}_tid") or "",
                "company": getattr(cr, f"{side}_company") or "",
                # "pending" is reserved; a submission is either auto-verified
                # or waiting for the nightly rechecking window.
                "auto_status": "verified" if verified else "needs_review",
            })
    events.sort(key=lambda e: e["created_at"])
    return jsonify({"events": events})
