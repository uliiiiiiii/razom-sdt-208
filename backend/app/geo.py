"""Geospatial helpers built on PostGIS."""
from __future__ import annotations

import math


def round_location(latitude: float, longitude: float, radius_m: int = 300) -> tuple[float, float]:
    """Snap a point to a coarse grid so the public map cannot reveal an exact address.

    A ~300m grid is implemented by rounding to a fixed number of decimal places:
    1 degree of latitude ~= 111_000 m, so ~0.003 degrees ~= 333m.
    """
    step = max(radius_m, 1) / 111_000.0
    return (
        round(latitude / step) * step,
        round(longitude / step) * step,
    )
