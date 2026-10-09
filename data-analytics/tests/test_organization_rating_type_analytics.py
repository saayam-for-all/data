"""Unit tests for organization_rating_type_analytics (issue #380).

Run from the repo root with:
    python -m unittest discover -s data-analytics/tests -v
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest import mock

sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "lambda_functions"),
)

import organization_rating_type_analytics as analytics  # noqa: E402


TODAY = date(2026, 9, 28)

ALL_KEYS = ["7D", "30D", "1Y", "All", "Custom"]
CHART_KEYS = ["organization_mix_trend", "rating_distribution"]
SERIES_KEYS = ["for_profit", "non_profit"]

ORG_HEADER = "org_id,org_rating,org_type,state_id,created_at\n"

STATES_CSV = (
    "state_id,country_id\n"
    "CA,1\n"
    "TX,1\n"
    "KA,2\n"
)

COUNTRIES_CSV = (
    "country_id,country_name,country_code\n"
    "1,UNITED_STATES_OF_AMERICA,USA\n"
    "2,INDIA,IND\n"
)

# today = 2026-09-28  ->  7D: 09-21..09-28, 30D: 08-29..09-28, 1Y: 2025-09-28..
ORGS_CSV = ORG_HEADER + (
    "O1,5,Non-Profit,CA,2024-03-10 10:00:00\n"   # USA, only in All
    "O2,4,For-profit,TX,2025-06-15 12:00:00\n"   # USA, before 1Y
    "O3,3,Non-Profit,KA,2026-01-05 09:00:00\n"   # IND, 1Y
    "O4,5,Non-Profit,CA,2026-09-01 08:00:00\n"   # USA, 30D
    "O5,,For-profit,TX,2026-09-25 23:59:59\n"    # USA, 7D, null rating
    "O6,2,,KA,2026-09-28 23:59:59\n"             # IND, 7D, null type, last second
    "O7,4,Non-Profit,CA,2026-09-27 14:00:00\n"   # USA, 7D
)

EMPTY_TREND = {"non_profit": [], "for_profit": []}


def rating(*pairs):
    return [{"rating": r, "count": c} for r, c in pairs]


def series(*pairs):
    return [{"period": p, "count": c} for p, c in pairs]


class AnalyticsTestCase(unittest.TestCase):
    """Writes mock CSVs into a temp dir and points the module at it."""

    orgs_csv = ORGS_CSV

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.mock_dir = tmp.name

        self.write_csv("states.csv", STATES_CSV)
        self.write_csv("countries.csv", COUNTRIES_CSV)
        self.write_csv("organizations.csv", self.orgs_csv)

        env = mock.patch.dict(
            os.environ, {"USE_MOCK_DATA": "true", "MOCK_DATA_DIR": self.mock_dir}
        )
        env.start()
        self.addCleanup(env.stop)

    def write_csv(self, name, content):
        with open(os.path.join(self.mock_dir, name), "w", encoding="utf-8", newline="") as fh:
            fh.write(content)

    def call(self, event):
        return analytics.handle_request(event, today=TODAY)

    def ok_body(self, event):
        resp = self.call(event)
        self.assertEqual(resp["statusCode"], 200, resp["body"])
        body = json.loads(resp["body"])
        self.assert_shape(body)
        return body

    def assert_shape(self, body):
        for bucket, payload in body.items():
            self.assertEqual(sorted(payload), CHART_KEYS, bucket)
            self.assertIsInstance(payload["rating_distribution"], list, bucket)
            trend = payload["organization_mix_trend"]
            self.assertEqual(sorted(trend), SERIES_KEYS, bucket)
            for org_type in SERIES_KEYS:
                counts = [point["count"] for point in trend[org_type]]
                self.assertEqual(counts, sorted(counts), (bucket, org_type))
                periods = [point["period"] for point in trend[org_type]]
                self.assertEqual(periods, sorted(periods), (bucket, org_type))
                self.assertTrue(all(c > 0 for c in counts), (bucket, org_type))


class FixedBucketTests(AnalyticsTestCase):

    def test_no_body_returns_exact_bucket_keys(self):
        for event in ({}, None, {"body": None}, {"body": ""}):
            with self.subTest(event=event):
                body = self.ok_body(event)
                self.assertEqual(list(body), ALL_KEYS)
                for bucket in ("7D", "30D", "1Y", "All"):
                    self.assertTrue(body[bucket]["rating_distribution"], bucket)
                    self.assertTrue(body[bucket]["organization_mix_trend"]["non_profit"], bucket)
                    self.assertTrue(body[bucket]["organization_mix_trend"]["for_profit"], bucket)
                self.assertEqual(body["Custom"], analytics.empty_chart_payload())

    def test_bucket_values(self):
        body = self.ok_body({})

        self.assertEqual(body["7D"]["rating_distribution"], rating((2, 1), (4, 1)))
        self.assertEqual(body["7D"]["organization_mix_trend"], {
            "non_profit": series(("2026-09-27", 4)),
            "for_profit": series(("2026-09-25", 2)),
        })

        self.assertEqual(body["30D"]["rating_distribution"], rating((2, 1), (4, 1), (5, 1)))
        self.assertEqual(body["30D"]["organization_mix_trend"], {
            "non_profit": series(("2026-09-01", 3), ("2026-09-27", 4)),
            "for_profit": series(("2026-09-25", 2)),
        })

        self.assertEqual(
            body["1Y"]["rating_distribution"], rating((2, 1), (3, 1), (4, 1), (5, 1))
        )
        self.assertEqual(body["1Y"]["organization_mix_trend"], {
            "non_profit": series(("2026-01", 2), ("2026-09", 4)),
            "for_profit": series(("2026-09", 2)),
        })

        self.assertEqual(body["All"]["rating_distribution"], rating((2, 1), (3, 1), (4, 2), (5, 2)))
        self.assertEqual(body["All"]["organization_mix_trend"], {
            "non_profit": series(("2024-03", 1), ("2026-01", 2), ("2026-09", 4)),
            "for_profit": series(("2025-06", 1), ("2026-09", 2)),
        })

    def test_trend_is_cumulative_and_counts_orgs_before_window(self):
        body = self.ok_body({})
        # Only O7 is a non-profit inside 7D, yet the running total includes
        # the three non-profits created earlier.
        self.assertEqual(
            body["7D"]["organization_mix_trend"]["non_profit"], series(("2026-09-27", 4))
        )

    def test_no_zero_filled_periods(self):
        body = self.ok_body({})
        # 30 daily periods in the window, but only days with new orgs appear.
        self.assertEqual(len(body["30D"]["organization_mix_trend"]["non_profit"]), 2)
        self.assertEqual(len(body["30D"]["organization_mix_trend"]["for_profit"]), 1)

    def test_period_format_per_bucket(self):
        body = self.ok_body({})
        formats = {"7D": 10, "30D": 10, "1Y": 7, "All": 7}
        for bucket, length in formats.items():
            for org_type in SERIES_KEYS:
                for point in body[bucket]["organization_mix_trend"][org_type]:
                    with self.subTest(bucket=bucket, period=point["period"]):
                        self.assertEqual(len(point["period"]), length)
                        fmt = "%Y-%m-%d" if length == 10 else "%Y-%m"
                        datetime.strptime(point["period"], fmt)

        custom = self.ok_body({"type_start_date": "2026-09-01", "type_end_date": "2026-09-28"})
        for point in custom["Custom"]["organization_mix_trend"]["non_profit"]:
            datetime.strptime(point["period"], "%Y-%m-%d")

    def test_end_date_inclusive(self):
        # O6 is created at 23:59:59 on today's date and still lands in 7D.
        body = self.ok_body({})
        self.assertIn({"rating": 2, "count": 1}, body["7D"]["rating_distribution"])

        custom = self.ok_body({
            "rating_start_date": "2026-09-28", "rating_end_date": "2026-09-28",
            "type_start_date": "2026-09-25", "type_end_date": "2026-09-25",
        })
        self.assertEqual(custom["Custom"]["rating_distribution"], rating((2, 1)))
        self.assertEqual(
            custom["Custom"]["organization_mix_trend"]["for_profit"], series(("2026-09-25", 2))
        )

    def test_null_rating_excluded_and_null_type_still_rated(self):
        body = self.ok_body({})
        # O5 (null rating) is in 7D but absent from the rating chart.
        self.assertEqual(sum(r["count"] for r in body["7D"]["rating_distribution"]), 2)
        # O6 (null type) is counted in the rating chart...
        self.assertIn({"rating": 2, "count": 1}, body["7D"]["rating_distribution"])
        # ...but in neither trend series: totals cover the 6 typed orgs only.
        trend = body["All"]["organization_mix_trend"]
        self.assertEqual(trend["non_profit"][-1]["count"] + trend["for_profit"][-1]["count"], 6)

    def test_rating_chart_not_zero_filled(self):
        body = self.ok_body({})
        self.assertEqual([r["rating"] for r in body["7D"]["rating_distribution"]], [2, 4])


class CountryFilterTests(AnalyticsTestCase):

    def test_usa_counts_only_usa_orgs(self):
        for country in ("USA", "usa", "United States of America", " UNITED_STATES_OF_AMERICA "):
            with self.subTest(country=country):
                body = self.ok_body({"country": country})
                self.assertEqual(list(body), ALL_KEYS)
                self.assertEqual(body["All"]["rating_distribution"], rating((4, 2), (5, 2)))
                self.assertEqual(body["All"]["organization_mix_trend"], {
                    "non_profit": series(("2024-03", 1), ("2026-09", 3)),
                    "for_profit": series(("2025-06", 1), ("2026-09", 2)),
                })
                self.assertEqual(body["7D"]["rating_distribution"], rating((4, 1)))

    def test_ind_counts_only_ind_orgs(self):
        body = self.ok_body({"country": "IND"})
        self.assertEqual(body["All"]["rating_distribution"], rating((2, 1), (3, 1)))
        self.assertEqual(body["All"]["organization_mix_trend"], {
            "non_profit": series(("2026-01", 1)),
            "for_profit": [],
        })

    def test_all_country_is_unfiltered(self):
        self.assertEqual(self.ok_body({"country": "all"}), self.ok_body({}))

    def test_unknown_country_returns_empty_charts(self):
        body = self.ok_body({"country": "Atlantis"})
        self.assertEqual(list(body), ALL_KEYS)
        for bucket in ALL_KEYS:
            self.assertEqual(body[bucket], analytics.empty_chart_payload(), bucket)


class CustomRangeTests(AnalyticsTestCase):

    def test_rating_pair_only(self):
        body = self.ok_body({"rating_start_date": "2026-01-01", "rating_end_date": "2026-01-31"})
        self.assertEqual(list(body), ["Custom"])
        self.assertEqual(body["Custom"]["rating_distribution"], rating((3, 1)))
        self.assertEqual(body["Custom"]["organization_mix_trend"], EMPTY_TREND)

    def test_type_pair_only(self):
        body = self.ok_body({"type_start_date": "2026-09-01", "type_end_date": "2026-09-28"})
        self.assertEqual(list(body), ["Custom"])
        self.assertEqual(body["Custom"]["rating_distribution"], [])
        self.assertEqual(body["Custom"]["organization_mix_trend"], {
            "non_profit": series(("2026-09-01", 3), ("2026-09-27", 4)),
            "for_profit": series(("2026-09-25", 2)),
        })

    def test_both_pairs_each_use_their_own_range(self):
        body = self.ok_body({
            "rating_start_date": "2026-09-01", "rating_end_date": "2026-09-30",
            "type_start_date": "2025-06-01", "type_end_date": "2025-06-30",
        })
        self.assertEqual(list(body), ["Custom"])
        # Rating range (Sep 2026) -> O4, O6, O7 rated; O5 unrated.
        self.assertEqual(body["Custom"]["rating_distribution"], rating((2, 1), (4, 1), (5, 1)))
        # Type range (Jun 2025) -> only O2, a for-profit.
        self.assertEqual(body["Custom"]["organization_mix_trend"], {
            "non_profit": [],
            "for_profit": series(("2025-06-15", 1)),
        })

    def test_custom_with_country(self):
        body = self.ok_body({
            "country": "IND",
            "rating_start_date": "2026-09-01", "rating_end_date": "2026-09-30",
        })
        self.assertEqual(body["Custom"]["rating_distribution"], rating((2, 1)))

    def test_api_gateway_body_and_query_string(self):
        body = self.ok_body({"body": json.dumps({
            "rating_start_date": "2026-01-01", "rating_end_date": "2026-01-31",
        })})
        self.assertEqual(body["Custom"]["rating_distribution"], rating((3, 1)))

        body = self.ok_body({"queryStringParameters": {
            "type_start_date": "2025-06-01", "type_end_date": "2025-06-30",
        }})
        self.assertEqual(
            body["Custom"]["organization_mix_trend"]["for_profit"], series(("2025-06-15", 1))
        )


class ValidationTests(AnalyticsTestCase):

    BAD_EVENTS = {
        "missing rating end": {"rating_start_date": "2026-01-01"},
        "missing rating start": {"rating_end_date": "2026-01-01"},
        "missing type end": {"type_start_date": "2026-01-01"},
        "missing type start": {"type_end_date": "2026-01-01"},
        "slash format": {"rating_start_date": "2026/01/01", "rating_end_date": "2026-01-31"},
        "unpadded format": {"type_start_date": "2026-1-5", "type_end_date": "2026-01-31"},
        "datetime format": {"rating_start_date": "2026-01-01T00:00:00", "rating_end_date": "2026-01-31"},
        "invalid calendar date": {"rating_start_date": "2026-02-30", "rating_end_date": "2026-03-01"},
        "rating start after end": {"rating_start_date": "2026-02-01", "rating_end_date": "2026-01-01"},
        "type start after end": {"type_start_date": "2025-12-31", "type_end_date": "2025-01-01"},
        "non-string date": {"rating_start_date": 20260101, "rating_end_date": "2026-01-31"},
        "non-string country": {"country": 1},
        "invalid JSON body": {"body": "{not json"},
        "non-object JSON body": {"body": "[1, 2]"},
        "non-object body type": {"body": 42},
        "non-object event": ["country", "USA"],
    }

    def test_malformed_requests_return_400(self):
        for label, event in self.BAD_EVENTS.items():
            with self.subTest(label):
                resp = self.call(event)
                self.assertEqual(resp["statusCode"], 400, resp["body"])
                body = json.loads(resp["body"])
                self.assertEqual(list(body), ["error"])
                self.assertTrue(body["error"])

    def test_validation_runs_before_loading_data(self):
        with mock.patch.object(analytics, "load_organizations") as load:
            resp = self.call({"rating_start_date": "2026-01-01"})
        self.assertEqual(resp["statusCode"], 400)
        load.assert_not_called()

    def test_single_day_range_is_valid(self):
        body = self.ok_body({"rating_start_date": "2026-01-05", "rating_end_date": "2026-01-05"})
        self.assertEqual(body["Custom"]["rating_distribution"], rating((3, 1)))


class ResponseFormatTests(AnalyticsTestCase):

    def test_body_is_json_with_cors_header(self):
        resp = self.call({})
        self.assertEqual(resp["headers"]["Access-Control-Allow-Origin"], "*")
        self.assertEqual(resp["headers"]["Content-Type"], "application/json")
        self.assertIsInstance(resp["body"], str)
        self.assertIsInstance(json.loads(resp["body"]), dict)

    def test_lambda_handler_delegates(self):
        resp = analytics.lambda_handler({}, None)
        self.assertEqual(resp["statusCode"], 200)
        self.assertEqual(list(json.loads(resp["body"])), ALL_KEYS)

    def test_unexpected_error_returns_generic_500(self):
        with mock.patch.object(
            analytics, "load_organizations", side_effect=Exception("secret detail")
        ), mock.patch.object(analytics.traceback, "print_exc") as print_exc:
            resp = self.call({})
        self.assertEqual(resp["statusCode"], 500)
        self.assertEqual(json.loads(resp["body"]), {"error": "Internal server error."})
        self.assertNotIn("secret detail", resp["body"])
        print_exc.assert_called_once()


class EdgeCaseCsvTests(AnalyticsTestCase):

    EVENTS = [
        {},
        {"country": "USA"},
        {"rating_start_date": "2026-01-01", "rating_end_date": "2026-12-31"},
        {"type_start_date": "2026-01-01", "type_end_date": "2026-12-31"},
        {
            "rating_start_date": "2026-01-01", "rating_end_date": "2026-12-31",
            "type_start_date": "2026-01-01", "type_end_date": "2026-12-31",
        },
    ]

    def check_all_events(self):
        bodies = []
        for event in self.EVENTS:
            with self.subTest(event=event):
                bodies.append(self.ok_body(event))
        return bodies

    def test_header_only_organizations_csv(self):
        self.write_csv("organizations.csv", ORG_HEADER)
        for body in self.check_all_events():
            for payload in body.values():
                self.assertEqual(payload, analytics.empty_chart_payload())

    def test_zero_byte_organizations_csv(self):
        self.write_csv("organizations.csv", "")
        for body in self.check_all_events():
            for payload in body.values():
                self.assertEqual(payload, analytics.empty_chart_payload())

    def test_single_row_organizations_csv(self):
        self.write_csv("organizations.csv", ORG_HEADER + "X1,3,For-profit,CA,2026-09-27 10:00:00\n")
        bodies = self.check_all_events()

        for bucket in ("7D", "30D", "1Y", "All"):
            self.assertEqual(bodies[0][bucket]["rating_distribution"], rating((3, 1)), bucket)
            self.assertEqual(bodies[0][bucket]["organization_mix_trend"]["non_profit"], [], bucket)
        self.assertEqual(
            bodies[0]["7D"]["organization_mix_trend"]["for_profit"], series(("2026-09-27", 1))
        )
        self.assertEqual(
            bodies[0]["All"]["organization_mix_trend"]["for_profit"], series(("2026-09", 1))
        )
        self.assertEqual(bodies[2]["Custom"]["rating_distribution"], rating((3, 1)))
        self.assertEqual(
            bodies[3]["Custom"]["organization_mix_trend"]["for_profit"], series(("2026-09-27", 1))
        )


class DatabasePathTests(unittest.TestCase):

    CREDS = {
        "HOST": "db.example",
        "DATABASE NAME": "saayam",
        "USERNAME": "analytics",
        "PASSWORD": "secret",
        "PORT": 5432,
    }

    ROWS = [
        ("ORG1", Decimal("4"), "Non-Profit", datetime(2026, 9, 27, 10, tzinfo=timezone.utc),
         "USA", "UNITED_STATES_OF_AMERICA"),
        ("ORG2", Decimal("3.5"), "For-profit", datetime(2026, 1, 5, 9, tzinfo=timezone.utc),
         None, None),
        ("ORG3", 5, "nonprofit", datetime(2025, 3, 1, 12, tzinfo=timezone.utc),
         "IND", "INDIA"),
        ("ORG4", Decimal("2"), None, datetime(2026, 9, 28, 23, 59, 59, tzinfo=timezone.utc),
         None, None),
    ]

    def setUp(self):
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("USE_MOCK_DATA", None)

        self.boto3 = mock.MagicMock()
        self.boto3.client.return_value.get_parameter.return_value = {
            "Parameter": {"Value": json.dumps(self.CREDS)}
        }
        self.psycopg2 = mock.MagicMock()
        self.conn = self.psycopg2.connect.return_value
        self.cursor = self.conn.cursor.return_value
        self.cursor.fetchall.return_value = self.ROWS

        for name, value in (("boto3", self.boto3), ("psycopg2", self.psycopg2)):
            patcher = mock.patch.object(analytics, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_db_path_returns_expected_shapes(self):
        resp = analytics.handle_request({}, today=TODAY)
        self.assertEqual(resp["statusCode"], 200, resp["body"])
        body = json.loads(resp["body"])
        self.assertEqual(list(body), ALL_KEYS)

        # Decimal("3.5") is not a whole rating and is dropped; null country
        # rows still count when no country filter is applied.
        self.assertEqual(body["All"]["rating_distribution"], rating((2, 1), (4, 1), (5, 1)))
        self.assertEqual(body["All"]["organization_mix_trend"], {
            "non_profit": series(("2025-03", 1), ("2026-09", 2)),
            "for_profit": series(("2026-01", 1)),
        })
        self.assertEqual(body["7D"]["rating_distribution"], rating((2, 1), (4, 1)))
        for bucket, payload in body.items():
            self.assertEqual(sorted(payload), CHART_KEYS, bucket)
            self.assertEqual(sorted(payload["organization_mix_trend"]), SERIES_KEYS, bucket)

        self.boto3.client.assert_called_once_with("ssm", region_name="us-east-1")
        self.boto3.client.return_value.get_parameter.assert_called_once_with(
            Name="/dev/saayam/db/Virginia/Analytics/user", WithDecryption=True
        )
        self.psycopg2.connect.assert_called_once_with(
            host="db.example", database="saayam", user="analytics",
            password="secret", port=5432, sslmode="require",
        )
        self.cursor.execute.assert_called_once()
        args, kwargs = self.cursor.execute.call_args
        self.assertEqual(len(args), 1)
        self.assertEqual(kwargs, {})
        self.assertIn("virginia_dev_saayam_rdbms.organizations", args[0])
        self.cursor.close.assert_called_once()
        self.conn.close.assert_called_once()

    def test_db_path_country_filter_in_pandas(self):
        body = json.loads(analytics.handle_request({"country": "usa"}, today=TODAY)["body"])
        self.assertEqual(body["All"]["rating_distribution"], rating((4, 1)))
        self.assertEqual(body["All"]["organization_mix_trend"], {
            "non_profit": series(("2026-09", 1)),
            "for_profit": [],
        })

    def test_db_connection_closed_on_query_error(self):
        self.cursor.execute.side_effect = RuntimeError("query failed")
        with mock.patch.object(analytics.traceback, "print_exc"):
            resp = analytics.handle_request({}, today=TODAY)
        self.assertEqual(resp["statusCode"], 500)
        self.cursor.close.assert_called_once()
        self.conn.close.assert_called_once()

    def test_db_path_without_psycopg2_returns_500(self):
        with mock.patch.object(analytics, "psycopg2", None), \
                mock.patch.object(analytics.traceback, "print_exc"):
            resp = analytics.handle_request({}, today=TODAY)
        self.assertEqual(resp["statusCode"], 500)
        self.assertEqual(json.loads(resp["body"]), {"error": "Internal server error."})
        with mock.patch.object(analytics, "psycopg2", None):
            with self.assertRaisesRegex(RuntimeError, "psycopg2 is required"):
                analytics.load_organizations()

    def test_db_path_without_boto3_returns_500(self):
        with mock.patch.object(analytics, "boto3", None), \
                mock.patch.object(analytics.traceback, "print_exc"):
            resp = analytics.handle_request({}, today=TODAY)
        self.assertEqual(resp["statusCode"], 500)
        self.psycopg2.connect.assert_not_called()

    def test_validation_still_400_on_db_path(self):
        resp = analytics.handle_request({"type_start_date": "2026-01-01"}, today=TODAY)
        self.assertEqual(resp["statusCode"], 400)
        self.psycopg2.connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
