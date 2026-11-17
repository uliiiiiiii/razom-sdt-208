"""Data retention: forget exact addresses of requests closed long ago.

Runs at startup; can also be run by hand:  python -m app.retention
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

RETENTION_DAYS = 30


def purge_closed_addresses(db: Session, older_than_days: int = RETENTION_DAYS) -> int:
    """Drop the address and replace the exact point with the approximate one
    for confirmed/cancelled requests closed more than `older_than_days` ago.
    Returns the number of requests purged."""
    rows = db.execute(
        text(
            """
            UPDATE help_requests
               SET address = NULL, location = approx_location
             WHERE status IN ('confirmed', 'cancelled')
               AND closed_at < now() - make_interval(days => :days)
               AND approx_location IS NOT NULL
               AND (address IS NOT NULL
                    OR NOT ST_Equals(location::geometry, approx_location::geometry))
            RETURNING id
            """
        ),
        {"days": older_than_days},
    ).all()
    db.commit()
    return len(rows)


if __name__ == "__main__":
    from .database import SessionLocal

    with SessionLocal() as session:
        print(f"Purged {purge_closed_addresses(session)} request(s)")
