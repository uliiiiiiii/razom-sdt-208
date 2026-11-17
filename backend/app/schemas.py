"""Pydantic request/response schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field

# lowercased so A@x.com and a@x.com are the same account
Email = Annotated[EmailStr, AfterValidator(str.lower)]


class UserRegister(BaseModel):
    email: Email
    password: str = Field(min_length=6)
    display_name: str = Field(min_length=1, max_length=100)
    is_resident: bool = False
    is_volunteer: bool = False
    is_organization: bool = False


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

    # must match the CHECK constraint on help_requests.category in db/init.sql
    category: Literal["charging", "groceries", "medicine", "water", "transport", "pets", "other"]
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
