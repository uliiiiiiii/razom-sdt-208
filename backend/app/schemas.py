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


class RequestMapItem(BaseModel):
    """Public map marker — approximate location only, no address."""

    id: int
    category: str
    title: str | None
    status: str
    latitude: float
    longitude: float
    distance_m: float | None = None


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
