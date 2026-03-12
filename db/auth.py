import re
from fastapi import HTTPException


def normalize_company_name(name: str) -> str:
    if not name or not name.strip():
        raise HTTPException(status_code=400, detail="Company name is required")
    return " ".join(name.strip().split())


def validate_website_url(url: str) -> str:
    if not url or not url.strip():
        raise HTTPException(status_code=400, detail="Website URL is required")
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    # Basic URL pattern
    if not re.match(r"^https?://[^\s/$.?#].[^\s]*$", url):
        raise HTTPException(status_code=400, detail="Invalid website URL")
    return url
