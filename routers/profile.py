from fastapi import APIRouter, Depends, HTTPException
from db.deps import get_user_id
from db.supabase import get_supabase
from db.models import ProfileCreate, ProfileUpdate

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("")
async def get_profile(user_id: str = Depends(get_user_id)):
    supabase = get_supabase()
    r = supabase.table("profiles").select("*").eq("user_id", user_id).maybe_single().execute()
    if not r or r.data is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return r.data


@router.post("")
async def create_profile(body: ProfileCreate, user_id: str = Depends(get_user_id)):
    supabase = get_supabase()
    existing = supabase.table("profiles").select("id").eq("user_id", user_id).execute()
    if existing.data and len(existing.data) > 0:
        raise HTTPException(status_code=400, detail="Profile already exists")
    row = {
        "user_id": user_id,
        "user_type": body.user_type,
        "goal": body.goal,
        "preferred_sector": body.preferred_sector,
        "preferred_geography": body.preferred_geography,
    }
    r = supabase.table("profiles").insert(row).execute()
    if not r.data or len(r.data) == 0:
        raise HTTPException(status_code=500, detail="Failed to create profile")
    return r.data[0]


@router.patch("")
async def update_profile(body: ProfileUpdate, user_id: str = Depends(get_user_id)):
    supabase = get_supabase()
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        return await get_profile(user_id)
    r = supabase.table("profiles").update(updates).eq("user_id", user_id).execute()
    if not r.data or len(r.data) == 0:
        raise HTTPException(status_code=404, detail="Profile not found")
    return r.data[0]
