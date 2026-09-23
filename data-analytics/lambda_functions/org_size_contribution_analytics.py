import json
import os
import unittest
from datetime import datetime, timedelta
from io import StringIO

import pandas as pd

try:
    import psycopg2
except ImportError:
    psycopg2 = None

MOCK_DATA_DIR = os.environ.get(
    "MOCK_DATA_DIR",
    os.path.join(os.path.dirname(__file__), "..", "sql"),
)
USE_MOCK_DATA = os.environ.get("USE_MOCK_DATA", "true").lower() == "true"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_data(sql_dir):
    org_df = pd.read_csv(os.path.join(sql_dir, "organizations.csv"))
    state_df = pd.read_csv(os.path.join(sql_dir, "states.csv"))
    country_df = pd.read_csv(os.path.join(sql_dir, "countries.csv"))

    org_df["created_at"] = pd.to_datetime(org_df["created_at"])
    org_df["is_collaborator"] = org_df["is_collaborator"].map(
        {"TRUE": True, "FALSE": False, True: True, False: False}
    )
    if "is_contributor" in org_df.columns:
        org_df["is_contributor"] = org_df["is_contributor"].map(
            {"TRUE": True, "FALSE": False, True: True, False: False}
        )
    else:
        org_df["is_contributor"] = False

    return org_df, state_df, country_df


# ---------------------------------------------------------------------------
# Filtering helpers
# ---------------------------------------------------------------------------

def apply_country_filter(org_df, state_df, country_df, country_value):
    if not country_value or country_value.upper() == "ALL":
        return org_df

    country_match = country_df[
        (country_df["country_code"].str.upper() == country_value.upper())
        | (country_df["country_name"].str.lower() == country_value.lower())
    ]
    if country_match.empty:
        return org_df.iloc[0:0]

    country_ids = country_match["country_id"].tolist()
    valid_state_ids = state_df[state_df["country_id"].isin(country_ids)]["state_id"].tolist()
    return org_df[org_df["state_id"].isin(valid_state_ids)]


def apply_org_type_filter(df, organization_type):
    if not organization_type or organization_type.upper() == "ALL":
        return df
    return df[df["org_type"].str.lower().str.replace("-", "_") == organization_type.lower()]


def apply_filters(org_df, state_df, country_df, country=None, organization_type=None):
    filtered = apply_country_filter(org_df, state_df, country_df, country)
    filtered = apply_org_type_filter(filtered, organization_type)
    return filtered


def filter_by_window(df, start_date, end_date):
    return df[
        (df["created_at"] >= pd.Timestamp(start_date))
        & (df["created_at"] <= pd.Timestamp(end_date))
    ]


# ---------------------------------------------------------------------------
# Chart builders
# ---------------------------------------------------------------------------

def build_organizations_by_size(df):
    if len(df) == 0:
        return []

    by_size = df.groupby("org_size").size().reset_index(name="count")
    by_size = by_size.sort_values("count", ascending=False)

    return [
        {"size": str(row["org_size"]), "count": int(row["count"])}
        for _, row in by_size.iterrows()
    ]


def build_collaborator_vs_contributor(df):
    if len(df) == 0:
        return []

    total = len(df)
    collab_count = int((df["is_collaborator"] == True).sum())
    contrib_count = int((df["is_contributor"] == True).sum())

    collab_pct = round(collab_count / total * 100, 1) if total > 0 else 0.0
    contrib_pct = round(contrib_count / total * 100, 1) if total > 0 else 0.0

    return [
        {"type": "Collaborator", "count": collab_count, "percentage": collab_pct},
        {"type": "Contributor", "count": contrib_count, "percentage": contrib_pct},
    ]


# ---------------------------------------------------------------------------
# Time-bucket windows
# ---------------------------------------------------------------------------

def get_bucket_windows():
    today = pd.Timestamp.now().normalize()
    return {
        "7D": (today - pd.Timedelta(days=7), today + pd.Timedelta(days=1)),
        "30D": (today - pd.Timedelta(days=30), today + pd.Timedelta(days=1)),
        "1Y": (today - pd.DateOffset(years=1), today + pd.Timedelta(days=1)),
        "All": (pd.Timestamp.min, today + pd.Timedelta(days=1)),
    }


# ---------------------------------------------------------------------------
# Main handler
# ---------------------------------------------------------------------------

def handler(event, context=None):
    body = event if isinstance(event, dict) else {}

    country = body.get("country", "ALL")
    organization_type = body.get("organization_type", "ALL")
    size_start = body.get("size_start_date")
    size_end = body.get("size_end_date")
    contrib_start = body.get("contribution_start_date")
    contrib_end = body.get("contribution_end_date")

    # --- Input validation ---------------------------------------------------
    errors = []

    for label, s, e in [
        ("size", size_start, size_end),
        ("contribution", contrib_start, contrib_end),
    ]:
        if s and not e:
            errors.append(f"{label}_end_date is required when {label}_start_date is provided")
        if e and not s:
            errors.append(f"{label}_start_date is required when {label}_end_date is provided")
        if s and e:
            try:
                sd = datetime.strptime(s, "%Y-%m-%d")
                ed = datetime.strptime(e, "%Y-%m-%d")
                if sd > ed:
                    errors.append(f"{label}_start_date must be before {label}_end_date")
            except ValueError:
                errors.append(f"Invalid date format for {label} dates. Use YYYY-MM-DD")

    if errors:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "; ".join(errors)}),
        }

    # --- Load data ----------------------------------------------------------
    use_mock = os.environ.get("USE_MOCK_DATA", "true").lower() == "true"
    mock_dir = os.environ.get(
        "MOCK_DATA_DIR",
        os.path.join(os.path.dirname(__file__), "..", "sql"),
    )

    if use_mock:
        org_df, state_df, country_df = load_data(mock_dir)
    elif not use_mock:
        if psycopg2 is None:
            return {
                "statusCode": 500,
                "body": json.dumps({"error": "psycopg2 not installed"}),
            }
        return {
            "statusCode": 501,
            "body": json.dumps({"error": "Postgres path not implemented yet"}),
        }

    # --- Apply common filters -----------------------------------------------
    filtered = apply_filters(org_df, state_df, country_df, country, organization_type)

    has_size_custom = size_start and size_end
    has_contrib_custom = contrib_start and contrib_end
    is_custom = has_size_custom or has_contrib_custom

    # --- Build response -----------------------------------------------------
    if is_custom:
        size_data = []
        contrib_data = []

        if has_size_custom:
            window_df = filter_by_window(filtered, size_start, size_end)
            size_data = build_organizations_by_size(window_df)

        if has_contrib_custom:
            window_df = filter_by_window(filtered, contrib_start, contrib_end)
            contrib_data = build_collaborator_vs_contributor(window_df)

        response = {
            "Custom": {
                "organizations_by_size": size_data,
                "collaborator_vs_contributor": contrib_data,
            }
        }
    else:
        buckets = get_bucket_windows()
        response = {}

        for bucket_name, (start, end) in buckets.items():
            window_df = filtered[
                (filtered["created_at"] >= start) & (filtered["created_at"] < end)
            ]
            response[bucket_name] = {
                "organizations_by_size": build_organizations_by_size(window_df),
                "collaborator_vs_contributor": build_collaborator_vs_contributor(window_df),
            }

        response["Custom"] = {
            "organizations_by_size": [],
            "collaborator_vs_contributor": [],
        }

    return {
        "statusCode": 200,
        "body": json.dumps(response),
    }


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------

class TestOrgSizeContributionAnalytics(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.org_csv = (
            "org_id,org_name,street,city_name,state_id,zip_code,mission,web_url,phone,email,"
            "org_type,org_size,org_rating,is_collaborator,is_contributor,created_at,last_updated_at\n"
            "ORG001,Alpha Org,123 Main,CityA,CA,90001,Help,https://a.org,111-111-1111,a@a.org,"
            "non_profit,small,5,TRUE,FALSE,2026-09-20 10:00:00,2026-09-20 10:00:00\n"
            "ORG002,Beta Org,456 Oak,CityB,TX,75001,Serve,https://b.org,222-222-2222,b@b.org,"
            "for_profit,large,3,FALSE,TRUE,2026-09-18 10:00:00,2026-09-18 10:00:00\n"
            "ORG003,Gamma Org,789 Elm,CityC,CA,90002,Aid,https://c.org,333-333-3333,c@c.org,"
            "non_profit,medium,,TRUE,TRUE,2026-08-01 10:00:00,2026-08-01 10:00:00\n"
            "ORG004,Delta Org,321 Pine,CityD,NY,10001,Support,https://d.org,444-444-4444,d@d.org,"
            "non_profit,small,4,TRUE,FALSE,2026-06-15 10:00:00,2026-06-15 10:00:00\n"
            "ORG005,Epsilon Org,654 Birch,CityE,TX,75002,Care,https://e.org,555-555-5555,e@e.org,"
            "for_profit,medium,2,FALSE,FALSE,2026-01-10 10:00:00,2026-01-10 10:00:00\n"
            "ORG006,Zeta Org,987 Maple,CityF,CA,90003,Grow,https://f.org,666-666-6666,f@f.org,"
            "non_profit,large,5,TRUE,TRUE,2025-03-01 10:00:00,2025-03-01 10:00:00\n"
        )
        cls.state_csv = (
            "state_id,country_id,state_name,state_code,last_update_date\n"
            "CA,1,California,US-CA,2025-08-08 00:00:00\n"
            "TX,1,Texas,US-TX,2025-08-08 00:00:00\n"
            "NY,1,New York,US-NY,2025-08-08 00:00:00\n"
            "MH,2,Maharashtra,IN-MH,2025-08-08 00:00:00\n"
        )
        cls.country_csv = (
            "country_id,country_name,country_code,last_update_date\n"
            "1,United States,USA,2025-08-08 00:00:00\n"
            "2,India,IND,2025-08-08 00:00:00\n"
        )

        cls.org_df = pd.read_csv(StringIO(cls.org_csv))
        cls.state_df = pd.read_csv(StringIO(cls.state_csv))
        cls.country_df = pd.read_csv(StringIO(cls.country_csv))

        cls.org_df["created_at"] = pd.to_datetime(cls.org_df["created_at"])
        cls.org_df["is_collaborator"] = cls.org_df["is_collaborator"].map(
            {"TRUE": True, "FALSE": False, True: True, False: False}
        )
        cls.org_df["is_contributor"] = cls.org_df["is_contributor"].map(
            {"TRUE": True, "FALSE": False, True: True, False: False}
        )

    def _call_mock(self, body=None):
        import tempfile, shutil
        tmp = tempfile.mkdtemp()
        try:
            pd.read_csv(StringIO(self.org_csv)).to_csv(os.path.join(tmp, "organizations.csv"), index=False)
            pd.read_csv(StringIO(self.state_csv)).to_csv(os.path.join(tmp, "states.csv"), index=False)
            pd.read_csv(StringIO(self.country_csv)).to_csv(os.path.join(tmp, "countries.csv"), index=False)

            old_dir = os.environ.get("MOCK_DATA_DIR")
            old_mock = os.environ.get("USE_MOCK_DATA")
            os.environ["MOCK_DATA_DIR"] = tmp
            os.environ["USE_MOCK_DATA"] = "true"
            try:
                resp = handler(body or {})
            finally:
                if old_dir is not None:
                    os.environ["MOCK_DATA_DIR"] = old_dir
                else:
                    os.environ.pop("MOCK_DATA_DIR", None)
                if old_mock is not None:
                    os.environ["USE_MOCK_DATA"] = old_mock
                else:
                    os.environ.pop("USE_MOCK_DATA", None)
            return resp
        finally:
            shutil.rmtree(tmp)

    def _parse(self, resp):
        self.assertEqual(resp["statusCode"], 200)
        return json.loads(resp["body"])

    # --- No Custom params: 5 top-level keys --------------------------------

    def test_no_params_returns_five_keys(self):
        data = self._parse(self._call_mock())
        self.assertEqual(set(data.keys()), {"7D", "30D", "1Y", "All", "Custom"})

    def test_no_params_custom_is_empty(self):
        data = self._parse(self._call_mock())
        self.assertEqual(data["Custom"]["organizations_by_size"], [])
        self.assertEqual(data["Custom"]["collaborator_vs_contributor"], [])

    def test_each_bucket_has_both_charts(self):
        data = self._parse(self._call_mock())
        for key in ["7D", "30D", "1Y", "All", "Custom"]:
            self.assertIn("organizations_by_size", data[key])
            self.assertIn("collaborator_vs_contributor", data[key])

    # --- Country filter -----------------------------------------------------

    def test_country_filter(self):
        data = self._parse(self._call_mock({"country": "USA"}))
        all_bucket = data["All"]
        self.assertTrue(len(all_bucket["organizations_by_size"]) > 0)

    def test_country_filter_no_match(self):
        data = self._parse(self._call_mock({"country": "XYZ"}))
        all_bucket = data["All"]
        self.assertEqual(all_bucket["organizations_by_size"], [])

    # --- Org type filter ----------------------------------------------------

    def test_org_type_filter(self):
        data = self._parse(self._call_mock({"organization_type": "non_profit"}))
        all_bucket = data["All"]
        total = sum(r["count"] for r in all_bucket["organizations_by_size"])
        self.assertEqual(total, 4)

    # --- Only size Custom pair supplied -------------------------------------

    def test_size_custom_only_returns_custom_key(self):
        data = self._parse(self._call_mock({
            "size_start_date": "2026-01-01",
            "size_end_date": "2026-12-31",
        }))
        self.assertEqual(set(data.keys()), {"Custom"})

    def test_size_custom_populates_size_chart(self):
        data = self._parse(self._call_mock({
            "size_start_date": "2026-01-01",
            "size_end_date": "2026-12-31",
        }))
        self.assertTrue(len(data["Custom"]["organizations_by_size"]) > 0)

    def test_size_custom_leaves_contrib_empty(self):
        data = self._parse(self._call_mock({
            "size_start_date": "2026-01-01",
            "size_end_date": "2026-12-31",
        }))
        self.assertEqual(data["Custom"]["collaborator_vs_contributor"], [])

    # --- Only contribution Custom pair supplied -----------------------------

    def test_contrib_custom_only_returns_custom_key(self):
        data = self._parse(self._call_mock({
            "contribution_start_date": "2026-01-01",
            "contribution_end_date": "2026-12-31",
        }))
        self.assertEqual(set(data.keys()), {"Custom"})

    def test_contrib_custom_populates_contrib_chart(self):
        data = self._parse(self._call_mock({
            "contribution_start_date": "2026-01-01",
            "contribution_end_date": "2026-12-31",
        }))
        contrib = data["Custom"]["collaborator_vs_contributor"]
        self.assertEqual(len(contrib), 2)
        types = {r["type"] for r in contrib}
        self.assertEqual(types, {"Collaborator", "Contributor"})

    def test_contrib_custom_leaves_size_empty(self):
        data = self._parse(self._call_mock({
            "contribution_start_date": "2026-01-01",
            "contribution_end_date": "2026-12-31",
        }))
        self.assertEqual(data["Custom"]["organizations_by_size"], [])

    # --- Both Custom pairs supplied -----------------------------------------

    def test_both_custom_returns_custom_only(self):
        data = self._parse(self._call_mock({
            "size_start_date": "2026-01-01",
            "size_end_date": "2026-12-31",
            "contribution_start_date": "2026-01-01",
            "contribution_end_date": "2026-12-31",
        }))
        self.assertEqual(set(data.keys()), {"Custom"})
        self.assertTrue(len(data["Custom"]["organizations_by_size"]) > 0)
        self.assertEqual(len(data["Custom"]["collaborator_vs_contributor"]), 2)

    # --- Collaborator vs Contributor independent counts ----------------------

    def test_collab_contrib_independent_counts(self):
        data = self._parse(self._call_mock())
        contrib = data["All"]["collaborator_vs_contributor"]
        if len(contrib) == 2:
            collab = next(r for r in contrib if r["type"] == "Collaborator")
            contri = next(r for r in contrib if r["type"] == "Contributor")
            total = sum(r["count"] for r in data["All"]["organizations_by_size"])
            self.assertLessEqual(collab["count"], total)
            self.assertLessEqual(contri["count"], total)

    # --- Missing is_contributor column handled gracefully --------------------

    def test_missing_is_contributor_column(self):
        import tempfile, shutil
        org_no_contrib = (
            "org_id,org_name,street,city_name,state_id,zip_code,mission,web_url,phone,email,"
            "org_type,org_size,org_rating,is_collaborator,created_at,last_updated_at\n"
            "ORG001,Alpha Org,123 Main,CityA,CA,90001,Help,https://a.org,111-111-1111,a@a.org,"
            "non_profit,small,5,TRUE,2026-09-20 10:00:00,2026-09-20 10:00:00\n"
        )
        tmp = tempfile.mkdtemp()
        try:
            pd.read_csv(StringIO(org_no_contrib)).to_csv(os.path.join(tmp, "organizations.csv"), index=False)
            pd.read_csv(StringIO(self.state_csv)).to_csv(os.path.join(tmp, "states.csv"), index=False)
            pd.read_csv(StringIO(self.country_csv)).to_csv(os.path.join(tmp, "countries.csv"), index=False)

            old_dir = os.environ.get("MOCK_DATA_DIR")
            old_mock = os.environ.get("USE_MOCK_DATA")
            os.environ["MOCK_DATA_DIR"] = tmp
            os.environ["USE_MOCK_DATA"] = "true"
            try:
                resp = handler({})
            finally:
                if old_dir is not None:
                    os.environ["MOCK_DATA_DIR"] = old_dir
                else:
                    os.environ.pop("MOCK_DATA_DIR", None)
                if old_mock is not None:
                    os.environ["USE_MOCK_DATA"] = old_mock
                else:
                    os.environ.pop("USE_MOCK_DATA", None)

            data = json.loads(resp["body"])
            contrib = data["All"]["collaborator_vs_contributor"]
            contri_row = next(r for r in contrib if r["type"] == "Contributor")
            self.assertEqual(contri_row["count"], 0)
            self.assertEqual(contri_row["percentage"], 0.0)
        finally:
            shutil.rmtree(tmp)

    # --- Error handling -----------------------------------------------------

    def test_missing_half_of_size_pair(self):
        resp = self._call_mock({"size_start_date": "2026-01-01"})
        self.assertEqual(resp["statusCode"], 400)

    def test_missing_half_of_contrib_pair(self):
        resp = self._call_mock({"contribution_end_date": "2026-12-31"})
        self.assertEqual(resp["statusCode"], 400)

    def test_bad_date_format(self):
        resp = self._call_mock({
            "size_start_date": "01-01-2026",
            "size_end_date": "12-31-2026",
        })
        self.assertEqual(resp["statusCode"], 400)

    def test_start_after_end(self):
        resp = self._call_mock({
            "size_start_date": "2026-12-31",
            "size_end_date": "2026-01-01",
        })
        self.assertEqual(resp["statusCode"], 400)

    # --- Empty data ---------------------------------------------------------

    def test_empty_csv_no_crash(self):
        import tempfile, shutil
        empty_org = (
            "org_id,org_name,street,city_name,state_id,zip_code,mission,web_url,phone,email,"
            "org_type,org_size,org_rating,is_collaborator,is_contributor,created_at,last_updated_at\n"
        )
        tmp = tempfile.mkdtemp()
        try:
            pd.read_csv(StringIO(empty_org)).to_csv(os.path.join(tmp, "organizations.csv"), index=False)
            pd.read_csv(StringIO(self.state_csv)).to_csv(os.path.join(tmp, "states.csv"), index=False)
            pd.read_csv(StringIO(self.country_csv)).to_csv(os.path.join(tmp, "countries.csv"), index=False)

            old_dir = os.environ.get("MOCK_DATA_DIR")
            old_mock = os.environ.get("USE_MOCK_DATA")
            os.environ["MOCK_DATA_DIR"] = tmp
            os.environ["USE_MOCK_DATA"] = "true"
            try:
                resp = handler({})
            finally:
                if old_dir is not None:
                    os.environ["MOCK_DATA_DIR"] = old_dir
                else:
                    os.environ.pop("MOCK_DATA_DIR", None)
                if old_mock is not None:
                    os.environ["USE_MOCK_DATA"] = old_mock
                else:
                    os.environ.pop("USE_MOCK_DATA", None)

            self.assertEqual(resp["statusCode"], 200)
            data = json.loads(resp["body"])
            for key in ["7D", "30D", "1Y", "All", "Custom"]:
                self.assertEqual(data[key]["organizations_by_size"], [])
        finally:
            shutil.rmtree(tmp)

    def test_single_row_csv_no_crash(self):
        import tempfile, shutil
        one_row = (
            "org_id,org_name,street,city_name,state_id,zip_code,mission,web_url,phone,email,"
            "org_type,org_size,org_rating,is_collaborator,is_contributor,created_at,last_updated_at\n"
            "ORG001,Only Org,123 Main,CityA,CA,90001,Help,https://a.org,111,a@a.org,"
            "non_profit,small,5,TRUE,TRUE,2026-09-20 10:00:00,2026-09-20 10:00:00\n"
        )
        tmp = tempfile.mkdtemp()
        try:
            pd.read_csv(StringIO(one_row)).to_csv(os.path.join(tmp, "organizations.csv"), index=False)
            pd.read_csv(StringIO(self.state_csv)).to_csv(os.path.join(tmp, "states.csv"), index=False)
            pd.read_csv(StringIO(self.country_csv)).to_csv(os.path.join(tmp, "countries.csv"), index=False)

            old_dir = os.environ.get("MOCK_DATA_DIR")
            old_mock = os.environ.get("USE_MOCK_DATA")
            os.environ["MOCK_DATA_DIR"] = tmp
            os.environ["USE_MOCK_DATA"] = "true"
            try:
                resp = handler({})
            finally:
                if old_dir is not None:
                    os.environ["MOCK_DATA_DIR"] = old_dir
                else:
                    os.environ.pop("MOCK_DATA_DIR", None)
                if old_mock is not None:
                    os.environ["USE_MOCK_DATA"] = old_mock
                else:
                    os.environ.pop("USE_MOCK_DATA", None)

            self.assertEqual(resp["statusCode"], 200)
        finally:
            shutil.rmtree(tmp)


# ---------------------------------------------------------------------------
# Local test runner
# ---------------------------------------------------------------------------

def run_local():
    sql_dir = MOCK_DATA_DIR
    print(f"Loading mock data from: {sql_dir}")
    print()

    test_events = [
        {"label": "No body ({})", "event": {}},
        {"label": "Country filter: USA", "event": {"country": "USA"}},
        {"label": "Org type: non_profit", "event": {"organization_type": "non_profit"}},
        {
            "label": "Size Custom only",
            "event": {
                "size_start_date": "2026-01-01",
                "size_end_date": "2026-12-31",
            },
        },
        {
            "label": "Contribution Custom only",
            "event": {
                "contribution_start_date": "2025-01-01",
                "contribution_end_date": "2026-12-31",
            },
        },
        {
            "label": "Both Custom ranges",
            "event": {
                "size_start_date": "2026-01-01",
                "size_end_date": "2026-12-31",
                "contribution_start_date": "2025-01-01",
                "contribution_end_date": "2026-12-31",
            },
        },
    ]

    for t in test_events:
        print(f"=== Test: {t['label']} ===")
        resp = handler(t["event"])
        body = json.loads(resp["body"]) if resp["statusCode"] == 200 else resp
        print(json.dumps(body, indent=2))
        print()


def main():
    print("=" * 60)
    print("RUNNING UNIT TESTS")
    print("=" * 60)

    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestOrgSizeContributionAnalytics)
    runner = unittest.TextTestRunner(verbosity=2)
    test_result = runner.run(suite)

    print()
    print("=" * 60)
    print("RUNNING LOCAL TESTS WITH MOCK DATA")
    print("=" * 60)
    print()

    try:
        run_local()
    except Exception as e:
        print(f"Local test error (expected if CSVs not present): {e}")

    if test_result.wasSuccessful():
        print("\nAll unit tests passed.")
    else:
        print("\nSome unit tests failed.")


if __name__ == "__main__":
    main()
