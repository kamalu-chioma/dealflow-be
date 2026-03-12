from fastapi import APIRouter, Depends, HTTPException
from db.deps import get_user_id
from db.supabase import get_supabase
from db.models import CompareRequest
from openai import OpenAI
from config import OPENAI_API_KEY
import json

router = APIRouter(tags=["compare"])
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

COMPARE_SYSTEM = """You compare two B2B companies for a user's goal. Output valid JSON with: preferred_company ("A" or "B"), stronger_fit_reason, key_tradeoffs (string), higher_risk_company ("A" or "B" or "neither"), summary (short comparison)."""

def _t(v, n: int) -> str:
    s = (v or "")
    if not isinstance(s, str):
        s = str(s)
    s = s.strip()
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


@router.post("/compare")
async def compare(body: CompareRequest, user_id: str = Depends(get_user_id)):
    supabase = get_supabase()
    for lid in [body.lead_a_id, body.lead_b_id]:
        lead = supabase.table("leads").select("id").eq("id", lid).eq("user_id", user_id).maybe_single().execute()
        if lead.data is None:
            raise HTTPException(status_code=404, detail=f"Lead not found: {lid}")

    a_analysis = supabase.table("lead_analyses").select("*").eq("lead_id", body.lead_a_id).order("created_at", desc=True).limit(1).execute()
    b_analysis = supabase.table("lead_analyses").select("*").eq("lead_id", body.lead_b_id).order("created_at", desc=True).limit(1).execute()
    if not a_analysis.data or not b_analysis.data:
        raise HTTPException(status_code=400, detail="Both leads must have an analysis. Run analysis on each lead first.")

    profile = supabase.table("profiles").select("goal, preferred_sector, preferred_geography").eq("user_id", user_id).maybe_single().execute()
    user_goal = (profile.data or {}).get("goal") or ""
    user_sector = (profile.data or {}).get("preferred_sector") or ""
    user_geo = (profile.data or {}).get("preferred_geography") or ""

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

    a_row = a_analysis.data[0]
    b_row = b_analysis.data[0]
    prompt = f"""User goal: {user_goal}
Preferred sector: {user_sector}
Preferred geography: {user_geo}

{company_profile_context}

Company A: fit={a_row.get('fit_score')}, risk={a_row.get('risk_score')}, recommendation={a_row.get('recommendation')}
Summary: {a_row.get('company_summary', '')[:500]}
Strengths: {a_row.get('strengths_json', [])}
Red flags: {a_row.get('red_flags_json', [])}

Company B: fit={b_row.get('fit_score')}, risk={b_row.get('risk_score')}, recommendation={b_row.get('recommendation')}
Summary: {b_row.get('company_summary', '')[:500]}
Strengths: {b_row.get('strengths_json', [])}
Red flags: {b_row.get('red_flags_json', [])}

Compare and recommend which company to prioritize."""

    if not client:
        return {
            "preferred_company": "A",
            "summary": "Comparison not available (missing API key).",
            "stronger_fit_reason": "",
            "key_tradeoffs": "",
            "higher_risk_company": "neither",
        }

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": COMPARE_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
        )
        data = json.loads(resp.choices[0].message.content or "{}")
        preferred = data.get("preferred_company", "A")
        preferred_lead_id = body.lead_a_id if preferred == "A" else body.lead_b_id
        supabase.table("comparisons").insert({
            "user_id": user_id,
            "lead_a_id": body.lead_a_id,
            "lead_b_id": body.lead_b_id,
            "summary": data.get("summary"),
            "preferred_lead_id": preferred_lead_id,
            "tradeoff_notes": data.get("key_tradeoffs"),
        }).execute()
        return {
            "preferred_company": preferred,
            "preferred_lead_id": preferred_lead_id,
            "summary": data.get("summary"),
            "stronger_fit_reason": data.get("stronger_fit_reason"),
            "key_tradeoffs": data.get("key_tradeoffs"),
            "higher_risk_company": data.get("higher_risk_company", "neither"),
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.get("/comparisons")
async def list_comparisons(user_id: str = Depends(get_user_id)):
    supabase = get_supabase()
    r = supabase.table("comparisons").select("*").eq("user_id", user_id).order("created_at", desc=True).limit(20).execute()
    return r.data or []
