from fastapi import APIRouter, Depends, HTTPException

from db.deps import get_user_id
from db.supabase import get_supabase
from db.models import CompanyProfileCreate, CompanyProfileUpdate

router = APIRouter(prefix="/company-profile", tags=["company-profile"])


@router.get("")
async def get_company_profile(user_id: str = Depends(get_user_id)):
    supabase = get_supabase()
    r = (
        supabase.table("company_profiles")
        .select("*")
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    if not r or r.data is None:
        raise HTTPException(status_code=404, detail="Company profile not found")
    return r.data


@router.post("")
async def create_company_profile(body: CompanyProfileCreate, user_id: str = Depends(get_user_id)):
    supabase = get_supabase()
    existing = supabase.table("company_profiles").select("id").eq("user_id", user_id).execute()
    if existing.data and len(existing.data) > 0:
        raise HTTPException(status_code=400, detail="Company profile already exists")

    row = {
        "user_id": user_id,
        **body.model_dump(exclude_unset=True),
    }
    r = supabase.table("company_profiles").insert(row).execute()
    if not r.data or len(r.data) == 0:
        raise HTTPException(status_code=500, detail="Failed to create company profile")
    return r.data[0]


@router.patch("")
async def update_company_profile(body: CompanyProfileUpdate, user_id: str = Depends(get_user_id)):
    supabase = get_supabase()
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        return await get_company_profile(user_id)
    r = supabase.table("company_profiles").update(updates).eq("user_id", user_id).execute()
    if not r.data or len(r.data) == 0:
        raise HTTPException(status_code=404, detail="Company profile not found")
    return r.data[0]

