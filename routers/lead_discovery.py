from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException

from db.deps import get_user_id
from db.supabase import get_supabase
from db.auth import validate_website_url
from db.models import LeadDiscoveryFeedbackCreate


router = APIRouter(prefix="/lead-discovery", tags=["lead-discovery"])


def _normalize_domain(url: str) -> str:
    try:
        p = urlparse(url.strip())
        host = (p.netloc or "").lower()
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


@router.post("/feedback")
async def record_feedback(body: LeadDiscoveryFeedbackCreate, user_id: str = Depends(get_user_id)):
    website_url = validate_website_url(body.website_url)
    domain = _normalize_domain(website_url)
    if not domain:
        raise HTTPException(status_code=400, detail="Invalid website URL domain")

    supabase = get_supabase()
    # Upsert-like behavior using the unique index (user_id, domain)
    existing = (
        supabase.table("lead_discovery_feedback")
        .select("id")
        .eq("user_id", user_id)
        .eq("domain", domain)
        .maybe_single()
        .execute()
    )

    row = {
        "user_id": user_id,
        "website_url": website_url,
        "domain": domain,
        "company_name": (body.company_name or "").strip() or None,
        "decision": body.decision,
    }

    if existing.data and existing.data.get("id"):
        supabase.table("lead_discovery_feedback").update(row).eq("id", existing.data["id"]).execute()
    else:
        supabase.table("lead_discovery_feedback").insert(row).execute()

    return {"ok": True}

