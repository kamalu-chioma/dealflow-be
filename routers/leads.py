from fastapi import APIRouter, Depends, HTTPException
from db.deps import get_user_id
from db.supabase import get_supabase
from db.auth import normalize_company_name, validate_website_url
from db.models import LeadCreate, LeadUpdate, DiscoverLeadsRequest
from services import discovery as discovery_service

router = APIRouter(prefix="/leads", tags=["leads"])


@router.get("")
async def list_leads(include_analysis: bool = False, user_id: str = Depends(get_user_id)):
    supabase = get_supabase()
    r = supabase.table("leads").select("*").eq("user_id", user_id).order("updated_at", desc=True).execute()
    leads = r.data or []
    if not include_analysis or not leads:
        return leads
    out = []
    for lead in leads:
        lead_id = lead["id"]
        ar = supabase.table("lead_analyses").select("fit_score, risk_score, recommendation, opportunity_score").eq("lead_id", lead_id).order("created_at", desc=True).limit(1).execute()
        latest = ar.data[0] if ar.data and len(ar.data) > 0 else None
        lead_copy = {**lead, "latest_analysis": latest}
        out.append(lead_copy)
    return out


@router.post("")
async def create_lead(body: LeadCreate, user_id: str = Depends(get_user_id)):
    company_name = normalize_company_name(body.company_name)
    website_url = validate_website_url(body.website_url)
    supabase = get_supabase()
    # Optional duplicate check: same website_url for this user
    existing = supabase.table("leads").select("id, company_name").eq("user_id", user_id).eq("website_url", website_url).execute()
    if existing.data and len(existing.data) > 0:
        raise HTTPException(status_code=409, detail="A lead with this website already exists.")
    row = {
        "user_id": user_id,
        "company_name": company_name,
        "website_url": website_url,
        "geography": body.geography,
        "industry": body.industry,
        "note": body.note,
        "lead_status": body.lead_status or "New Lead",
    }
    r = supabase.table("leads").insert(row).execute()
    if not r.data or len(r.data) == 0:
        raise HTTPException(status_code=500, detail="Failed to create lead")
    return r.data[0]


@router.post("/discover")
async def discover_leads(body: DiscoverLeadsRequest, user_id: str = Depends(get_user_id)):
    try:
        limit = int(body.limit or 10)
        limit = max(1, min(25, limit))
    except Exception:
        limit = 10
    try:
        return discovery_service.discover_leads(user_id=user_id, limit=limit)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=502, detail="Lead discovery failed. Check backend logs.") from e


@router.get("/{lead_id}")
async def get_lead(lead_id: str, user_id: str = Depends(get_user_id)):
    supabase = get_supabase()
    r = supabase.table("leads").select("*").eq("id", lead_id).eq("user_id", user_id).maybe_single().execute()
    if r.data is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    return r.data


@router.patch("/{lead_id}")
async def update_lead(lead_id: str, body: LeadUpdate, user_id: str = Depends(get_user_id)):
    supabase = get_supabase()
    # Ensure ownership
    existing = supabase.table("leads").select("id").eq("id", lead_id).eq("user_id", user_id).execute()
    if not existing.data or len(existing.data) == 0:
        raise HTTPException(status_code=404, detail="Lead not found")
    updates = body.model_dump(exclude_unset=True)
    if "website_url" in updates and updates["website_url"]:
        updates["website_url"] = validate_website_url(updates["website_url"])
    if "company_name" in updates and updates["company_name"]:
        updates["company_name"] = normalize_company_name(updates["company_name"])
    if not updates:
        return await get_lead(lead_id, user_id)
    r = supabase.table("leads").update(updates).eq("id", lead_id).eq("user_id", user_id).execute()
    return r.data[0]


@router.delete("/{lead_id}")
async def delete_lead(lead_id: str, user_id: str = Depends(get_user_id)):
    supabase = get_supabase()
    r = supabase.table("leads").delete().eq("id", lead_id).eq("user_id", user_id).execute()
    if not r.data:
        raise HTTPException(status_code=404, detail="Lead not found")
    return {"ok": True}
