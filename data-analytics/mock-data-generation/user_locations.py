"""Generates the user_locations table.
user_locations.user_id -> users.user_id directly (unlike
volunteer_locations, which goes through volunteer_details). Not every user
has opted into location tracking, so this covers a configurable subset of
all users rather than every row in users.csv."""

from typing import Any, Dict, List

from utils import ewkt_point, format_ts, jitter_coord, random_datetime_after, unique_sample, weighted_bool


def generate_user_locations(
    user_contexts: List[Dict[str, Any]], coverage_ratio: float = 0.85
) -> List[Dict[str, Any]]:
    eligible = [ctx for ctx in user_contexts if ctx["has_city"]]
    sample_size = max(1, int(round(len(eligible) * coverage_ratio)))
    selected = unique_sample(eligible, sample_size)

    rows: List[Dict[str, Any]] = []
    for ctx in selected:
        has_prev = weighted_bool(0.6)
        curr_lat, curr_lon = jitter_coord(ctx["lat"], ctx["lon"], max_delta=0.03)
        prev_loc = ""
        if has_prev:
            prev_lat, prev_lon = jitter_coord(ctx["lat"], ctx["lon"], max_delta=0.03)
            prev_loc = ewkt_point(prev_lat, prev_lon)

        last_updated_at = random_datetime_after(ctx["base_date"], max_days=60)

        rows.append({
            "user_id": ctx["user_id"],
            "prev_loc": prev_loc,
            "curr_loc": ewkt_point(curr_lat, curr_lon),
            "last_updated_at": format_ts(last_updated_at),
        })

    return rows
