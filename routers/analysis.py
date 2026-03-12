import json
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from datetime import datetime, timezone
from db.deps import get_user_id
from db.supabase import get_supabase
from services.enrichment import run_enrichment
from services import analysis as analysis_service
from services import rag
from openai import OpenAI
from config import OPENAI_API_KEY

router = APIRouter(tags=["analysis"])
openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None


def _t(v: str | None, n: int) -> str:
    s = (v or "").strip()
    return s[:n]


def _format_company_profile_context(row: dict | None) -> str:
    if not row:
        return ""
    parts: list[str] = []
    parts.append("Your company profile (the business doing the evaluation):")
    name = _t(row.get("company_name"), 120)
    if name:
        parts.append(f"- Company name: {name}")
    website = _t(row.get("website_url"), 200)
    if website:
        parts.append(f"- Website: {website}")
    industry = _t(row.get("industry"), 120)
    if industry:
        parts.append(f"- Industry: {industry}")
    geo = _t(row.get("geography"), 120)
    if geo:
        parts.append(f"- Geography: {geo}")
    desc = _t(row.get("description"), 800)
    if desc:
        parts.append(f"- Description: {desc}")
    offerings = _t(row.get("offerings"), 800)
    if offerings:
        parts.append(f"- Offerings: {offerings}")
    icp = _t(row.get("ideal_customer_profile"), 800)
    if icp:
        parts.append(f"- Ideal customer profile: {icp}")
    targets = _t(row.get("target_sectors"), 500)
    if targets:
        parts.append(f"- Target sectors: {targets}")
    constraints = _t(row.get("constraints"), 800)
    if constraints:
        parts.append(f"- Constraints / dealbreakers: {constraints}")
    return "\n".join(parts).strip()


@router.get("/leads/{lead_id}/analysis")
async def get_analysis(lead_id: str, user_id: str = Depends(get_user_id)):
    supabase = get_supabase()
    lead = supabase.table("leads").select("id").eq("id", lead_id).eq("user_id", user_id).maybe_single().execute()
    if lead.data is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    r = supabase.table("lead_analyses").select("*").eq("lead_id", lead_id).order("created_at", desc=True).limit(1).execute()
    if not r.data or len(r.data) == 0:
        return None  # 200 with null body = no analysis yet
    return r.data[0]


@router.get("/leads/{lead_id}/sources")
async def get_sources(lead_id: str, user_id: str = Depends(get_user_id)):
    supabase = get_supabase()
    lead = supabase.table("leads").select("id").eq("id", lead_id).eq("user_id", user_id).maybe_single().execute()
    if lead.data is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    r = supabase.table("sources").select("id, source_type, source_url, title, raw_text, created_at").eq("lead_id", lead_id).execute()
    return r.data or []


@router.get("/leads/{lead_id}/contacts")
async def get_contacts(lead_id: str, user_id: str = Depends(get_user_id)):
    supabase = get_supabase()
    lead = supabase.table("leads").select("id").eq("id", lead_id).eq("user_id", user_id).maybe_single().execute()
    if lead.data is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    r = supabase.table("contacts").select("*").eq("lead_id", lead_id).execute()
    return r.data or []


@router.get("/leads/{lead_id}/outreach-readiness")
async def get_outreach_readiness(lead_id: str, user_id: str = Depends(get_user_id)):
    supabase = get_supabase()
    lead = supabase.table("leads").select("id, website_url").eq("id", lead_id).eq("user_id", user_id).maybe_single().execute()
    if lead.data is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    contacts_r = supabase.table("contacts").select("contact_type").eq("lead_id", lead_id).execute()
    sources_r = supabase.table("sources").select("source_type, source_url").eq("lead_id", lead_id).execute()
    contacts = contacts_r.data or []
    sources = sources_r.data or []
    email_found = any(c.get("contact_type") == "email" for c in contacts)
    phone_found = any(c.get("contact_type") == "phone" for c in contacts)
    website_valid = bool(lead.data.get("website_url", "").strip())
    contact_page_available = any(
        s.get("source_type") in ("contact", "about") or "contact" in (s.get("source_url") or "").lower()
        for s in sources
    )
    contact_form_found = contact_page_available and (not email_found and not phone_found) or any(
        "contact" in (s.get("source_url") or "").lower() and "form" in (s.get("source_url") or "").lower()
        for s in sources
    )
    return {
        "contact_form_found": contact_form_found,
        "email_found": email_found,
        "phone_found": phone_found,
        "website_valid": website_valid,
        "contact_page_available": contact_page_available,
    }


@router.post("/leads/{lead_id}/generate-outreach-email")
async def generate_outreach_email(lead_id: str, user_id: str = Depends(get_user_id)):
    supabase = get_supabase()
    lead = supabase.table("leads").select("id, company_name, website_url").eq("id", lead_id).eq("user_id", user_id).maybe_single().execute()
    if lead.data is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    ar = supabase.table("lead_analyses").select("company_summary, recommendation, recommendation_reason").eq("lead_id", lead_id).order("created_at", desc=True).limit(1).execute()
    analysis = ar.data[0] if ar.data and len(ar.data) > 0 else {}
    if not openai_client:
        raise HTTPException(status_code=503, detail="OpenAI not configured")
    company_name = lead.data.get("company_name") or "this company"
    summary = analysis.get("company_summary") or ""
    rec = analysis.get("recommendation") or "Monitor"
    rec_reason = analysis.get("recommendation_reason") or ""
    prompt = f"""Draft a short B2B outreach email to {company_name}. Context: {summary}. Our internal recommendation: {rec}. Reason: {rec_reason}.
Output valid JSON with keys: subject (string), greeting (string), body (string, 2-3 sentences), cta (string, one call-to-action). Be professional and concise."""
    try:
        resp = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.5,
        )
        data = json.loads(resp.choices[0].message.content or "{}")
        return {
            "subject": data.get("subject", ""),
            "greeting": data.get("greeting", ""),
            "body": data.get("body", ""),
            "cta": data.get("cta", ""),
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.post("/leads/{lead_id}/analyze")
async def analyze_lead(
    lead_id: str,
    background_tasks: BackgroundTasks,
    background: bool = False,
    user_id: str = Depends(get_user_id),
):
    supabase = get_supabase()
    lead = supabase.table("leads").select("*").eq("id", lead_id).eq("user_id", user_id).maybe_single().execute()
    if lead.data is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    lead_row = lead.data

    def _run_pipeline_safe(lid: str, uid: str):
        sb = get_supabase()
        try:
            lead_r = sb.table("leads").select("*").eq("id", lid).eq("user_id", uid).maybe_single().execute()
            if lead_r.data is None:
                return
            row = lead_r.data
            website_url = row.get("website_url") or ""
            company_name = row.get("company_name") or ""

            _, _, combined_text = run_enrichment(lid, website_url, company_name, uid)

            profile_row = None
            try:
                prof = sb.table("profiles").select("goal, preferred_sector, preferred_geography").eq("user_id", uid).maybe_single().execute()
                profile_row = prof.data
            except Exception:
                pass

            user_goal = (profile_row or {}).get("goal") or ""
            user_sector = (profile_row or {}).get("preferred_sector") or ""
            user_geo = (profile_row or {}).get("preferred_geography") or ""

            company_profile_row = None
            try:
                cp = (
                    sb.table("company_profiles")
                    .select(
                        "company_name, website_url, industry, geography, description, offerings, ideal_customer_profile, target_sectors, constraints"
                    )
                    .eq("user_id", uid)
                    .maybe_single()
                    .execute()
                )
                company_profile_row = cp.data
            except Exception:
                pass
            company_profile_context = _format_company_profile_context(company_profile_row)

            result = analysis_service.run_analysis(
                combined_text,
                user_goal,
                user_sector,
                user_geo,
                company_profile_context,
            )

            sb.table("lead_analyses").insert({"lead_id": lid, **result}).execute()

            try:
                rag.chunk_and_embed_sources(lid)
            except Exception:
                pass

            try:
                sb.table("leads").update({"updated_at": datetime.now(timezone.utc).isoformat()}).eq("id", lid).execute()
            except Exception:
                pass
        except Exception as e:
            import traceback

            print(f"[analyze] Background analysis failed for lead_id={lid}: {e}\n{traceback.format_exc()}")

    if background:
        background_tasks.add_task(_run_pipeline_safe, lead_id, user_id)
        return {"ok": True, "message": "Analysis queued"}

    # Synchronous execution (existing behavior)
    website_url = lead_row.get("website_url") or ""
    company_name = lead_row.get("company_name") or ""

    try:
        _, _, combined_text = run_enrichment(lead_id, website_url, company_name, user_id)
    except Exception as e:
        import traceback
        print(f"[analyze] Enrichment error: {traceback.format_exc()}")
        raise HTTPException(status_code=502, detail=f"Enrichment failed: {str(e)}") from e

    profile_row = None
    try:
        prof = supabase.table("profiles").select("goal, preferred_sector, preferred_geography").eq("user_id", user_id).maybe_single().execute()
        profile_row = prof.data
    except Exception:
        pass

    user_goal = (profile_row or {}).get("goal") or ""
    user_sector = (profile_row or {}).get("preferred_sector") or ""
    user_geo = (profile_row or {}).get("preferred_geography") or ""

    company_profile_row = None
    try:
        cp = (
            supabase.table("company_profiles")
            .select(
                "company_name, website_url, industry, geography, description, offerings, ideal_customer_profile, target_sectors, constraints"
            )
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        company_profile_row = cp.data
    except Exception:
        pass
    company_profile_context = _format_company_profile_context(company_profile_row)

    try:
        result = analysis_service.run_analysis(
            combined_text,
            user_goal,
            user_sector,
            user_geo,
            company_profile_context,
        )
    except Exception as e:
        import traceback
        print(f"[analyze] Analysis error: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}") from e

    try:
        supabase.table("lead_analyses").insert({
            "lead_id": lead_id,
            **result,
        }).execute()
    except Exception as e:
        import traceback
        print(f"[analyze] DB insert error: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Failed to save analysis: {str(e)}") from e

    try:
        rag.chunk_and_embed_sources(lead_id)
    except Exception:
        pass

    try:
        supabase.table("leads").update({"updated_at": datetime.now(timezone.utc).isoformat()}).eq("id", lead_id).execute()
    except Exception:
        pass

    return {"ok": True, "message": "Analysis complete"}
