"""Pydantic request/response schemas."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    model_validator,
)

# lowercased so A@x.com and a@x.com are the same account
Email = Annotated[EmailStr, AfterValidator(str.lower)]

# must match the category CHECK constraints in the migrations
Category = Literal["charging", "groceries", "medicine", "water", "transport", "pets", "other"]


def _in_future(value: datetime) -> datetime:
    if value <= datetime.now(timezone.utc):
        raise ValueError("must be in the future")
    return value


# timezone-aware (naive datetimes are rejected) and in the future
FutureDatetime = Annotated[AwareDatetime, AfterValidator(_in_future)]


class UserRegister(BaseModel):
    email: Email
    password: str = Field(min_length=6)
    display_name: str = Field(min_length=1, max_length=100)
    is_resident: bool = False
    is_volunteer: bool = False
    is_organization: bool = False
    org_name: str | None = Field(None, min_length=2, max_length=120)

    @model_validator(mode="after")
    def _org_needs_name(self) -> UserRegister:
        if self.is_organization and not self.org_name:
            raise ValueError("org_name is required for an organization account")
        return self


class UserLogin(BaseModel):
    email: Email
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    display_name: str
    roles: list[str]


class UserOut(BaseModel):
    id: int
    email: str
    display_name: str
    roles: list[str]


class RequestCreate(BaseModel):
    # strip whitespace so a blank description fails min_length
    model_config = ConfigDict(str_strip_whitespace=True)

    category: Category
    description: str = Field(min_length=1)
    title: str | None = None
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    address: str | None = None


class MapItem(BaseModel):
    """Map marker. Requests carry their APPROXIMATE point and never an address."""

    type: Literal["request", "opportunity"]
    id: int
    category: str
    title: str | None
    latitude: float
    longitude: float
    distance_m: float
    start_time: datetime | None = None  # opportunities only
    slots_left: int | None = None  # opportunities only


class ClaimerInfo(BaseModel):
    """What the resident sees about a volunteer before accepting them."""

    display_name: str
    confirmed_count: int


class RequestOut(BaseModel):
    # no author_id / claimed_by: user ids would let anyone link requests to a person
    id: int
    category: str
    title: str | None
    description: str
    status: str
    latitude: float | None = None
    longitude: float | None = None
    address: str | None = None
    # tells the client whether exact location/address were revealed
    exact_location: bool = False
    is_mine: bool
    is_claimer: bool
    accepted: bool
    claimer: ClaimerInfo | None = None  # only for the author
    created_at: datetime
    closed_at: datetime | None = None


class MessageOut(BaseModel):
    message: str
    status: str | None = None


# ---------------------------------------------------------------------------
# organizations & opportunities
# ---------------------------------------------------------------------------
class OrgRef(BaseModel):
    id: int
    org_name: str


class OrganizationMe(OrgRef):
    verification_status: str
    comment: str | None = None  # latest moderator comment


class OpportunityCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=120)
    description: str | None = None
    category: Category
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    start_time: FutureDatetime
    slots_total: int = Field(ge=1, le=500)


class OpportunityUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(None, min_length=1, max_length=120)
    description: str | None = None
    category: Category | None = None
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    start_time: FutureDatetime | None = None
    slots_total: int | None = Field(None, ge=1, le=500)


class OpportunityOut(BaseModel):
    id: int
    organization: OrgRef
    title: str
    description: str | None
    category: str
    latitude: float
    longitude: float
    start_time: datetime
    slots_total: int
    slots_taken: int
    status: str
    is_signed_up: bool
    is_owner: bool


class VolunteerRef(BaseModel):
    id: int
    display_name: str


class SignupOut(BaseModel):
    id: int
    volunteer: VolunteerRef
    signed_up_at: datetime
    attended: bool | None


class OpportunityBrief(BaseModel):
    id: int
    title: str
    start_time: datetime
    status: str
    organization: OrgRef


class MySignupOut(BaseModel):
    id: int
    opportunity: OpportunityBrief
    signed_up_at: datetime
    attended: bool | None


class AttendanceUpdate(BaseModel):
    attended: bool


# ---------------------------------------------------------------------------
# reports & moderation
# ---------------------------------------------------------------------------
TargetType = Literal["request", "opportunity", "user"]


class ReportCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    target_type: TargetType
    target_id: int
    reason: str = Field(min_length=3, max_length=500)


class ReportCreated(BaseModel):
    id: int
    status: str


class ReportOut(BaseModel):
    id: int
    target_type: str
    target_id: int
    reason: str
    status: str
    created_at: datetime
    reporter: VolunteerRef
    open_reports_on_target: int


class ReportDetail(ReportOut):
    # serialized request / opportunity / user; for a request with an open
    # report this includes the exact address (and the access is logged)
    target: dict | None


class ReportDecision(BaseModel):
    decision: Literal["dismiss", "hide", "block"]


class OrgDecision(BaseModel):
    decision: Literal["approved", "rejected"]
    comment: str | None = Field(None, max_length=500)


class OrganizationAdmin(BaseModel):
    id: int
    org_name: str
    verification_status: str
    created_at: datetime
    user: UserOut


class UserAdmin(UserOut):
    is_blocked: bool
    created_at: datetime


class UserUpdate(BaseModel):
    is_blocked: bool | None = None
    is_moderator: bool | None = None


class AccessLogEntry(BaseModel):
    request_id: int
    user: VolunteerRef
    via: str
    accessed_at: datetime


# ---------------------------------------------------------------------------
# statistics
# ---------------------------------------------------------------------------
class OrgStats(BaseModel):
    opportunities_total: int
    opportunities_open: int
    signups_total: int
    attended_total: int
    past_opportunities: int


class PlatformStats(BaseModel):
    requests_by_status: dict[str, int]
    requests_by_category: dict[str, int]
    users_total: int
    active_users_30d: int
    pending_reports: int
    pending_organizations: int
