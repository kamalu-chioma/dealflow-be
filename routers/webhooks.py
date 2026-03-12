"""
Inbound email webhook: accept only direct replies (In-Reply-To matches a sent message).
"""
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Request

from config import INBOUND_WEBHOOK_SECRET
from db.supabase import get_supabase

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _normalize_message_id(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    s = (raw or "").strip().strip("<>")
    return s if s else None


def _extract_in_reply_to(body: Dict[str, Any]) -> Optional[str]:
    headers = body.get("headers")
    if isinstance(headers, dict):
        for key in ("In-Reply-To", "in-reply-to", "InReplyTo"):
            if key in headers and headers[key]:
                return _normalize_message_id(str(headers[key]))
    if isinstance(headers, list):
        for h in headers:
            name = (h.get("name") or h.get("key") or "").lower()
            if name == "in-reply-to" and h.get("value"):
                return _normalize_message_id(str(h["value"]))
    if body.get("in_reply_to"):
        return _normalize_message_id(str(body["in_reply_to"]))
    return None


def _extract_references(body: Dict[str, Any]) -> List[str]:
    headers = body.get("headers")
    refs: List[str] = []
    raw = None
    if isinstance(headers, dict):
        for key in ("References", "references"):
            if key in headers and headers[key]:
                raw = str(headers[key])
                break
    if isinstance(headers, list):
        for h in headers:
            name = (h.get("name") or h.get("key") or "").lower()
            if name == "references" and h.get("value"):
                raw = str(h["value"])
                break
    if raw:
        for part in re.split(r"\s+", raw):
            n = _normalize_message_id(part)
            if n:
                refs.append(n)
    return refs


def _extract_from(body: Dict[str, Any]) -> str:
    from_val = body.get("from") or body.get("sender") or body.get("email")
    if isinstance(from_val, str):
        match = re.search(r"<([^>]+)>", from_val)
        if match:
            return match.group(1).strip().lower()
        if "@" in from_val:
            return from_val.strip().lower()
    return ""


def _extract_to(body: Dict[str, Any]) -> str:
    to_val = body.get("to") or body.get("recipient") or body.get("email_to")
    if isinstance(to_val, str):
        match = re.search(r"<([^>]+)>", to_val)
        if match:
            return match.group(1).strip().lower()
        if "@" in to_val:
            return to_val.strip().lower()
    if isinstance(to_val, list) and to_val:
        return _extract_to({"to": to_val[0]})
    return ""


@router.post("/inbound-email")
async def inbound_email_webhook(
    request: Request,
    x_webhook_secret: Optional[str] = Header(None, alias="X-Webhook-Secret"),
):
    """
    Only creates a message if In-Reply-To or References matches our sent email_message_id.
    """
    if INBOUND_WEBHOOK_SECRET and x_webhook_secret != INBOUND_WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    in_reply_to = _extract_in_reply_to(body)
    references = _extract_references(body)
    if not in_reply_to and not references:
        return {"ok": True, "ignored": "not a reply"}

    supabase = get_supabase()
    r = (
        supabase.table("lead_messages")
        .select("id, lead_id, user_id, email_message_id")
        .not_.is_("email_message_id", "null")
        .execute()
    )
    candidates = []
    for row in r.data or []:
        mid = _normalize_message_id(row.get("email_message_id"))
        if mid == in_reply_to:
            candidates.append(row)
            break
        for ref in references:
            if mid == ref:
                candidates.append(row)
                break
        if candidates:
            break

    if not candidates:
        return {"ok": True, "ignored": "no matching outbound message"}

    outbound = candidates[0]
    from_email = _extract_from(body)
    to_email = _extract_to(body)
    subject = (body.get("subject") or "").strip()
    body_text = (body.get("text") or body.get("body_plain") or body.get("body") or "").strip()
    body_html = (body.get("html") or body.get("body_html") or "").strip() or None

    row = {
        "user_id": outbound["user_id"],
        "lead_id": outbound["lead_id"],
        "direction": "inbound",
        "subject": subject or None,
        "body_text": body_text or None,
        "body_html": body_html,
        "from_identity_id": None,
        "to_email": to_email or "inbound@dealflow",
        "from_email": from_email or None,
        "status": "delivered",
        "in_reply_to_message_id": outbound["id"],
    }
    supabase.table("lead_messages").insert(row).execute()
    return {"ok": True, "stored": True}
