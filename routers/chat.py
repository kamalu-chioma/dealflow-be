from fastapi import APIRouter, Depends, HTTPException
from db.deps import get_user_id
from db.supabase import get_supabase
from db.models import ChatMessageCreate
from services.rag import get_embeddings
from openai import OpenAI
from config import OPENAI_API_KEY

router = APIRouter(tags=["chat"])
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

RAG_SYSTEM = """Answer the user's question using ONLY the provided context from a saved company profile. Be concise and grounded. If the context does not contain enough information, say so. Do not make up information."""


def _retrieve_chunks(lead_id: str, query: str, k: int = 5) -> list[str]:
    supabase = get_supabase()
    r = supabase.table("sources").select("chunk_text").eq("lead_id", lead_id).not_.is_("chunk_text", "null").limit(k * 2).execute()
    return [x["chunk_text"] for x in (r.data or []) if x.get("chunk_text")][:k]


@router.post("/leads/{lead_id}/chat")
async def chat(lead_id: str, body: ChatMessageCreate, user_id: str = Depends(get_user_id)):
    supabase = get_supabase()
    lead = supabase.table("leads").select("id").eq("id", lead_id).eq("user_id", user_id).maybe_single().execute()
    if lead.data is None:
        raise HTTPException(status_code=404, detail="Lead not found")

    session_r = supabase.table("chat_sessions").select("id").eq("user_id", user_id).eq("lead_id", lead_id).order("created_at", desc=True).limit(1).execute()
    session_id = session_r.data[0]["id"] if session_r.data else None
    if not session_id:
        ins = supabase.table("chat_sessions").insert({"user_id": user_id, "lead_id": lead_id}).execute()
        session_id = ins.data[0]["id"] if ins.data else None
    if not session_id:
        raise HTTPException(status_code=500, detail="Could not create chat session")

    supabase.table("chat_messages").insert({"session_id": session_id, "role": "user", "content": body.message}).execute()

    context_chunks = _retrieve_chunks(lead_id, body.message, k=5)
    context = "\n\n".join(context_chunks) if context_chunks else "No saved context for this lead."

    if not client:
        reply = "Chat is not configured (missing OpenAI API key)."
    else:
        try:
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": RAG_SYSTEM + "\n\nContext:\n" + context[:15000]},
                    {"role": "user", "content": body.message},
                ],
                temperature=0.2,
            )
            reply = resp.choices[0].message.content or ""
        except Exception as e:
            reply = f"Sorry, I couldn't generate a response: {str(e)}"

    supabase.table("chat_messages").insert({"session_id": session_id, "role": "assistant", "content": reply}).execute()
    return {"reply": reply, "session_id": session_id}


@router.get("/chat-sessions/{session_id}")
async def get_chat_session(session_id: str, user_id: str = Depends(get_user_id)):
    supabase = get_supabase()
    sess = supabase.table("chat_sessions").select("*").eq("id", session_id).eq("user_id", user_id).maybe_single().execute()
    if sess.data is None:
        raise HTTPException(status_code=404, detail="Session not found")
    msgs = supabase.table("chat_messages").select("*").eq("session_id", session_id).order("created_at").execute()
    return {"session": sess.data, "messages": msgs.data or []}


@router.get("/leads/{lead_id}/chat-session")
async def get_lead_chat_session(lead_id: str, user_id: str = Depends(get_user_id)):
    supabase = get_supabase()
    lead = supabase.table("leads").select("id").eq("id", lead_id).eq("user_id", user_id).maybe_single().execute()
    if lead.data is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    sess = supabase.table("chat_sessions").select("id").eq("user_id", user_id).eq("lead_id", lead_id).order("created_at", desc=True).limit(1).execute()
    if not sess.data:
        return {"session_id": None, "messages": []}
    session_id = sess.data[0]["id"]
    msgs = supabase.table("chat_messages").select("*").eq("session_id", session_id).order("created_at").execute()
    return {"session_id": session_id, "messages": msgs.data or []}
