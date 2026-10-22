"""
Size & Contribution Analytics API  (Issue #376)
Organization Analytics dashboard -- Saayam for All

Two charts:
    1. organizations_by_size          -> flat [{"size": <enum>, "count": <int>}, ...]
    2. collaborator_vs_contributor    -> exactly 2 rows (Collaborator / Contributor)

Response shape (see STEP 1 of the spec):
    * No custom date params  -> 5 keys: 7D / 30D / 1Y / All / Custom (Custom empty)
    * Any custom date pair    -> 1 key : Custom (only the supplied charts populated)

Data access:
    * USE_MOCK_DATA=true -> load CSVs with pandas from MOCK_DATA_DIR  (no DB)
    * otherwise          -> read Postgres with psycopg2 (optional import)
All aggregation runs in pandas so the mock and real paths share one code path.

No AWS Parameter Store, no hardcoded credentials -- everything via env vars.
"""

import json
import os
import re
from datetime import datetime, timedelta

import pandas as pd

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:  # real DB path is optional -- mock path needs none of this
    psycopg2 = None
    RealDictCursor = None


SCHEMA_NAME = os.environ.get("DB_SCHEMA", "virginia_dev_saayam_rdbms")

# Preferred display order for known size enums; unknown values sort after, A-Z.
SIZE_ORDER = {"small": 0, "medium": 1, "large": 2}

# Candidate file names -- the shared repo ships state.csv / country.csv while the
# ticket refers to states.csv / countries.csv, so we accept either.
ORG_FILES = ["organizations.csv"]
STATE_FILES = ["states.csv", "state.csv"]
COUNTRY_FILES = ["countries.csv", "country.csv"]


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def build_response(status_code, body):
    # body is JSON-serialized for AWS Lambda proxy / API Gateway integration.
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body),
    }


class InvalidRequest(ValueError):
    """Raised for malformed input so the handler can return a 400."""


def parse_event_body(event):
    if not event:
        return {}
    body = event.get("body")
    if body is None:
        # direct invocation: the event itself is the payload
        return {k: v for k, v in event.items() if k != "body"} or event
    if isinstance(body, str):
        if body.strip() == "":
            return {}
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            raise InvalidRequest("Request body is not valid JSON")
        if not isinstance(parsed, dict):
            raise InvalidRequest("Request body must be a JSON object")
        return parsed
    if isinstance(body, dict):
        return body
    raise InvalidRequest("Request body must be a JSON object")


def empty_metrics():
    return {"organizations_by_size": [], "collaborator_vs_contributor": []}


def _norm(value):
    """Lowercase + strip non-alphanumerics so 'Non-Profit' == 'non_profit'."""
    return "".join(ch for ch in str(value).lower() if ch.isalnum())


def _to_bool(series):
    return series.astype(str).str.strip().str.upper().isin(["TRUE", "T", "1", "YES", "Y"])


def _parse_date(raw, field):
    """Strictly parse a user-supplied YYYY-MM-DD date; raise on anything else."""
    if not isinstance(raw, str):
        raise InvalidRequest(f"'{field}' must be a 'YYYY-MM-DD' string, got {raw!r}")
    text = raw.strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        raise InvalidRequest(f"'{field}' must be in 'YYYY-MM-DD' format, got {raw!r}")
    try:
        return datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        raise InvalidRequest(f"'{field}' is not a valid calendar date: {raw!r}")


def _validate_pair(start, end, start_field, end_field):
    """Return (start_dt, end_dt) or raise ValueError. (None, None) if neither set."""
    if bool(start) != bool(end):
        missing = end_field if start else start_field
        raise InvalidRequest(f"'{missing}' is required when the other half of the date range is supplied")
    if not start and not end:
        return None, None
    start_dt = _parse_date(start, start_field)
    end_dt = _parse_date(end, end_field)
    if start_dt > end_dt:
        raise InvalidRequest(f"'{start_field}' ({start}) cannot be after '{end_field}' ({end})")
    # make the end date inclusive of the whole day
    end_dt = datetime(end_dt.year, end_dt.month, end_dt.day) + timedelta(days=1) - timedelta(seconds=1)
    start_dt = datetime(start_dt.year, start_dt.month, start_dt.day)
    return start_dt, end_dt


# --------------------------------------------------------------------------- #
# Data loading  (mock CSV  ||  real Postgres) -> unified pandas DataFrame
# --------------------------------------------------------------------------- #
def _use_mock():
    return os.environ.get("USE_MOCK_DATA", "").strip().lower() in ("true", "1", "yes")


def _find_file(mock_dir, candidates):
    for name in candidates:
        path = os.path.join(mock_dir, name)
        if os.path.exists(path):
            return path
    return None


def _load_mock_frames():
    mock_dir = os.environ.get("MOCK_DATA_DIR")
    if not mock_dir:
        raise ValueError("MOCK_DATA_DIR is not set but USE_MOCK_DATA is enabled")

    org_path = _find_file(mock_dir, ORG_FILES)
    state_path = _find_file(mock_dir, STATE_FILES)
    country_path = _find_file(mock_dir, COUNTRY_FILES)
    if not org_path:
        raise ValueError(f"organizations csv not found in {mock_dir}")

    orgs = pd.read_csv(org_path, dtype=str, keep_default_na=False)
    states = pd.read_csv(state_path, dtype=str, keep_default_na=False) if state_path else pd.DataFrame()
    countries = pd.read_csv(country_path, dtype=str, keep_default_na=False) if country_path else pd.DataFrame()
    return orgs, states, countries


def _load_db_frames():
    if psycopg2 is None:
        raise ValueError("psycopg2 is not installed -- cannot use the real database path")
    from psycopg2 import sql  # local import keeps the mock path psycopg2-free

    conn = psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=os.environ.get("DB_PORT", "5432"),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        sslmode=os.environ.get("DB_SSLMODE", "require"),
    )
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        frames = {}
        for key, table in (
            ("orgs", "organizations"),
            ("states", "state"),
            ("countries", "country"),
        ):
            # Quote schema/table as identifiers to avoid SQL injection via env config.
            query = sql.SQL("SELECT * FROM {}.{};").format(
                sql.Identifier(SCHEMA_NAME), sql.Identifier(table)
            )
            cursor.execute(query)
            # Do NOT astype(str): keep native types so NULL stays NaN (not "None").
            frames[key] = pd.DataFrame([dict(r) for r in cursor.fetchall()])
        cursor.close()
        return frames["orgs"], frames["states"], frames["countries"]
    finally:
        conn.close()


def load_organizations():
    """Load orgs joined to country info; created_at parsed; returns a DataFrame."""
    orgs, states, countries = _load_mock_frames() if _use_mock() else _load_db_frames()

    if orgs.empty:
        return orgs.assign(created_at=pd.NaT) if "created_at" not in orgs else orgs

    # join state -> country so the country filter can match code or name
    if not states.empty and "state_id" in orgs.columns and "state_id" in states.columns:
        orgs = orgs.merge(states[["state_id", "country_id"]], on="state_id", how="left")
    if not countries.empty and "country_id" in orgs.columns:
        country_cols = [c for c in ["country_id", "country_code", "country_name"] if c in countries.columns]
        orgs = orgs.merge(countries[country_cols], on="country_id", how="left")

    # Parse created_at and normalize to naive UTC so tz-aware values (ISO 'Z',
    # Postgres timestamptz) and naive values compare without raising.
    if "created_at" in orgs.columns:
        parsed = pd.to_datetime(orgs["created_at"], errors="coerce", utc=True)
        orgs["created_at"] = parsed.dt.tz_convert(None)
    else:
        orgs["created_at"] = pd.NaT
    return orgs


# --------------------------------------------------------------------------- #
# Filters
# --------------------------------------------------------------------------- #
def apply_filters(df, country, organization_type):
    """country + organization_type apply to BOTH charts in every response shape."""
    if df.empty:
        return df
    out = df

    if country and _norm(country) not in ("", "all"):
        target = _norm(country)
        code = out["country_code"].map(_norm) if "country_code" in out.columns else ""
        name = out["country_name"].map(_norm) if "country_name" in out.columns else ""
        mask = pd.Series(False, index=out.index)
        if "country_code" in out.columns:
            mask = mask | (code == target)
        if "country_name" in out.columns:
            mask = mask | (name == target)
        out = out[mask]

    if organization_type and _norm(organization_type) not in ("", "all"):
        target = _norm(organization_type)
        if "org_type" in out.columns:
            out = out[out["org_type"].map(_norm) == target]
        else:
            out = out.iloc[0:0]
    return out


def filter_window(df, start_dt, end_dt):
    """Window-scoped snapshot: rows with created_at inside [start, end]."""
    if df.empty or "created_at" not in df.columns:
        return df
    scoped = df[df["created_at"].notna()]
    return scoped[(scoped["created_at"] >= start_dt) & (scoped["created_at"] <= end_dt)]


# --------------------------------------------------------------------------- #
# Chart builders
# --------------------------------------------------------------------------- #
def get_organizations_by_size(df):
    """Flat array, one row per org_size that appears (no zero-filling)."""
    if df.empty or "org_size" not in df.columns:
        return []
    sizes = df["org_size"].astype(str).str.strip()
    sizes = sizes[sizes != ""]
    if sizes.empty:
        return []
    counts = sizes.value_counts()
    rows = [{"size": size, "count": int(count)} for size, count in counts.items()]
    rows.sort(key=lambda r: (SIZE_ORDER.get(r["size"].lower(), len(SIZE_ORDER)), r["size"].lower()))
    return rows


def get_collaborator_vs_contributor(df):
    """Empty window -> [] (per spec). Otherwise exactly 2 independent-count rows."""
    total = int(len(df))
    if total == 0:
        return []

    collaborator_count = int(_to_bool(df["is_collaborator"]).sum()) if "is_collaborator" in df.columns else 0

    # Degrade gracefully when the column is absent.
    contributor_count = int(_to_bool(df["is_contributor"]).sum()) if "is_contributor" in df.columns else 0

    def pct(n):
        return round(n / total * 100, 1)

    return [
        {"type": "Collaborator", "count": collaborator_count, "percentage": pct(collaborator_count)},
        {"type": "Contributor", "count": contributor_count, "percentage": pct(contributor_count)},
    ]


def compute_metrics(df):
    return {
        "organizations_by_size": get_organizations_by_size(df),
        "collaborator_vs_contributor": get_collaborator_vs_contributor(df),
    }


# --------------------------------------------------------------------------- #
# Handler
# --------------------------------------------------------------------------- #
def lambda_handler(event, context):
    try:
        body = parse_event_body(event)
    except InvalidRequest as e:
        return build_response(400, {"error": str(e)})

    country = body.get("country", "ALL")
    organization_type = body.get("organization_type", "ALL")

    # Validate the two independent custom date pairs up front.
    try:
        size_start, size_end = _validate_pair(
            body.get("size_start_date"), body.get("size_end_date"),
            "size_start_date", "size_end_date",
        )
        contrib_start, contrib_end = _validate_pair(
            body.get("contribution_start_date"), body.get("contribution_end_date"),
            "contribution_start_date", "contribution_end_date",
        )
    except ValueError as e:
        return build_response(400, {"error": str(e)})

    # Load + apply the shared country / org-type filters once.
    try:
        orgs = load_organizations()
    except Exception as e:  # missing files, bad config, etc.
        return build_response(500, {"error": f"Failed to load data: {e}"})

    base = apply_filters(orgs, country, organization_type)

    has_size = size_start is not None
    has_contrib = contrib_start is not None

    try:
        # ------- Custom-only response (1 top-level key) -------
        # Both pairs are evaluated INDEPENDENTLY -- we never silently drop the
        # second pair the way the reference volunteer analytics does.
        if has_size or has_contrib:
            custom = empty_metrics()
            if has_size:
                size_df = filter_window(base, size_start, size_end)
                custom["organizations_by_size"] = get_organizations_by_size(size_df)
            if has_contrib:
                contrib_df = filter_window(base, contrib_start, contrib_end)
                custom["collaborator_vs_contributor"] = get_collaborator_vs_contributor(contrib_df)
            return build_response(200, {"Custom": custom})

        # ------- No custom params: 4 fixed buckets + empty Custom (5 keys) -------
        # created_at is normalized to naive UTC, so compare against UTC now.
        now = datetime.utcnow()
        response_body = {
            "7D": compute_metrics(filter_window(base, now - timedelta(days=7), now)),
            "30D": compute_metrics(filter_window(base, now - timedelta(days=30), now)),
            "1Y": compute_metrics(filter_window(base, now - timedelta(days=365), now)),
            "All": compute_metrics(base),
            "Custom": empty_metrics(),
        }
        return build_response(200, response_body)
    except Exception as e:  # never surface a raw Lambda crash to the caller
        return build_response(500, {"error": f"Failed to compute analytics: {e}"})


# --------------------------------------------------------------------------- #
# Local test harness
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    os.environ.setdefault("USE_MOCK_DATA", "true")
    os.environ.setdefault(
        "MOCK_DATA_DIR",
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "sql")),
    )

    samples = [
        ("1. No body {}", {}),
        ("2. country filter only", {"body": {"country": "USA"}}),
        ("3. organization_type filter only", {"body": {"organization_type": "non_profit"}}),
        ("4. size dates only", {"body": {"size_start_date": "2025-06-01", "size_end_date": "2026-06-30"}}),
        ("5. contribution dates only", {"body": {"contribution_start_date": "2025-01-01", "contribution_end_date": "2025-12-31"}}),
        ("6. both date pairs", {"body": {
            "country": "USA", "organization_type": "non_profit",
            "size_start_date": "2025-06-01", "size_end_date": "2026-06-30",
            "contribution_start_date": "2025-01-01", "contribution_end_date": "2025-12-31",
        }}),
        ("7. malformed (missing half of a pair)", {"body": {"size_start_date": "2025-06-01"}}),
        ("8. malformed (bad date format)", {"body": {"size_start_date": "06/01/2025", "size_end_date": "2025-06-30"}}),
        ("9. malformed (invalid JSON body)", {"body": "{not-json"}),
    ]

    for title, event in samples:
        print("=" * 78)
        print(title)
        print("-" * 78)
        result = lambda_handler(event, None)
        # body is a JSON string (Lambda proxy format); parse for readable printing.
        print("statusCode:", result["statusCode"])
        print(json.dumps(json.loads(result["body"]), indent=2))
    print("=" * 78)


# ============================================================================
# LOCAL TEST OUTPUT  (USE_MOCK_DATA=true, generated mock CSVs -- NOT committed)
# Captured by running:  python3 size_contribution_analytics.py
# Automated tests: `pytest -q test_size_contribution_analytics.py`  -> 28 passed
# ============================================================================
#
# ==============================================================================
# 1. No body {}
# ------------------------------------------------------------------------------
# statusCode: 200
# {
#   "7D": {
#     "organizations_by_size": [
#       {
#         "size": "Small",
#         "count": 2
#       },
#       {
#         "size": "Medium",
#         "count": 1
#       },
#       {
#         "size": "Large",
#         "count": 1
#       }
#     ],
#     "collaborator_vs_contributor": [
#       {
#         "type": "Collaborator",
#         "count": 3,
#         "percentage": 75.0
#       },
#       {
#         "type": "Contributor",
#         "count": 3,
#         "percentage": 75.0
#       }
#     ]
#   },
#   "30D": {
#     "organizations_by_size": [
#       {
#         "size": "Small",
#         "count": 4
#       },
#       {
#         "size": "Medium",
#         "count": 2
#       },
#       {
#         "size": "Large",
#         "count": 3
#       }
#     ],
#     "collaborator_vs_contributor": [
#       {
#         "type": "Collaborator",
#         "count": 5,
#         "percentage": 55.6
#       },
#       {
#         "type": "Contributor",
#         "count": 7,
#         "percentage": 77.8
#       }
#     ]
#   },
#   "1Y": {
#     "organizations_by_size": [
#       {
#         "size": "Small",
#         "count": 7
#       },
#       {
#         "size": "Medium",
#         "count": 5
#       },
#       {
#         "size": "Large",
#         "count": 5
#       }
#     ],
#     "collaborator_vs_contributor": [
#       {
#         "type": "Collaborator",
#         "count": 11,
#         "percentage": 64.7
#       },
#       {
#         "type": "Contributor",
#         "count": 11,
#         "percentage": 64.7
#       }
#     ]
#   },
#   "All": {
#     "organizations_by_size": [
#       {
#         "size": "Small",
#         "count": 8
#       },
#       {
#         "size": "Medium",
#         "count": 6
#       },
#       {
#         "size": "Large",
#         "count": 6
#       }
#     ],
#     "collaborator_vs_contributor": [
#       {
#         "type": "Collaborator",
#         "count": 12,
#         "percentage": 60.0
#       },
#       {
#         "type": "Contributor",
#         "count": 13,
#         "percentage": 65.0
#       }
#     ]
#   },
#   "Custom": {
#     "organizations_by_size": [],
#     "collaborator_vs_contributor": []
#   }
# }
# ==============================================================================
# 2. country filter only
# ------------------------------------------------------------------------------
# statusCode: 200
# {
#   "7D": {
#     "organizations_by_size": [
#       {
#         "size": "Small",
#         "count": 1
#       },
#       {
#         "size": "Medium",
#         "count": 1
#       },
#       {
#         "size": "Large",
#         "count": 1
#       }
#     ],
#     "collaborator_vs_contributor": [
#       {
#         "type": "Collaborator",
#         "count": 2,
#         "percentage": 66.7
#       },
#       {
#         "type": "Contributor",
#         "count": 2,
#         "percentage": 66.7
#       }
#     ]
#   },
#   "30D": {
#     "organizations_by_size": [
#       {
#         "size": "Small",
#         "count": 3
#       },
#       {
#         "size": "Medium",
#         "count": 2
#       },
#       {
#         "size": "Large",
#         "count": 2
#       }
#     ],
#     "collaborator_vs_contributor": [
#       {
#         "type": "Collaborator",
#         "count": 4,
#         "percentage": 57.1
#       },
#       {
#         "type": "Contributor",
#         "count": 5,
#         "percentage": 71.4
#       }
#     ]
#   },
#   "1Y": {
#     "organizations_by_size": [
#       {
#         "size": "Small",
#         "count": 6
#       },
#       {
#         "size": "Medium",
#         "count": 4
#       },
#       {
#         "size": "Large",
#         "count": 3
#       }
#     ],
#     "collaborator_vs_contributor": [
#       {
#         "type": "Collaborator",
#         "count": 8,
#         "percentage": 61.5
#       },
#       {
#         "type": "Contributor",
#         "count": 8,
#         "percentage": 61.5
#       }
#     ]
#   },
#   "All": {
#     "organizations_by_size": [
#       {
#         "size": "Small",
#         "count": 6
#       },
#       {
#         "size": "Medium",
#         "count": 4
#       },
#       {
#         "size": "Large",
#         "count": 4
#       }
#     ],
#     "collaborator_vs_contributor": [
#       {
#         "type": "Collaborator",
#         "count": 8,
#         "percentage": 57.1
#       },
#       {
#         "type": "Contributor",
#         "count": 9,
#         "percentage": 64.3
#       }
#     ]
#   },
#   "Custom": {
#     "organizations_by_size": [],
#     "collaborator_vs_contributor": []
#   }
# }
# ==============================================================================
# 3. organization_type filter only
# ------------------------------------------------------------------------------
# statusCode: 200
# {
#   "7D": {
#     "organizations_by_size": [
#       {
#         "size": "Small",
#         "count": 2
#       },
#       {
#         "size": "Medium",
#         "count": 1
#       }
#     ],
#     "collaborator_vs_contributor": [
#       {
#         "type": "Collaborator",
#         "count": 2,
#         "percentage": 66.7
#       },
#       {
#         "type": "Contributor",
#         "count": 3,
#         "percentage": 100.0
#       }
#     ]
#   },
#   "30D": {
#     "organizations_by_size": [
#       {
#         "size": "Small",
#         "count": 4
#       },
#       {
#         "size": "Medium",
#         "count": 1
#       },
#       {
#         "size": "Large",
#         "count": 1
#       }
#     ],
#     "collaborator_vs_contributor": [
#       {
#         "type": "Collaborator",
#         "count": 4,
#         "percentage": 66.7
#       },
#       {
#         "type": "Contributor",
#         "count": 6,
#         "percentage": 100.0
#       }
#     ]
#   },
#   "1Y": {
#     "organizations_by_size": [
#       {
#         "size": "Small",
#         "count": 6
#       },
#       {
#         "size": "Medium",
#         "count": 3
#       },
#       {
#         "size": "Large",
#         "count": 3
#       }
#     ],
#     "collaborator_vs_contributor": [
#       {
#         "type": "Collaborator",
#         "count": 8,
#         "percentage": 66.7
#       },
#       {
#         "type": "Contributor",
#         "count": 10,
#         "percentage": 83.3
#       }
#     ]
#   },
#   "All": {
#     "organizations_by_size": [
#       {
#         "size": "Small",
#         "count": 7
#       },
#       {
#         "size": "Medium",
#         "count": 3
#       },
#       {
#         "size": "Large",
#         "count": 3
#       }
#     ],
#     "collaborator_vs_contributor": [
#       {
#         "type": "Collaborator",
#         "count": 9,
#         "percentage": 69.2
#       },
#       {
#         "type": "Contributor",
#         "count": 11,
#         "percentage": 84.6
#       }
#     ]
#   },
#   "Custom": {
#     "organizations_by_size": [],
#     "collaborator_vs_contributor": []
#   }
# }
# ==============================================================================
# 4. size dates only
# ------------------------------------------------------------------------------
# statusCode: 200
# {
#   "Custom": {
#     "organizations_by_size": [
#       {
#         "size": "Small",
#         "count": 3
#       },
#       {
#         "size": "Medium",
#         "count": 2
#       },
#       {
#         "size": "Large",
#         "count": 2
#       }
#     ],
#     "collaborator_vs_contributor": []
#   }
# }
# ==============================================================================
# 5. contribution dates only
# ------------------------------------------------------------------------------
# statusCode: 200
# {
#   "Custom": {
#     "organizations_by_size": [],
#     "collaborator_vs_contributor": [
#       {
#         "type": "Collaborator",
#         "count": 2,
#         "percentage": 50.0
#       },
#       {
#         "type": "Contributor",
#         "count": 2,
#         "percentage": 50.0
#       }
#     ]
#   }
# }
# ==============================================================================
# 6. both date pairs
# ------------------------------------------------------------------------------
# statusCode: 200
# {
#   "Custom": {
#     "organizations_by_size": [
#       {
#         "size": "Small",
#         "count": 2
#       },
#       {
#         "size": "Large",
#         "count": 1
#       }
#     ],
#     "collaborator_vs_contributor": [
#       {
#         "type": "Collaborator",
#         "count": 1,
#         "percentage": 50.0
#       },
#       {
#         "type": "Contributor",
#         "count": 1,
#         "percentage": 50.0
#       }
#     ]
#   }
# }
# ==============================================================================
# 7. malformed (missing half of a pair)
# ------------------------------------------------------------------------------
# statusCode: 400
# {
#   "error": "'size_end_date' is required when the other half of the date range is supplied"
# }
# ==============================================================================
# 8. malformed (bad date format)
# ------------------------------------------------------------------------------
# statusCode: 400
# {
#   "error": "'size_start_date' must be in 'YYYY-MM-DD' format, got '06/01/2025'"
# }
# ==============================================================================
# 9. malformed (invalid JSON body)
# ------------------------------------------------------------------------------
# statusCode: 400
# {
#   "error": "Request body is not valid JSON"
# }
# ==============================================================================
