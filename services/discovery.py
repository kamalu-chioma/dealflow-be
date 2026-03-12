import json
from urllib.parse import urlparse

import httpx
from openai import OpenAI

from config import OPENAI_API_KEY, TAVILY_API_KEY, APOLLO_API_KEY
from db.supabase import get_supabase
from services.analysis import _int_score


openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

DISCOVERY_SYSTEM = """You are an assistant that turns web search hits into a shortlist of B2B lead candidates.
You must output valid JSON only.

Given:
- the user's goal, preferred sector(s), and geography
- the user's company profile context
- a list of search hits (url, title, snippet)

Return JSON with key: leads (array). Each lead must have:
- company_name (string)
- website_url (string, must be one of the provided hit urls)
- summary (1-2 sentences, concise, based only on the hit snippet/title)
- fit_score (integer 1-10; 10 = very aligned to user's goal/sector/geography)
- fit_reasoning (1 sentence explaining the fit score)

If evidence is weak, lower fit_score and say so in fit_reasoning. Avoid duplicates."""


def _normalize_domain(url: str) -> str:
    try:
        p = urlparse(url.strip())
        host = (p.netloc or "").lower()
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


# Domains to exclude from Tavily so we get company websites only, not social/blog/news
TAVILY_EXCLUDE_DOMAINS = [
    "linkedin.com", "www.linkedin.com",
    "medium.com", "www.medium.com",
    "facebook.com", "www.facebook.com", "fb.com",
    "twitter.com", "www.twitter.com", "x.com",
    "instagram.com", "www.instagram.com",
    "youtube.com", "www.youtube.com",
    "reddit.com", "www.reddit.com",
    "quora.com", "www.quora.com",
    "t.co", "bit.ly",
    "news.ycombinator.com",
    "crunchbase.com", "pitchbook.com",
    "bloomberg.com", "reuters.com", "techcrunch.com", "forbes.com",
    "wikipedia.org", "en.wikipedia.org",
    "glassdoor.com", "indeed.com", "angel.co",
    "producthunt.com", "g2.com", "capterra.com",
]

# URL path segments that indicate a blog post/article, not a company homepage
NON_COMPANY_PATH_PATTERNS = (
    "/post/", "/posts/", "/blog/", "/article/", "/articles/", "/news/",
    "/pulse/", "/feed/", "/author/", "/tag/", "/category/", "/archive/",
    "/story/", "/stories/", "/opinion/", "/press-release/", "/pr/",
    "/linkedin/", "/status/", "/tweet/", "/thread/",
)


def _is_likely_company_url(url: str, domain: str) -> bool:
    """Keep only URLs that look like company homepages, not blog posts or social posts."""
    if not url or not domain:
        return False
    url_lower = url.lower()
    for pattern in NON_COMPANY_PATH_PATTERNS:
        if pattern in url_lower:
            return False
    # Allow root or short path only (e.g. https://company.com or https://company.com/about)
    path = urlparse(url).path.strip("/").lower()
    if path and path.count("/") > 1:
        # Long path like /blog/2024/01/post-title -> skip
        return False
    return True


def _company_profile_keywords(profile_row: dict | None) -> list[str]:
    """Extract short, search-friendly phrases from the company profile."""
    if not profile_row:
        return []
    keywords: list[str] = []
    for field in ("target_sectors", "industry"):
        raw = ((profile_row.get(field) or "")).strip()
        if raw:
            for chunk in raw.split(","):
                chunk = chunk.strip()
                if chunk and len(chunk) < 80:
                    keywords.append(chunk)
    for field in ("ideal_customer_profile", "offerings", "description"):
        raw = ((profile_row.get(field) or "")).strip()
        if not raw:
            continue
        sentences = [s.strip() for s in raw.replace("\n", ". ").split(".") if s.strip()]
        for s in sentences[:3]:
            words = s.split()
            if 2 <= len(words) <= 12:
                keywords.append(s)
    seen: set[str] = set()
    deduped: list[str] = []
    for kw in keywords:
        low = kw.lower()
        if low not in seen:
            seen.add(low)
            deduped.append(kw)
    return deduped[:15]


def _build_queries(
    user_goal: str,
    preferred_sector: str,
    preferred_geo: str,
    company_targets: str,
    profile_keywords: list[str] | None = None,
) -> list[str]:
    sector = (preferred_sector or company_targets or "").strip()
    geo = (preferred_geo or "").strip()
    goal = (user_goal or "").strip()
    kws = profile_keywords or []

    parts = []
    if sector and geo:
        parts.append(f"B2B {sector} companies in {geo}")
        parts.append(f"{sector} vendors {geo} B2B")
    elif sector:
        parts.append(f"B2B {sector} companies")
        parts.append(f"{sector} vendors B2B")
    elif geo:
        parts.append(f"B2B companies in {geo}")

    if goal and sector:
        parts.append(f"{sector} companies for {goal}")
    elif goal:
        parts.append(f"B2B companies for {goal}")

    for kw in kws[:4]:
        q = f"{kw} companies"
        if geo:
            q += f" in {geo}"
        parts.append(q)

    if not parts:
        parts.append("B2B companies SaaS")

    out: list[str] = []
    seen_lower: set[str] = set()
    for q in parts:
        qn = " ".join(q.split())
        if len(qn) > 200:
            qn = qn[:200]
        low = qn.lower()
        if qn and low not in seen_lower:
            seen_lower.add(low)
            out.append(qn)
    return out[:6]


def _t(row: dict | None, key: str, n: int) -> str:
    s = ((row or {}).get(key) or "").strip()
    return s[:n]


def _format_company_profile_context(row: dict | None) -> str:
    if not row:
        return ""
    parts: list[str] = []
    parts.append("Company profile (the business doing the evaluation):")
    for label, key, n in [
        ("Company name", "company_name", 120),
        ("Website", "website_url", 200),
        ("Industry", "industry", 120),
        ("Geography", "geography", 120),
        ("Description", "description", 600),
        ("Offerings", "offerings", 600),
        ("Ideal customer profile", "ideal_customer_profile", 600),
        ("Target sectors", "target_sectors", 400),
        ("Constraints / dealbreakers", "constraints", 600),
    ]:
        v = _t(row, key, n)
        if v:
            parts.append(f"- {label}: {v}")
    return "\n".join(parts).strip()


def _fetch_apollo_hits(
    existing_domains: set[str],
    dismissed_domains: set[str],
    preferred_geo: str,
    company_targets: str,
    limit: int,
) -> list[dict]:
    """Fetch company-only results from Apollo (second source after Tavily). Returns list of hit dicts."""
    if not APOLLO_API_KEY:
        return []
    geo_lower = (preferred_geo or company_targets or "").lower()
    locations: list[str] = []
    if "canada" in geo_lower or "canadian" in geo_lower:
        locations.append("canada")
    elif "usa" in geo_lower or "united states" in geo_lower or "us" in geo_lower:
        locations.append("united states")
    try:
        with httpx.Client(timeout=15.0) as http:
            params: dict = {"per_page": min(25, limit + 10), "page": 1}
            if locations:
                params["organization_locations[]"] = locations
            r = http.post(
                "https://api.apollo.io/api/v1/mixed_companies/search",
                headers={"Content-Type": "application/json", "x-api-key": APOLLO_API_KEY},
                params=params,
            )
            if not r.is_success:
                return []
            data = r.json() or {}
            orgs = data.get("organizations") or []
            out = []
            for org in orgs:
                if not isinstance(org, dict):
                    continue
                name = (org.get("name") or "").strip()
                website_url = (org.get("website_url") or "").strip()
                primary_domain = (org.get("primary_domain") or "").strip()
                if not website_url and primary_domain:
                    website_url = "https://" + primary_domain
                if not website_url:
                    continue
                domain = _normalize_domain(website_url)
                if not domain or domain in existing_domains or domain in dismissed_domains:
                    continue
                out.append({
                    "url": website_url,
                    "domain": domain,
                    "title": name[:300],
                    "snippet": (org.get("short_description") or "")[:800] or "",
                })
            return out
    except Exception:
        return []


def discover_leads(user_id: str, limit: int = 10) -> list[dict]:
    if not TAVILY_API_KEY:
        raise RuntimeError("Tavily not configured")

    supabase = get_supabase()

    # User preferences
    prof = supabase.table("profiles").select("goal, preferred_sector, preferred_geography").eq("user_id", user_id).maybe_single().execute()
    profile_row = prof.data or {}
    user_goal = (profile_row.get("goal") or "").strip()
    preferred_sector = (profile_row.get("preferred_sector") or "").strip()
    preferred_geo = (profile_row.get("preferred_geography") or "").strip()

    # Company profile context
    cp = (
        supabase.table("company_profiles")
        .select("company_name, website_url, industry, geography, description, offerings, ideal_customer_profile, target_sectors, constraints")
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    company_profile_row = cp.data or {}
    company_targets = (company_profile_row.get("target_sectors") or "").strip()
    company_profile_context = _format_company_profile_context(company_profile_row)
    profile_kws = _company_profile_keywords(company_profile_row)

    # Exclusion sets
    existing_domains: set[str] = set()
    try:
        lr = supabase.table("leads").select("website_url").eq("user_id", user_id).execute()
        for row in (lr.data or []):
            d = _normalize_domain((row or {}).get("website_url") or "")
            if d:
                existing_domains.add(d)
    except Exception:
        pass

    dismissed_domains: set[str] = set()
    try:
        fr = (
            supabase.table("lead_discovery_feedback")
            .select("domain, decision")
            .eq("user_id", user_id)
            .execute()
        )
        for row in (fr.data or []):
            if (row or {}).get("decision") == "not_interested":
                d = ((row or {}).get("domain") or "").strip().lower()
                if d:
                    dismissed_domains.add(d)
    except Exception:
        pass

    queries = _build_queries(user_goal, preferred_sector, preferred_geo, company_targets, profile_kws)

    hits: list[dict] = []
    headers = {"Content-Type": "application/json"}
    if TAVILY_API_KEY:
        headers["Authorization"] = f"Bearer {TAVILY_API_KEY}"

    geo_lower = (preferred_geo or company_targets or "").lower()
    country_param = "canada" if "canada" in geo_lower or "canadian" in geo_lower else None

    tavily_auth_error: str | None = None
    for q in queries:
        try:
            with httpx.Client(timeout=20.0) as http:
                payload: dict = {
                    "query": q,
                    "search_depth": "basic",
                    "max_results": 10,
                    "exclude_domains": TAVILY_EXCLUDE_DOMAINS,
                    "api_key": TAVILY_API_KEY,
                }
                if country_param:
                    payload["country"] = country_param
                r = http.post(
                    "https://api.tavily.com/search",
                    headers=headers,
                    json=payload,
                )
                if r.status_code in (401, 403):
                    detail = ""
                    try:
                        detail = r.json().get("detail", r.text[:200])
                    except Exception:
                        detail = r.text[:200]
                    tavily_auth_error = (
                        f"Tavily API returned {r.status_code}. "
                        f"Check TAVILY_API_KEY in backend .env (current key starts with "
                        f"'{TAVILY_API_KEY[:6]}...'). Detail: {detail}"
                    )
                    break
                if not r.is_success:
                    continue
                data = r.json() or {}
                for h in (data.get("results") or [])[:10]:
                    url = (h.get("url") or "").strip()
                    title = (h.get("title") or "").strip()
                    snippet = (h.get("content") or "").strip()
                    if not url:
                        continue
                    domain = _normalize_domain(url)
                    if not domain or domain in existing_domains or domain in dismissed_domains:
                        continue
                    if not _is_likely_company_url(url, domain):
                        continue
                    hits.append({"url": url, "domain": domain, "title": title[:300], "snippet": snippet[:800]})
        except Exception:
            continue

    if tavily_auth_error:
        raise RuntimeError(tavily_auth_error)

    # Second source: Apollo (company-only database). First call was Tavily; add more from Apollo.
    if APOLLO_API_KEY:
        apollo_hits = _fetch_apollo_hits(
            existing_domains, dismissed_domains, preferred_geo, company_targets, limit
        )
        for h in apollo_hits:
            d = h.get("domain") or ""
            if d and d not in existing_domains and d not in dismissed_domains:
                hits.append(h)

    # Dedup by domain and keep a reasonable batch size for the model
    seen: set[str] = set()
    deduped_hits: list[dict] = []
    for h in hits:
        d = h.get("domain") or ""
        if not d or d in seen:
            continue
        seen.add(d)
        deduped_hits.append(h)
    deduped_hits = deduped_hits[: min(30, max(10, limit * 3))]

    if not deduped_hits:
        return []

    if not openai_client:
        out = []
        for h in deduped_hits[:limit]:
            out.append(
                {
                    "company_name": (h.get("title") or h.get("domain") or "Unknown").split("|")[0].strip()[:200],
                    "website_url": h.get("url"),
                    "summary": (h.get("snippet") or "")[:220] or (h.get("title") or "")[:220],
                    "fit_score": 5,
                    "fit_reasoning": "Limited evidence available; enable OpenAI for better fit scoring.",
                }
            )
        return out

    user_context = (
        f"User goal: {user_goal}. Preferred sector: {preferred_sector or company_targets}. Preferred geography: {preferred_geo}."
        if (user_goal or preferred_sector or preferred_geo or company_targets)
        else "No user context."
    )
    prompt = (
        f"{user_context}\n\n"
        + (f"{company_profile_context}\n\n" if company_profile_context else "")
        + "Search hits:\n"
        + "\n".join([f"- url: {h['url']}\n  title: {h.get('title','')}\n  snippet: {h.get('snippet','')}" for h in deduped_hits])
        + "\n\nReturn at most "
        + str(limit)
        + " leads."
    )

    try:
        resp = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": DISCOVERY_SYSTEM}, {"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.3,
        )
        raw = resp.choices[0].message.content or "{}"
        data = json.loads(raw)
        leads = data.get("leads") or []
        out = []
        for item in leads:
            if not isinstance(item, dict):
                continue
            website_url = (item.get("website_url") or "").strip()
            if not website_url:
                continue
            domain = _normalize_domain(website_url)
            if not domain or domain in existing_domains or domain in dismissed_domains:
                continue
            if domain not in {h["domain"] for h in deduped_hits}:
                # Must be one of the provided hits
                continue
            out.append(
                {
                    "company_name": (item.get("company_name") or domain).strip()[:200],
                    "website_url": website_url,
                    "summary": (item.get("summary") or "").strip()[:600],
                    "fit_score": _int_score(item.get("fit_score")),
                    "fit_reasoning": (item.get("fit_reasoning") or "").strip()[:400],
                }
            )

        # Final dedupe by domain
        final: list[dict] = []
        seen_final: set[str] = set()
        for item in out:
            d = _normalize_domain(item.get("website_url") or "")
            if not d or d in seen_final:
                continue
            seen_final.add(d)
            final.append(item)
        return final[:limit]
    except Exception:
        # Fall back to heuristic output
        out = []
        for h in deduped_hits[:limit]:
            out.append(
                {
                    "company_name": (h.get("title") or h.get("domain") or "Unknown").split("|")[0].strip()[:200],
                    "website_url": h.get("url"),
                    "summary": (h.get("snippet") or "")[:220] or (h.get("title") or "")[:220],
                    "fit_score": 5,
                    "fit_reasoning": "Discovery model call failed; showing basic results.",
                }
            )
        return out

