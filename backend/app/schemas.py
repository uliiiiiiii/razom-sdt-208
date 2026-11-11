"""Pydantic request/response schemas."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    display_name: str = Field(min_length=1, max_length=100)
    phone: str | None = None
    is_resident: bool = False
    is_volunteer: bool = False
    is_organization: bool = False


class UserLogin(BaseModel):
    email: EmailStr
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
    category: str
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


class RequestOut(BaseModel):
    id: int
    category: str
    title: str | None
    description: str
    status: str
    author_id: int
    latitude: float | None = None
    longitude: float | None = None
    address: str | None = None
    claimed_by: int | None = None
    claimed_at: datetime | None = None
    created_at: datetime
    # tells the client whether exact location/address were revealed
    exact_location: bool = False


class MessageOut(BaseModel):
    message: str
    status: str | None = None
