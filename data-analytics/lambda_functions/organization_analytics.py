"""
Organization Analytics API — Issue #228

Provides two dashboards for the Saayam Organization Dashboard, built against
virginia_dev_saayam_rdbms.organizations (joined with .state / .country for
location breakdowns):

  1. Organization Overview
  2. Organization Performance

DESIGN CHOICE: this implementation uses the issue's *other* suggested option
— two separate Lambda entry points (overview_handler / performance_handler,
mapping to POST /analytics/organizations/overview and
POST /analytics/organizations/performance) rather than one endpoint routed by
a dashboard_type field. It also groups the query logic behind an
OrganizationAnalyticsService class instead of a flat set of module-level
functions, and returns organizations_by_location as a single flat list of
{state, city, count} rows (grouped by the state+city pair) rather than a
{by_state, by_city} split.

LOCAL DEV NOTE (per issue #228 — "test locally using a local PostgreSQL
connection, do not deploy to AWS"): get_db_connection() reads a DATABASE_URL
from the environment (same variable already in data-engineering/.env.example)
rather than pulling credentials from AWS SSM like the production lambdas do.
Swap this for the SSM-based get_db_config() pattern used elsewhere in this
folder (see volunteer_application_analytics.py) before this goes anywhere
near AWS.

SCHEMA GAP: the issue asks for "contributor" vs "non-contributor" org counts
and a "top contributor organizations" list, but
https://github.com/saayam-for-all/database/blob/main/ddl/Tables/ddl_organizations.sql
has no is_contributor (or equivalent) column — only is_collaborator. Every
contributor-related field below is wired up but intentionally returns a
zero/empty value with a comment pointing here. The issue itself later notes
"a new field, is_contributor, has been added to the task. However, this
field is not yet available in the current database" — so this is a known,
acknowledged gap, not a bug. Flag it for your reviewer if it isn't obvious
from the code comments.
"""

import json
import os

import psycopg2
from psycopg2.extras import RealDictCursor

SCHEMA_NAME = "virginia_dev_saayam_rdbms"
ORGANIZATIONS = f"{SCHEMA_NAME}.organizations"
STATE = f"{SCHEMA_NAME}.state"

TOP_N_DEFAULT = 10


# --------------------------------------------------------------------------
# Connection + response helpers
# --------------------------------------------------------------------------

def get_db_connection():
    """
    Local-dev connection: reads DATABASE_URL from the environment
    (see data-engineering/.env.example). For production this should be
    swapped for the boto3/SSM pattern used in volunteer_application_analytics.py
    and kpi_api_analytics.py — not done here per the issue's "local only" note.
    """
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is not set. Copy .env.example to .env and point it at "
            "your local Postgres instance before running this locally."
        )
    return psycopg2.connect(database_url)


def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
        },
        "body": json.dumps(body, default=str),
    }


def parse_event_body(event):
    if not event:
        return {}
    body = event.get("body")
    if body is None:
        return event
    if isinstance(body, str):
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {}
    if isinstance(body, dict):
        return body
    return {}


def _time_filter_clause(time_filter, start_date=None, end_date=None, column="o.created_at"):
    if time_filter == "CUSTOM" and start_date and end_date:
        return f"AND {column} BETWEEN %s AND %s", (start_date, end_date)
    if time_filter == "7D":
        return f"AND {column} >= CURRENT_DATE - INTERVAL '7 days'", ()
    if time_filter == "30D":
        return f"AND {column} >= CURRENT_DATE - INTERVAL '30 days'", ()
    if time_filter == "1Y":
        return f"AND {column} >= CURRENT_DATE - INTERVAL '1 year'", ()
    return "", ()  # "ALL" or unrecognized -> no filter


def _grouping_for(group_by):
    return {
        "daily": ("day", "YYYY-MM-DD"),
        "weekly": ("week", "IYYY-\"W\"IW"),
        "monthly": ("month", "YYYY-MM"),
        "yearly": ("year", "YYYY"),
    }.get(group_by, ("month", "YYYY-MM"))


# --------------------------------------------------------------------------
# Service class — holds a cursor and the shared filter context, exposes one
# public method per dashboard.
# --------------------------------------------------------------------------

class OrganizationAnalyticsService:
    """Encapsulates every query needed for the two organization dashboards.

    Instantiate with an open RealDictCursor and a filters dict (the parsed
    request body). Call get_overview() or get_performance() to run the
    dashboard's queries and get back the response payload.
    """

    def __init__(self, cursor, filters):
        self.cursor = cursor
        self.filters = filters or {}
        self.time_where, self.time_params = _time_filter_clause(
            self.filters.get("time_filter", "30D"),
            self.filters.get("start_date"),
            self.filters.get("end_date"),
        )
        self.common_where, self.common_params = self._build_common_filters()

    def _build_common_filters(self):
        clauses, params = [], []
        f = self.filters
        mapping = {
            "org_type": "o.org_type = %s",
            "org_size": "o.org_size = %s",
            "state_id": "o.state_id = %s",
            "city_name": "o.city_name = %s",
            "org_rating": "o.org_rating = %s",
        }
        for key, clause in mapping.items():
            if f.get(key):
                clauses.append(clause)
                params.append(f[key])
        if f.get("is_collaborator") is not None:
            clauses.append("o.is_collaborator = %s")
            params.append(f["is_collaborator"])
        where_fragment = (" AND " + " AND ".join(clauses)) if clauses else ""
        return where_fragment, params

    def _run(self, query, extra_params=(), fetch="all"):
        self.cursor.execute(query, (*self.time_params, *self.common_params, *extra_params))
        return self.cursor.fetchall() if fetch == "all" else self.cursor.fetchone()

    # ---- Overview dashboard ------------------------------------------------

    def get_overview(self):
        return {
            "summary": self._overview_summary(),
            "organization_activity_trend": self._activity_trend(),
            "organizations_by_type": self._by_column("org_type"),
            "organizations_by_size": self._by_column("org_size"),
            "organizations_by_location": self._by_location(),
            "collaborator_distribution": self._collaborator_distribution(),
            # SCHEMA GAP: no is_contributor column — see module docstring.
            "contributor_distribution": [],
        }

    def _overview_summary(self):
        query = f"""
            SELECT
                COUNT(*) AS total_organizations,
                COUNT(*) FILTER (WHERE o.org_type = 'non_profit') AS non_profit_organizations,
                COUNT(*) FILTER (WHERE o.org_type = 'for_profit') AS for_profit_organizations,
                COUNT(*) FILTER (WHERE o.is_collaborator IS TRUE) AS collaborator_organizations,
                COUNT(*) FILTER (WHERE o.is_collaborator IS NOT TRUE) AS non_collaborator_organizations
            FROM {ORGANIZATIONS} o
            WHERE 1=1 {self.time_where} {self.common_where}
        """
        row = self._run(query, fetch="one") or {}
        return {
            "total_organizations": int(row.get("total_organizations") or 0),
            "non_profit_organizations": int(row.get("non_profit_organizations") or 0),
            "for_profit_organizations": int(row.get("for_profit_organizations") or 0),
            "collaborator_organizations": int(row.get("collaborator_organizations") or 0),
            "non_collaborator_organizations": int(row.get("non_collaborator_organizations") or 0),
            # SCHEMA GAP: no is_contributor column — see module docstring.
            "contributor_organizations": 0,
            "non_contributor_organizations": 0,
        }

    def _activity_trend(self):
        period, date_format = _grouping_for(self.filters.get("group_by", "monthly"))
        query = f"""
            SELECT TO_CHAR(DATE_TRUNC('{period}', o.created_at), '{date_format}') AS period,
                   COUNT(*) AS count
            FROM {ORGANIZATIONS} o
            WHERE o.created_at IS NOT NULL {self.time_where} {self.common_where}
            GROUP BY 1
            ORDER BY 1
        """
        return [{"period": r["period"], "count": int(r["count"])} for r in self._run(query)]

    def _by_column(self, column):
        query = f"""
            SELECT COALESCE(o.{column}::text, 'unknown') AS {column}, COUNT(*) AS count
            FROM {ORGANIZATIONS} o
            WHERE 1=1 {self.time_where} {self.common_where}
            GROUP BY 1
            ORDER BY count DESC
        """
        return [{column: r[column], "count": int(r["count"])} for r in self._run(query)]

    def _by_location(self):
        # Flat list of {state, city, count}, one row per state+city pair —
        # deliberately different shape from a {by_state, by_city} split.
        query = f"""
            SELECT COALESCE(s.state_name, 'Unknown') AS state,
                   COALESCE(o.city_name, 'Unknown') AS city,
                   COUNT(*) AS count
            FROM {ORGANIZATIONS} o
            LEFT JOIN {STATE} s ON o.state_id = s.state_id
            WHERE 1=1 {self.time_where} {self.common_where}
            GROUP BY 1, 2
            ORDER BY count DESC, state, city
        """
        return [{"state": r["state"], "city": r["city"], "count": int(r["count"])} for r in self._run(query)]

    def _collaborator_distribution(self):
        query = f"""
            SELECT o.is_collaborator, COUNT(*) AS count
            FROM {ORGANIZATIONS} o
            WHERE 1=1 {self.time_where} {self.common_where}
            GROUP BY 1
        """
        return [
            {
                "is_collaborator": bool(r["is_collaborator"]) if r["is_collaborator"] is not None else False,
                "count": int(r["count"]),
            }
            for r in self._run(query)
        ]

    # ---- Performance dashboard ---------------------------------------------

    def get_performance(self):
        return {
            "summary": self._performance_summary(),
            "rating_distribution": self._rating_distribution(),
            "top_rated_organizations": self._top_organizations(order_by="o.org_rating DESC NULLS LAST"),
            "top_collaborator_organizations": self._top_organizations(
                order_by="o.org_rating DESC NULLS LAST", collaborator_only=True
            ),
            # SCHEMA GAP: no is_contributor column — see module docstring.
            "top_contributor_organizations": [],
            "ratings_by_organization_type": self._ratings_by_column("org_type"),
            "ratings_by_organization_size": self._ratings_by_column("org_size"),
        }

    def _performance_summary(self):
        query = f"""
            SELECT
                ROUND(AVG(o.org_rating)::numeric, 2) AS average_rating,
                COUNT(*) FILTER (WHERE o.org_rating IS NOT NULL) AS rated_organizations,
                COUNT(*) FILTER (WHERE o.org_rating IS NULL) AS unrated_organizations,
                COUNT(*) FILTER (WHERE o.org_rating = 5) AS five_star_organizations
            FROM {ORGANIZATIONS} o
            WHERE 1=1 {self.time_where} {self.common_where}
        """
        row = self._run(query, fetch="one") or {}
        return {
            "average_rating": float(row["average_rating"]) if row.get("average_rating") is not None else 0.0,
            "rated_organizations": int(row.get("rated_organizations") or 0),
            "unrated_organizations": int(row.get("unrated_organizations") or 0),
            "five_star_organizations": int(row.get("five_star_organizations") or 0),
        }

    def _rating_distribution(self):
        query = f"""
            SELECT o.org_rating AS rating, COUNT(*) AS count
            FROM {ORGANIZATIONS} o
            WHERE o.org_rating IS NOT NULL {self.time_where} {self.common_where}
            GROUP BY 1
            ORDER BY 1
        """
        return [{"rating": int(r["rating"]), "count": int(r["count"])} for r in self._run(query)]

    def _top_organizations(self, order_by, collaborator_only=False, limit=TOP_N_DEFAULT):
        collaborator_filter = "AND o.is_collaborator IS TRUE" if collaborator_only else ""
        query = f"""
            SELECT o.org_id, o.org_name, o.org_rating, o.org_type::text AS org_type, o.org_size::text AS org_size
            FROM {ORGANIZATIONS} o
            WHERE 1=1 {collaborator_filter} {self.time_where} {self.common_where}
            ORDER BY {order_by}, o.org_name ASC
            LIMIT %s
        """
        return [dict(r) for r in self._run(query, extra_params=(limit,))]

    def _ratings_by_column(self, column):
        query = f"""
            SELECT COALESCE(o.{column}::text, 'unknown') AS {column},
                   ROUND(AVG(o.org_rating)::numeric, 2) AS average_rating,
                   COUNT(*) AS count
            FROM {ORGANIZATIONS} o
            WHERE 1=1 {self.time_where} {self.common_where}
            GROUP BY 1
            ORDER BY average_rating DESC NULLS LAST
        """
        return [
            {
                column: r[column],
                "average_rating": float(r["average_rating"]) if r["average_rating"] is not None else 0.0,
                "count": int(r["count"]),
            }
            for r in self._run(query)
        ]


# --------------------------------------------------------------------------
# Lambda entrypoints — two separate handlers, per the issue's alternate
# suggested routing (POST /analytics/organizations/overview and
# POST /analytics/organizations/performance).
# --------------------------------------------------------------------------

def _empty_overview():
    return {
        "summary": {
            "total_organizations": 0, "non_profit_organizations": 0, "for_profit_organizations": 0,
            "collaborator_organizations": 0, "non_collaborator_organizations": 0,
            "contributor_organizations": 0, "non_contributor_organizations": 0,
        },
        "organization_activity_trend": [], "organizations_by_type": [], "organizations_by_size": [],
        "organizations_by_location": [], "collaborator_distribution": [], "contributor_distribution": [],
    }


def _empty_performance():
    return {
        "summary": {"average_rating": 0.0, "rated_organizations": 0, "unrated_organizations": 0, "five_star_organizations": 0},
        "rating_distribution": [], "top_rated_organizations": [], "top_collaborator_organizations": [],
        "top_contributor_organizations": [], "ratings_by_organization_type": [], "ratings_by_organization_size": [],
    }


def _run_dashboard(event, dashboard_key, method_name, empty_fn):
    conn = None
    cursor = None
    filters = parse_event_body(event)
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        service = OrganizationAnalyticsService(cursor, filters)
        result = getattr(service, method_name)()
        return build_response(200, {dashboard_key: result})
    except Exception as e:
        print(f"ERROR in organization_analytics.{method_name}: {e}")
        return build_response(500, {dashboard_key: empty_fn()})
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def overview_handler(event, context):
    """Lambda entry point for POST /analytics/organizations/overview"""
    return _run_dashboard(event, "organization_overview", "get_overview", _empty_overview)


def performance_handler(event, context):
    """Lambda entry point for POST /analytics/organizations/performance"""
    return _run_dashboard(event, "organization_performance", "get_performance", _empty_performance)


if __name__ == "__main__":
    # Local smoke test — requires DATABASE_URL set (see README).
    print("=== organization_overview ===")
    print(json.dumps(overview_handler({"time_filter": "ALL"}, None), indent=2))
    print("\n=== organization_performance ===")
    print(json.dumps(performance_handler({"time_filter": "ALL"}, None), indent=2))
