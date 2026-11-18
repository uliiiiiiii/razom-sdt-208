"""FastAPI dependencies: DB session and current user from JWT."""
from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .models import Organization, User
from .security import decode_access_token

# Swagger shows an "Authorize" box where the token from /api/auth/login is pasted
bearer_scheme = HTTPBearer(auto_error=False)

CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid or missing authentication token",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise CREDENTIALS_ERROR
    try:
        payload = decode_access_token(credentials.credentials)
        user_id = int(payload["sub"])
    except Exception as exc:  # noqa: BLE001
        raise CREDENTIALS_ERROR from exc
    user = db.get(User, user_id)
    if not user:
        raise CREDENTIALS_ERROR
    if user.is_blocked:
        # a blocked user's existing token is rejected; distinct message for the UI
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is blocked",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_roles(*roles: str):
    """Dependency factory: ensure the current user has at least one of the roles."""

    def _checker(user: User = Depends(get_current_user)) -> User:
        user_roles = set(user.role_list())
        if not user_roles.intersection(roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of roles: {', '.join(roles)}",
            )
        return user

    return _checker


def get_my_organization(
    user: User = Depends(require_roles("organization")),
    db: Session = Depends(get_db),
) -> Organization:
    org = db.scalar(select(Organization).where(Organization.user_id == user.id))
    if org is None:
        raise HTTPException(status_code=404, detail="Organization profile not found")
    return org


def require_verified_org(org: Organization = Depends(get_my_organization)) -> Organization:
    """Organizations can publish only after a moderator approved them (FR 4)."""
    if org.verification_status != "approved":
        raise HTTPException(status_code=403, detail="Organization is not verified yet")
    return org
