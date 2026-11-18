"""Geospatial helpers built on PostGIS."""
from __future__ import annotations

import math

from geoalchemy2 import Geometry
from geoalchemy2.elements import WKTElement
from sqlalchemy import cast, func


def round_location(latitude: float, longitude: float, radius_m: int = 300) -> tuple[float, float]:
    """Snap a point to a coarse grid so the public map cannot reveal an exact address.

    1 degree of latitude ~= 111 km everywhere, but a degree of longitude
    shrinks with cos(latitude) (~71 km in Kyiv), so the longitude step is
    widened to keep cells ~radius_m wide in both directions.
    """
    step_lat = max(radius_m, 1) / 111_000.0
    snapped_lat = round(latitude / step_lat) * step_lat
    # derive the step from the SNAPPED latitude: using the exact one would make
    # the output longitude leak where in the cell the point is
    step_lng = step_lat / max(math.cos(math.radians(snapped_lat)), 0.01)
    return snapped_lat, round(longitude / step_lng) * step_lng


def point_wkt(latitude: float, longitude: float) -> WKTElement:
    return WKTElement(f"POINT({longitude} {latitude})", srid=4326)


def lat_expr(col):
    # ST_Y/ST_X require geometry, not geography -> cast.
    return func.ST_Y(cast(col, Geometry(srid=4326)))


def lng_expr(col):
    return func.ST_X(cast(col, Geometry(srid=4326)))
