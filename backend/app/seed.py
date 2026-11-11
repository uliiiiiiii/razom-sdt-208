"""Seed script: creates the first moderator (cannot self-register).

Usage:
    python -m app.seed
or  python -m app.seed --email admin@razom.local --password secret --name Admin
"""
from __future__ import annotations

import argparse
import sys

from sqlalchemy import select

from .database import SessionLocal
from .models import User
from .security import hash_password


def seed_moderator(email: str, password: str, name: str) -> None:
    db = SessionLocal()
    try:
        existing = db.scalar(select(User).where(User.email == email))
        if existing:
            existing.is_moderator = True
            db.commit()
            print(f"Moderator role granted to existing user {email} (id={existing.id})")
            return
        user = User(
            email=email,
            password_hash=hash_password(password),
            display_name=name,
            is_moderator=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        print(f"Moderator created: {email} (id={user.id})")
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the first Razom moderator")
    parser.add_argument("--email", default="admin@razom.local")
    parser.add_argument("--password", default="admin123")
    parser.add_argument("--name", default="Admin")
    args = parser.parse_args()
    seed_moderator(args.email.lower(), args.password, args.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
