"""Auth router: register and login (JWT)."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import Organization, User
from ..ratelimit import LOGIN_LIMIT, REGISTER_LIMIT, limiter
from ..schemas import TokenResponse, UserLogin, UserOut, UserRegister
from ..security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
@limiter.limit(REGISTER_LIMIT)
def register(request: Request, payload: UserRegister, db: Session = Depends(get_db)) -> User:
    if not (payload.is_resident or payload.is_volunteer or payload.is_organization):
        raise HTTPException(
            status_code=400, detail="Choose at least one role: resident, volunteer or organization"
        )
    # moderators cannot self-register (per requirements)
    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name,
        is_resident=payload.is_resident,
        is_volunteer=payload.is_volunteer,
        is_organization=payload.is_organization,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:  # the unique email index; also catches two sign-ups racing
        db.rollback()
        raise HTTPException(status_code=409, detail="Email already registered") from None
    if payload.is_organization:
        # publishing is blocked until a moderator approves this profile
        db.add(Organization(user_id=user.id, org_name=payload.org_name))
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
@limiter.limit(LOGIN_LIMIT)
def login(request: Request, payload: UserLogin, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.scalar(select(User).where(User.email == payload.email))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if user.is_blocked:
        raise HTTPException(status_code=403, detail="Account is blocked")
    token = create_access_token(user.id, {"roles": user.role_list()})
    return TokenResponse(
        access_token=token,
        user_id=user.id,
        display_name=user.display_name,
        roles=user.role_list(),
    )


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user
