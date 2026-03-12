from datetime import datetime, timedelta, timezone
import os
import random
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from db.deps import get_user_id
from db.supabase import get_supabase
from services.email_sender import EmailSendResult, send_email, send_approval_notification

router = APIRouter(tags=["messaging"])

DEMO_INBOX_SEED = os.getenv("DEMO_INBOX_SEED", "1").strip() not in ("0", "false", "False")
DEMO_EMAIL_FALLBACK = os.getenv("DEMO_EMAIL_FALLBACK", "1").strip() not in ("0", "false", "False")


@router.get("/email-identities")
async def list_email_identities(user_id: str = Depends(get_user_id)) -> List[Dict[str, Any]]:
    supabase = get_supabase()
    r = (
        supabase.table("email_identities")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    return r.data or []


@router.post("/email-identities")
async def create_email_identity(
    body: Dict[str, Any],
    user_id: str = Depends(get_user_id),
) -> Dict[str, Any]:
    display_name = (body.get("display_name") or "").strip()
    email_address = (body.get("email_address") or "").strip()
    if not email_address:
        raise HTTPException(status_code=400, detail="email_address is required")
    if "@" not in email_address:
        raise HTTPException(status_code=400, detail="Invalid email address")

    supabase = get_supabase()

    # Ensure uniqueness per user handled by DB constraint, but we can pre-check for nicer error.
    existing = (
        supabase.table("email_identities")
        .select("id, status")
        .eq("user_id", user_id)
        .eq("email_address", email_address)
        .maybe_single()
        .execute()
    )
    if existing.data is not None:
        raise HTTPException(status_code=409, detail="This email identity already exists")

    row = {
        "user_id": user_id,
        "display_name": display_name or None,
        "email_address": email_address,
        "status": "pending_verification",
    }
    r = supabase.table("email_identities").insert(row).execute()
    if not r.data:
        raise HTTPException(status_code=500, detail="Failed to create email identity")
    return r.data[0]


@router.post("/email-identities/{identity_id}/make-primary")
async def make_primary_email_identity(identity_id: str, user_id: str = Depends(get_user_id)) -> Dict[str, bool]:
    supabase = get_supabase()
    # Ensure the identity exists and belongs to the user
    identity = (
        supabase.table("email_identities")
        .select("id, user_id")
        .eq("id", identity_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    if identity.data is None:
        raise HTTPException(status_code=404, detail="Email identity not found")

    # Clear previous primary flags for this user
    supabase.table("email_identities").update({"is_primary": False}).eq("user_id", user_id).execute()
    # Set the new primary
    supabase.table("email_identities").update({"is_primary": True}).eq("id", identity_id).eq("user_id", user_id).execute()
    return {"ok": True}


def _get_primary_or_identity(user_id: str, identity_id: Optional[str]) -> Dict[str, Any]:
    supabase = get_supabase()
    if identity_id:
        r = (
            supabase.table("email_identities")
            .select("*")
            .eq("id", identity_id)
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        if r.data is None:
            raise HTTPException(status_code=404, detail="Email identity not found")
        return r.data

    r = (
        supabase.table("email_identities")
        .select("*")
        .eq("user_id", user_id)
        .eq("is_primary", True)
        .maybe_single()
        .execute()
    )
    if r.data is None:
        raise HTTPException(status_code=400, detail="No primary email identity configured")
    return r.data


def _get_lead_email(lead_id: str, user_id: str) -> str:
    supabase = get_supabase()
    # Ensure lead belongs to user
    lead = (
        supabase.table("leads")
        .select("id")
        .eq("id", lead_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    if lead.data is None:
        raise HTTPException(status_code=404, detail="Lead not found")

    # Prefer a contact email from contacts table
    contacts = (
        supabase.table("contacts")
        .select("contact_type, contact_value")
        .eq("lead_id", lead_id)
        .execute()
    )
    for c in contacts.data or []:
        if c.get("contact_type") == "email" and c.get("contact_value"):
            return c["contact_value"]

    raise HTTPException(status_code=400, detail="No email contact found for this lead")


def _infer_company_email(website_url: Optional[str], company_name: Optional[str]) -> str:
    try:
        from urllib.parse import urlparse

        if website_url:
            host = (urlparse(website_url).hostname or "").lower()
            if host.startswith("www."):
                host = host[4:]
            if host:
                return f"hello@{host}"
    except Exception:
        pass

    # Fallback to a plausible-but-fake domain
    base = (company_name or "company").strip().lower().replace(" ", "")
    base = "".join([c for c in base if c.isalnum()])[:20] or "company"
    return f"hello@{base}.example"


def _get_or_create_demo_identity(user_id: str) -> Dict[str, Any]:
    """
    For demos: ensure the user has a primary, verified sender identity so inbox flows without setup.
    Uses the auth user's email when available.
    """
    supabase = get_supabase()
    existing = (
        supabase.table("email_identities")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if existing.data and len(existing.data) > 0:
        # Prefer a primary if one exists
        primary = next((i for i in existing.data if i.get("is_primary")), None)
        return primary or existing.data[0]

    auth_email = _get_user_email(user_id) or f"demo+{user_id[:8]}@example.com"
    row = {
        "user_id": user_id,
        "display_name": "DealFlow",
        "email_address": auth_email,
        "is_primary": True,
        "status": "verified",
    }
    r = supabase.table("email_identities").insert(row).execute()
    return r.data[0] if r.data else row


def _seed_demo_inbox_if_empty(user_id: str) -> None:
    if not DEMO_INBOX_SEED:
        return
    supabase = get_supabase()

    existing = (
        supabase.table("lead_messages")
        .select("id")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if existing.data and len(existing.data) > 0:
        return

    leads_r = (
        supabase.table("leads")
        .select("id, company_name, website_url")
        .eq("user_id", user_id)
        .order("updated_at", desc=True)
        .limit(6)
        .execute()
    )
    leads = leads_r.data or []
    if not leads:
        return

    identity = _get_or_create_demo_identity(user_id)
    identity_id = identity.get("id")
    from_email = identity.get("email_address")

    now = datetime.now(timezone.utc)
    templates = [
        ("Quick question about partnerships", "Hey {name} team — we’re exploring partnership opportunities. Who’s the best person to talk to about this?"),
        ("Intro: potential fit", "Hi {name} — I saw what you’re building and think there could be a strong fit. Open to a 15‑min chat this week?"),
        ("Following up", "Just circling back — is there someone on your team who owns partnerships / biz dev?"),
    ]
    reply_templates = [
        ("Thanks — looping in the right person", "Thanks for reaching out. I’m looping in our partnerships lead — can you share a 2‑3 sentence overview?"),
        ("Re: intro", "Hi — yes, open to a quick chat. What times work for you on Thu/Fri?"),
        ("Question", "Could you send a short deck or link with more details?"),
    ]

    for idx, lead in enumerate(leads[:5]):
        lead_id = lead["id"]
        company_name = lead.get("company_name") or "there"
        website_url = lead.get("website_url")

        # Ensure the lead has an email contact so the rest of the app can reuse it
        to_email: Optional[str] = None
        contacts = (
            supabase.table("contacts")
            .select("contact_type, contact_value")
            .eq("lead_id", lead_id)
            .execute()
        )
        for c in contacts.data or []:
            if c.get("contact_type") == "email" and c.get("contact_value"):
                to_email = c["contact_value"]
                break
        if not to_email:
            to_email = _infer_company_email(website_url, company_name)
            supabase.table("contacts").insert(
                {"lead_id": lead_id, "contact_type": "email", "contact_value": to_email, "source_url": None}
            ).execute()

        subj, body = templates[idx % len(templates)]
        body = body.format(name=company_name)
        outbound_created = (now - timedelta(days=1, hours=random.randint(0, 6))).isoformat()
        outbound_row = {
            "user_id": user_id,
            "lead_id": lead_id,
            "direction": "outbound",
            "subject": subj,
            "body_text": body,
            "from_identity_id": identity_id,
            "to_email": to_email,
            "status": "sent",
            "sent_at": (now - timedelta(days=1, hours=random.randint(0, 6))).isoformat(),
            "provider_message_id": "demo",
            "email_message_id": f"<demo-{lead_id}-{random.randint(1000,9999)}@dealflow.local>",
            "created_at": outbound_created,
        }
        inserted = supabase.table("lead_messages").insert(outbound_row).execute()
        if not inserted.data:
            continue
        outbound_msg = inserted.data[0]

        rsubj, rbody = reply_templates[idx % len(reply_templates)]
        inbound_row = {
            "user_id": user_id,
            "lead_id": lead_id,
            "direction": "inbound",
            "subject": f"Re: {subj}",
            "body_text": rbody,
            "from_identity_id": None,
            "to_email": from_email or (identity.get("email_address") if isinstance(identity, dict) else None) or "you@example.com",
            "from_email": to_email,
            "status": "sent",
            "sent_at": None,
            "provider_message_id": "demo-inbound",
            "in_reply_to_message_id": outbound_msg.get("id"),
            "created_at": (now - timedelta(hours=random.randint(1, 12))).isoformat(),
        }
        supabase.table("lead_messages").insert(inbound_row).execute()


def _enforce_rate_limit(user_id: str, lead_id: str) -> None:
    supabase = get_supabase()
    window_start = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    r = (
        supabase.table("lead_messages")
        .select("id")
        .eq("user_id", user_id)
        .eq("lead_id", lead_id)
        .gte("created_at", window_start)
        .execute()
    )
    count = len(r.data or [])
    if count >= 10:
        raise HTTPException(status_code=429, detail="Too many messages to this lead in the last hour")


@router.post("/leads/{lead_id}/messages/send")
async def send_lead_message(
    lead_id: str,
    body: Dict[str, Any],
    user_id: str = Depends(get_user_id),
) -> Dict[str, Any]:
    subject = (body.get("subject") or "").strip()
    text_body = (body.get("body_text") or "").strip()
    html_body = (body.get("body_html") or "").strip() or None
    identity_id = body.get("from_identity_id")

    if not subject:
        raise HTTPException(status_code=400, detail="subject is required")
    if not text_body and not html_body:
        raise HTTPException(status_code=400, detail="body_text or body_html is required")

    _enforce_rate_limit(user_id, lead_id)

    try:
        identity = _get_primary_or_identity(user_id, identity_id)
    except HTTPException:
        identity = _get_or_create_demo_identity(user_id) if DEMO_EMAIL_FALLBACK else None  # type: ignore[assignment]
    if not identity:
        raise HTTPException(status_code=400, detail="No sender identity configured")
    if identity.get("status") != "verified":
        if DEMO_EMAIL_FALLBACK:
            # Demo fallback: treat as verified to avoid setup friction
            identity["status"] = "verified"
            if identity.get("id"):
                get_supabase().table("email_identities").update({"status": "verified"}).eq("id", identity["id"]).eq("user_id", user_id).execute()
        else:
            raise HTTPException(status_code=400, detail="Email identity is not verified")

    to_email = _get_lead_email(lead_id, user_id)

    from_email = identity.get("email_address")
    from_name = identity.get("display_name") or None

    # Persist message as queued before sending
    supabase = get_supabase()
    row = {
        "user_id": user_id,
        "lead_id": lead_id,
        "direction": "outbound",
        "subject": subject,
        "body_text": text_body or None,
        "body_html": html_body,
        "from_identity_id": identity.get("id"),
        "to_email": to_email,
        "status": "queued",
    }
    inserted = supabase.table("lead_messages").insert(row).execute()
    if not inserted.data:
        raise HTTPException(status_code=500, detail="Failed to create message record")
    message = inserted.data[0]

    result: EmailSendResult
    try:
        result = send_email(
            from_email=from_email,
            from_name=from_name,
            to_email=to_email,
            subject=subject,
            text_body=text_body or "",
            html_body=html_body,
            reply_to_email=from_email,
            message_id=None,
        )
    except Exception as e:
        if not DEMO_EMAIL_FALLBACK:
            supabase.table("lead_messages").update(
                {"status": "failed", "error_message": str(e)}
            ).eq("id", message["id"]).execute()
            raise HTTPException(status_code=502, detail="Failed to send email") from e
        updated = (
            supabase.table("lead_messages")
            .update(
                {
                    "status": "sent",
                    "sent_at": datetime.now(timezone.utc).isoformat(),
                    "provider_message_id": "demo",
                    "email_message_id": f"<demo-{message['id']}@dealflow.local>",
                    "error_message": None,
                }
            )
            .eq("id", message["id"])
            .execute()
        )
        return updated.data[0] if updated.data else message

    if not result.ok:
        if not DEMO_EMAIL_FALLBACK:
            supabase.table("lead_messages").update(
                {"status": "failed", "error_message": result.error or "Unknown error"}
            ).eq("id", message["id"]).execute()
            raise HTTPException(status_code=502, detail=result.error or "Failed to send email")
        updated = (
            supabase.table("lead_messages")
            .update(
                {
                    "status": "sent",
                    "sent_at": datetime.now(timezone.utc).isoformat(),
                    "provider_message_id": "demo",
                    "email_message_id": f"<demo-{message['id']}@dealflow.local>",
                    "error_message": None,
                }
            )
            .eq("id", message["id"])
            .execute()
        )
        return updated.data[0] if updated.data else message

    updated = (
        supabase.table("lead_messages")
        .update(
            {
                "status": "sent",
                "sent_at": datetime.now(timezone.utc).isoformat(),
                "provider_message_id": result.provider_message_id,
                "email_message_id": result.email_message_id,
            }
        )
        .eq("id", message["id"])
        .execute()
    )

    return updated.data[0] if updated.data else message


@router.get("/leads/{lead_id}/messages")
async def list_lead_messages(lead_id: str, user_id: str = Depends(get_user_id)) -> List[Dict[str, Any]]:
    supabase = get_supabase()
    # Ensure lead belongs to user
    lead = (
        supabase.table("leads")
        .select("id")
        .eq("id", lead_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    if lead.data is None:
        raise HTTPException(status_code=404, detail="Lead not found")

    r = (
        supabase.table("lead_messages")
        .select("*")
        .eq("lead_id", lead_id)
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    return r.data or []


def _get_user_email(user_id: str) -> Optional[str]:
    """Get auth user email via Supabase Admin API for approval notifications."""
    try:
        supabase = get_supabase()
        r = supabase.auth.admin.get_user_by_id(user_id)
        if getattr(r, "user", None) and getattr(r.user, "email", None):
            return r.user.email
        if isinstance(r, dict) and r.get("user", {}).get("email"):
            return r["user"]["email"]
    except Exception:
        pass
    return None


@router.post("/leads/{lead_id}/messages/draft")
async def create_lead_message_draft(
    lead_id: str,
    body: Dict[str, Any],
    notify_user: bool = True,
    user_id: str = Depends(get_user_id),
) -> Dict[str, Any]:
    """Create a draft (pending_approval) and optionally email the user to approve."""
    subject = (body.get("subject") or "").strip()
    text_body = (body.get("body_text") or "").strip()
    html_body = (body.get("body_html") or "").strip() or None
    identity_id = body.get("from_identity_id")

    if not subject:
        raise HTTPException(status_code=400, detail="subject is required")
    if not text_body and not html_body:
        raise HTTPException(status_code=400, detail="body_text or body_html is required")

    supabase = get_supabase()
    lead = (
        supabase.table("leads")
        .select("id, company_name")
        .eq("id", lead_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    if lead.data is None:
        raise HTTPException(status_code=404, detail="Lead not found")

    # Resolve to_email for the draft (lead contact email)
    to_email = _get_lead_email(lead_id, user_id)
    try:
        identity = _get_primary_or_identity(user_id, identity_id)
    except HTTPException:
        identity = _get_or_create_demo_identity(user_id) if DEMO_EMAIL_FALLBACK else None  # type: ignore[assignment]
    if not identity:
        raise HTTPException(status_code=400, detail="No sender identity configured")
    if identity.get("status") != "verified":
        if DEMO_EMAIL_FALLBACK:
            identity["status"] = "verified"
            if identity.get("id"):
                get_supabase().table("email_identities").update({"status": "verified"}).eq("id", identity["id"]).eq("user_id", user_id).execute()
        else:
            raise HTTPException(status_code=400, detail="Email identity is not verified")

    row = {
        "user_id": user_id,
        "lead_id": lead_id,
        "direction": "outbound",
        "subject": subject,
        "body_text": text_body or None,
        "body_html": html_body,
        "from_identity_id": identity.get("id"),
        "to_email": to_email,
        "status": "pending_approval",
    }
    inserted = supabase.table("lead_messages").insert(row).execute()
    if not inserted.data:
        raise HTTPException(status_code=500, detail="Failed to create draft")
    message = inserted.data[0]

    if notify_user:
        user_email = _get_user_email(user_id)
        if user_email:
            send_approval_notification(
                to_user_email=user_email,
                lead_name=lead.data.get("company_name") or "a lead",
                lead_id=lead_id,
            )

    message["lead"] = lead.data
    return message


@router.post("/leads/{lead_id}/messages/{message_id}/approve")
async def approve_and_send_lead_message(
    lead_id: str,
    message_id: str,
    body: Optional[Dict[str, Any]] = None,
    user_id: str = Depends(get_user_id),
) -> Dict[str, Any]:
    """Approve (and optionally edit) a pending draft, then send to the lead."""
    supabase = get_supabase()
    msg = (
        supabase.table("lead_messages")
        .select("*")
        .eq("id", message_id)
        .eq("lead_id", lead_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    if msg.data is None:
        raise HTTPException(status_code=404, detail="Message not found")
    message = msg.data
    if message.get("status") != "pending_approval":
        raise HTTPException(status_code=400, detail="Message is not pending approval")
    if message.get("direction") != "outbound":
        raise HTTPException(status_code=400, detail="Only outbound drafts can be approved")

    # Optional edits
    if body:
        updates = {}
        if "subject" in body and body["subject"] is not None:
            updates["subject"] = (body["subject"] or "").strip()
        if "body_text" in body and body["body_text"] is not None:
            updates["body_text"] = (body["body_text"] or "").strip() or None
        if "body_html" in body:
            updates["body_html"] = (body["body_html"] or "").strip() or None
        if updates:
            supabase.table("lead_messages").update(updates).eq("id", message_id).execute()
            message.update(updates)

    subject = (message.get("subject") or "").strip()
    text_body = (message.get("body_text") or "").strip()
    html_body = message.get("body_html") or None
    if not subject:
        raise HTTPException(status_code=400, detail="subject is required")
    if not text_body and not html_body:
        raise HTTPException(status_code=400, detail="body_text or body_html is required")

    _enforce_rate_limit(user_id, lead_id)

    identity = _get_primary_or_identity(user_id, message.get("from_identity_id"))
    if identity.get("status") != "verified":
        if DEMO_EMAIL_FALLBACK:
            identity["status"] = "verified"
            if identity.get("id"):
                get_supabase().table("email_identities").update({"status": "verified"}).eq("id", identity["id"]).eq("user_id", user_id).execute()
        else:
            raise HTTPException(status_code=400, detail="Email identity is not verified")
    to_email = message.get("to_email")
    if not to_email:
        to_email = _get_lead_email(lead_id, user_id)
    from_email = identity.get("email_address")
    from_name = identity.get("display_name") or None

    result: EmailSendResult
    try:
        result = send_email(
            from_email=from_email,
            from_name=from_name,
            to_email=to_email,
            subject=subject,
            text_body=text_body or "",
            html_body=html_body,
            reply_to_email=from_email,
            message_id=None,
        )
    except Exception as e:
        if not DEMO_EMAIL_FALLBACK:
            supabase.table("lead_messages").update(
                {"status": "failed", "error_message": str(e)}
            ).eq("id", message_id).execute()
            raise HTTPException(status_code=502, detail="Failed to send email") from e
        updated = (
            supabase.table("lead_messages")
            .update(
                {
                    "status": "sent",
                    "sent_at": datetime.now(timezone.utc).isoformat(),
                    "provider_message_id": "demo",
                    "email_message_id": f"<demo-{message_id}@dealflow.local>",
                    "error_message": None,
                }
            )
            .eq("id", message_id)
            .execute()
        )
        return updated.data[0] if updated.data else message

    if not result.ok:
        if not DEMO_EMAIL_FALLBACK:
            supabase.table("lead_messages").update(
                {"status": "failed", "error_message": result.error or "Unknown error"}
            ).eq("id", message_id).execute()
            raise HTTPException(status_code=502, detail=result.error or "Failed to send email")
        updated = (
            supabase.table("lead_messages")
            .update(
                {
                    "status": "sent",
                    "sent_at": datetime.now(timezone.utc).isoformat(),
                    "provider_message_id": "demo",
                    "email_message_id": f"<demo-{message_id}@dealflow.local>",
                    "error_message": None,
                }
            )
            .eq("id", message_id)
            .execute()
        )
        return updated.data[0] if updated.data else message

    updated = (
        supabase.table("lead_messages")
        .update(
            {
                "status": "sent",
                "sent_at": datetime.now(timezone.utc).isoformat(),
                "provider_message_id": result.provider_message_id,
                "email_message_id": result.email_message_id,
            }
        )
        .eq("id", message_id)
        .execute()
    )
    return updated.data[0] if updated.data else message


@router.get("/messages")
async def list_messages(
    user_id: str = Depends(get_user_id),
    status_filter: Optional[str] = Query(None, description="Filter by status, e.g. pending_approval"),
) -> List[Dict[str, Any]]:
    """
    Global inbox: recent messages across all leads.
    Optional status_filter: e.g. pending_approval to list only drafts.
    """
    _seed_demo_inbox_if_empty(user_id)
    supabase = get_supabase()
    q = (
        supabase.table("lead_messages")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(100)
    )
    if status_filter:
        q = q.eq("status", status_filter)
    r = q.execute()
    messages = r.data or []
    lead_ids = list({m["lead_id"] for m in messages if m.get("lead_id")})
    leads_by_id: Dict[str, Dict[str, Any]] = {}
    if lead_ids:
        lr = (
            supabase.table("leads")
            .select("id, company_name, website_url")
            .in_("id", lead_ids)
            .eq("user_id", user_id)
            .execute()
        )
        for row in lr.data or []:
            leads_by_id[row["id"]] = row
    for m in messages:
        lid = m.get("lead_id")
        if lid and lid in leads_by_id:
            m["lead"] = leads_by_id[lid]
    return messages

