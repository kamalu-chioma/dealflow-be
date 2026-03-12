from fastapi import APIRouter, Depends, HTTPException
from db.deps import get_user_id
from db.supabase import get_supabase
from db.models import NoteCreate

router = APIRouter(tags=["notes"])


@router.get("/leads/{lead_id}/notes")
async def list_notes(lead_id: str, user_id: str = Depends(get_user_id)):
    supabase = get_supabase()
    lead = supabase.table("leads").select("id").eq("id", lead_id).eq("user_id", user_id).maybe_single().execute()
    if lead.data is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    r = supabase.table("notes").select("*").eq("lead_id", lead_id).order("created_at", desc=True).execute()
    return r.data or []


@router.post("/leads/{lead_id}/notes")
async def create_note(lead_id: str, body: NoteCreate, user_id: str = Depends(get_user_id)):
    supabase = get_supabase()
    lead = supabase.table("leads").select("id").eq("id", lead_id).eq("user_id", user_id).maybe_single().execute()
    if lead.data is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    row = {"lead_id": lead_id, "user_id": user_id, "content": body.content}
    r = supabase.table("notes").insert(row).execute()
    if not r.data or len(r.data) == 0:
        raise HTTPException(status_code=500, detail="Failed to create note")
    return r.data[0]
