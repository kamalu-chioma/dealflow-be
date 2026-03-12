import re
from openai import OpenAI
from config import OPENAI_API_KEY
from db.supabase import get_supabase

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
CHUNK_SIZE = 800
CHUNK_OVERLAP = 100
EMBEDDING_MODEL = "text-embedding-3-small"


def chunk_text(text: str) -> list[str]:
    if not text or len(text) < 100:
        return [text] if text else []
    chunks = []
    start = 0
    while start < len(text):
        end = start + CHUNK_SIZE
        if end < len(text):
            segment = text[start : end + 200]
            for sep in [". ", "\n\n", "\n"]:
                last = segment.rfind(sep)
                if last > CHUNK_SIZE // 2:
                    end = start + last + len(sep)
                    break
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end - CHUNK_OVERLAP if end < len(text) else len(text)
    return chunks[:50]


def get_embeddings(texts: list[str]) -> list[list[float]]:
    if not client or not texts:
        return []
    texts = [t[:8000] for t in texts]
    try:
        r = client.embeddings.create(input=texts, model=EMBEDDING_MODEL)
        return [d.embedding for d in r.data]
    except Exception:
        return []


def chunk_and_embed_sources(lead_id: str) -> None:
    """Load sources for lead, chunk raw_text, embed, update first chunk per source and insert rest."""
    supabase = get_supabase()
    r = supabase.table("sources").select("id, raw_text, source_type, source_url, title").eq("lead_id", lead_id).execute()
    rows = r.data or []
    for row in rows:
        raw = (row.get("raw_text") or "")[:50000]
        if not raw:
            continue
        chunks = chunk_text(raw)
        if not chunks:
            continue
        embeddings = get_embeddings(chunks)
        if len(embeddings) < len(chunks):
            embeddings.extend([[0.0] * 1536] * (len(chunks) - len(embeddings)))
        source_id = row["id"]
        lead_id_val = lead_id
        stype = row.get("source_type") or "homepage"
        surl = row.get("source_url") or ""
        title = row.get("title") or ""
        # Update first row with first chunk and embedding
        supabase.table("sources").update({
            "chunk_text": chunks[0],
            "embedding": embeddings[0] if embeddings else None,
        }).eq("id", source_id).execute()
        # Insert remaining chunks as new rows
        for i in range(1, len(chunks)):
            ins = {
                "lead_id": lead_id_val,
                "source_type": stype,
                "source_url": surl,
                "title": title,
                "raw_text": raw[:10000],
                "chunk_text": chunks[i],
                "embedding": embeddings[i] if i < len(embeddings) else None,
            }
            supabase.table("sources").insert(ins).execute()
