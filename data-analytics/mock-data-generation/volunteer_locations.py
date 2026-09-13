"""Generates the volunteer_locations table.
volunteer_locations.user_id -> volunteer_details.user_id (NOT users.user_id
directly - see the FK note in the issue). curr_loc/prev_loc are geography
points stored as EWKT text, plausibly located within the volunteer's own
state/city rather than random global coordinates."""

from typing import Any, Dict, List

from utils import ewkt_point, format_ts, jitter_coord, random_datetime_after, weighted_bool


def generate_volunteer_locations(volunteer_contexts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []

    for ctx in volunteer_contexts:
        if not ctx["has_city"]:
            continue  # no coordinates to place a point near

        has_prev = weighted_bool(0.7)
        curr_lat, curr_lon = jitter_coord(ctx["lat"], ctx["lon"], max_delta=0.03)
        prev_loc = ""
        if has_prev:
            prev_lat, prev_lon = jitter_coord(ctx["lat"], ctx["lon"], max_delta=0.03)
            prev_loc = ewkt_point(prev_lat, prev_lon)

        last_updated_at = random_datetime_after(ctx["vol_created_at"], max_days=45)

        rows.append({
            "user_id": ctx["user_id"],
            "prev_loc": prev_loc,
            "curr_loc": ewkt_point(curr_lat, curr_lon),
            "last_updated_at": format_ts(last_updated_at),
        })

    return rows
