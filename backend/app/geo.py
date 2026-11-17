"""Geospatial helpers built on PostGIS."""
from __future__ import annotations

from geoalchemy2 import Geometry
from geoalchemy2.elements import WKTElement
from sqlalchemy import cast, func


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


def point_wkt(latitude: float, longitude: float) -> WKTElement:
    return WKTElement(f"POINT({longitude} {latitude})", srid=4326)


def lat_expr(col):
    # ST_Y/ST_X require geometry, not geography -> cast.
    return func.ST_Y(cast(col, Geometry(srid=4326)))


def lng_expr(col):
    return func.ST_X(cast(col, Geometry(srid=4326)))
