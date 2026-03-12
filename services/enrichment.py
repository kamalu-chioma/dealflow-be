import re
import httpx
from openai import OpenAI
from config import OPENAI_API_KEY, JINA_READER_URL, TAVILY_API_KEY
from db.supabase import get_supabase

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
CHUNK_SIZE = 800
CHUNK_OVERLAP = 100
EMBEDDING_MODEL = "text-embedding-3-small"
DIMENSION = 1536

# Regex for contact extraction
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
PHONE_RE = re.compile(r"(?:\+?1[-.\s]?)?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}")


def run_enrichment(lead_id: str, website_url: str, company_name: str, user_id: str):
    """
    Fetch website content (Jina, optional Tavily), extract contacts, write to sources and contacts.
    Returns (sources_count, contacts_count, combined_text) for downstream analysis.
    """
    supabase = get_supabase()
    # Clear previous enrichment for this lead so re-analyze doesn't duplicate
    try:
        supabase.table("sources").delete().eq("lead_id", lead_id).execute()
        supabase.table("contacts").delete().eq("lead_id", lead_id).execute()
    except Exception:
        pass
    combined_parts = []

    # 1) Fetch website via Jina Reader
    if website_url and website_url.strip():
        url = (website_url.strip() if website_url.startswith("http") else "https://" + website_url.strip())
        jina_url = f"{JINA_READER_URL.rstrip('/')}/{url}"
        try:
            with httpx.Client(timeout=30.0) as http:
                r = http.get(jina_url, headers={"X-Return-Format": "text"})
                r.raise_for_status()
                body = (r.text or "").strip()
                if body:
                    combined_parts.append(body)
                    supabase.table("sources").insert({
                        "lead_id": lead_id,
                        "source_type": "homepage",
                        "source_url": url,
                        "title": company_name or "Homepage",
                        "raw_text": body[:100000],
                    }).execute()
        except Exception:
            pass

    # 2) Optional Tavily search for extra context (Bearer auth)
    if TAVILY_API_KEY and company_name:
        try:
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {TAVILY_API_KEY}"}
            with httpx.Client(timeout=15.0) as http:
                r = http.post(
                    "https://api.tavily.com/search",
                    headers=headers,
                    json={
                        "query": f"{company_name} company",
                        "search_depth": "basic",
                        "max_results": 3,
                    },
                    timeout=15.0,
                )
                if r.is_success:
                    data = r.json()
                    for hit in (data.get("results") or [])[:3]:
                        content = (hit.get("content") or "").strip()
                        if content:
                            combined_parts.append(content)
                            supabase.table("sources").insert({
                                "lead_id": lead_id,
                                "source_type": "search",
                                "source_url": hit.get("url", ""),
                                "title": (hit.get("title") or "")[:500],
                                "raw_text": content[:50000],
                            }).execute()
        except Exception:
            pass

    combined_text = "\n\n".join(combined_parts) if combined_parts else ""

    # 3) Extract contacts from combined text and insert
    emails = list(dict.fromkeys(EMAIL_RE.findall(combined_text)))
    phones = list(dict.fromkeys(PHONE_RE.findall(combined_text)))
    # Filter obvious false positives
    emails = [e for e in emails if not e.endswith(".png") and not e.endswith(".jpg") and "example" not in e.lower()]
    for email in emails[:20]:
        try:
            supabase.table("contacts").insert({
                "lead_id": lead_id,
                "contact_type": "email",
                "contact_value": email,
                "source_url": website_url or None,
            }).execute()
        except Exception:
            pass
    for phone in phones[:10]:
        try:
            supabase.table("contacts").insert({
                "lead_id": lead_id,
                "contact_type": "phone",
                "contact_value": phone,
                "source_url": website_url or None,
            }).execute()
        except Exception:
            pass

    sources_count = len(combined_parts)  # approximate
    contacts_count = len(emails[:20]) + len(phones[:10])
    return (sources_count, contacts_count, combined_text)


def chunk_text(text: str) -> list[str]:
    if not text or len(text) < 100:
        return [text] if text else []
    chunks = []
    start = 0
    while start < len(text):
        end = start + CHUNK_SIZE
        if end < len(text):
            # Try to break at sentence or newline
            segment = text[start:end + 200]
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


def chunk_and_embed_sources(lead_id: str, source_rows: list[dict]) -> None:
    """Given source rows with raw_text, chunk and embed them.

    NOTE: For now this function only computes embeddings and does not persist
    them back to the database. The signature is kept so it can be wired into
    the RAG pipeline without breaking callers.
    """
    if not source_rows:
        return

    for row in source_rows:
        raw = (row.get("raw_text") or "")[:50000]
        if not raw:
            continue
        chunks = chunk_text(raw)
        if not chunks:
            continue
        _ = get_embeddings(chunks)