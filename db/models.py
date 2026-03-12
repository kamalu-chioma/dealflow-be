from pydantic import BaseModel
from typing import Optional, Literal
from enum import Enum


class UserType(str, Enum):
    FOUNDER = "founder"
    BUSINESS_OWNER = "business_owner"
    PARTNERSHIPS_LEAD = "partnerships_lead"
    INVESTOR = "investor"
    OTHER = "other"


class Goal(str, Enum):
    PARTNERSHIP = "partnership"
    LEAD_SOURCING = "lead_sourcing"
    STRATEGIC_COLLABORATION = "strategic_collaboration"
    ACQUISITION_WATCH = "acquisition_watch"
    OTHER = "other"


class LeadStatus(str, Enum):
    NEW_LEAD = "New Lead"
    HIGH_PRIORITY = "High Priority"
    WATCHLIST = "Watchlist"
    PASSED = "Passed"


class Recommendation(str, Enum):
    PURSUE = "Pursue"
    MONITOR = "Monitor"
    PASS = "Pass"


# Profile
class ProfileCreate(BaseModel):
    user_type: str
    goal: str
    preferred_sector: Optional[str] = None
    preferred_geography: Optional[str] = None


class ProfileUpdate(BaseModel):
    user_type: Optional[str] = None
    goal: Optional[str] = None
    preferred_sector: Optional[str] = None
    preferred_geography: Optional[str] = None


# Company profile (business context)
class CompanyProfileCreate(BaseModel):
    company_name: Optional[str] = None
    website_url: Optional[str] = None
    industry: Optional[str] = None
    geography: Optional[str] = None
    description: Optional[str] = None
    offerings: Optional[str] = None
    ideal_customer_profile: Optional[str] = None
    target_sectors: Optional[str] = None
    constraints: Optional[str] = None


class CompanyProfileUpdate(BaseModel):
    company_name: Optional[str] = None
    website_url: Optional[str] = None
    industry: Optional[str] = None
    geography: Optional[str] = None
    description: Optional[str] = None
    offerings: Optional[str] = None
    ideal_customer_profile: Optional[str] = None
    target_sectors: Optional[str] = None
    constraints: Optional[str] = None


# Lead
class LeadCreate(BaseModel):
    company_name: str
    website_url: str
    geography: Optional[str] = None
    industry: Optional[str] = None
    note: Optional[str] = None
    lead_status: str = "New Lead"


class LeadUpdate(BaseModel):
    company_name: Optional[str] = None
    website_url: Optional[str] = None
    geography: Optional[str] = None
    industry: Optional[str] = None
    note: Optional[str] = None
    lead_status: Optional[str] = None


# Note
class NoteCreate(BaseModel):
    content: str


# Chat
class ChatMessageCreate(BaseModel):
    message: str


# Compare
class CompareRequest(BaseModel):
    lead_a_id: str
    lead_b_id: str


# Lead discovery
class DiscoverLeadsRequest(BaseModel):
    limit: Optional[int] = 10


class LeadDiscoveryFeedbackCreate(BaseModel):
    website_url: str
    company_name: Optional[str] = None
    decision: Literal["interested", "not_interested"]
