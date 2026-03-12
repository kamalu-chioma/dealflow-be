import json
from openai import OpenAI
from config import OPENAI_API_KEY

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

ANALYSIS_SYSTEM = """You are an analyst that turns raw company information into a structured B2B lead profile with clear explainability.
Output valid JSON only, with these exact keys: company_summary, offering_summary, sector_guess, geography_guess, fit_score, risk_score, confidence_score, strengths (array of strings), red_flags (array of strings), recommendation, recommendation_reason, fit_reasoning, risk_reasoning, top_evidence_signals (array of 3-5 short strings: visible public signals that influenced the analysis), confidence_reasoning.
- fit_score, risk_score, confidence_score: integers 1-10. fit = relevance to user goal, risk = visible concerns, confidence = how reliable the analysis is given the evidence.
- recommendation: exactly one of "Pursue", "Monitor", "Pass".
- fit_reasoning: 1-2 sentences explaining why the company is or is not a fit for the user's goal.
- risk_reasoning: 1-2 sentences explaining why risk is high or low based on visible signals.
- confidence_reasoning: 1 sentence on how much evidence was available and any gaps.
- top_evidence_signals: 3-5 short bullet-style strings (e.g. "Clear product description on homepage", "No financials found").
- Be concise. If information is missing, infer cautiously and lower confidence_score."""


def run_analysis(
    combined_text: str,
    user_goal: str = "",
    user_sector: str = "",
    user_geography: str = "",
    company_profile_context: str = "",
) -> dict:
    if not client:
        return _fallback_analysis(combined_text)
    user_context = (
        f"User goal: {user_goal}. Preferred sector: {user_sector}. Geography: {user_geography}."
        if (user_goal or user_sector or user_geography)
        else "No user context."
    )
    profile_context = company_profile_context.strip()
    prompt = (
        f"{user_context}\n\n"
        + (f"{profile_context}\n\n" if profile_context else "")
        + "Company information:\n\n"
        + combined_text[:30000]
    )
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": ANALYSIS_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
        )
        raw = resp.choices[0].message.content
        data = json.loads(raw)
        # Normalize keys to snake_case for DB
        return {
            "company_summary": data.get("company_summary", ""),
            "offering_summary": data.get("offering_summary", ""),
            "sector_guess": data.get("sector_guess"),
            "geography_guess": data.get("geography_guess"),
            "fit_score": _int_score(data.get("fit_score")),
            "risk_score": _int_score(data.get("risk_score")),
            "confidence_score": _int_score(data.get("confidence_score")),
            "recommendation": data.get("recommendation") or "Monitor",
            "recommendation_reason": data.get("recommendation_reason", ""),
            "strengths_json": data.get("strengths", []),
            "red_flags_json": data.get("red_flags", []),
            "fit_reasoning": data.get("fit_reasoning", ""),
            "risk_reasoning": data.get("risk_reasoning", ""),
            "top_evidence_signals": data.get("top_evidence_signals", []),
            "confidence_reasoning": data.get("confidence_reasoning", ""),
        }
    except Exception:
        return _fallback_analysis(combined_text)


def _int_score(v) -> int:
    if v is None:
        return 5
    try:
        return max(1, min(10, int(v)))
    except (TypeError, ValueError):
        return 5


def _fallback_analysis(text: str) -> dict:
    return {
        "company_summary": (text[:1500] + "...") if len(text) > 1500 else text or "No content available.",
        "offering_summary": "",
        "sector_guess": None,
        "geography_guess": None,
        "fit_score": 5,
        "risk_score": 5,
        "confidence_score": 2,
        "recommendation": "Monitor",
        "recommendation_reason": "Analysis could not be completed; limited or no content.",
        "strengths_json": [],
        "red_flags_json": [],
        "fit_reasoning": "",
        "risk_reasoning": "",
        "top_evidence_signals": [],
        "confidence_reasoning": "Limited evidence available; analysis may be unreliable.",
        "opportunity_score": 5,
    }
