"""Conformance checker for issue #336 (Growth & Location Analytics API).

Not tied to any one PR's implementation. Point it at any lambda_handler and
it reports which spec rules pass, including the team lead's rulings from
the #336 WhatsApp thread (2026-09-21):
  - supplying only one of a start/end date pair is a 400, not a partial result
  - "1Y" means trailing 12 calendar months
  - country.csv/state.csv must be internally consistent (the shipped fixture
    has all US states pointing at Afghanistan's country_id; build your own
    correct CSVs for local testing, per the lead)

Usage as a library:
    from tests.growth_location_conformance import conformance, fixtures

    def call(event):
        result = my_lambda_handler(event, None)
        body = result["body"]
        if isinstance(body, str):
            body = json.loads(body)
        return result["statusCode"], body

    report = conformance.run_conformance(call, mock_dir="/tmp/my_mock_data")
    conformance.print_report(report)

Usage from the command line, against any implementation file:
    python -m tests.growth_location_conformance.conformance \\
        --impl path/to/lambda_function.py --entry lambda_handler

The target's data directory is set via the MOCK_DATA_DIR environment
variable AND written to <impl_dir>/mock_data, to cover both conventions
seen across the open #336 PRs (some read MOCK_DATA_DIR, some hardcode a
"mock_data" folder next to the handler file).
"""
import argparse
import importlib.util
import json
import os
import sys
from datetime import datetime, timezone

from . import fixtures
from . import oracle as oracle_mod


def run_conformance(call, mock_dir, now=None, on_write_fixtures=None):
    """Runs every rule against `call` and returns {rule_id: (status, detail)}.

    call: Callable[[dict], tuple[int, dict]] -- your adapter, event in,
        (status_code, body_dict) out.
    mock_dir: directory the target implementation reads its CSVs from.
    on_write_fixtures: optional callback(countries, states, orgs, encoder)
        invoked whenever fixtures are (re)written, e.g. to also mirror them
        into a second directory for implementations with a fixed data path.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    results = {}

    def record(rule_id, status, detail=""):
        results[rule_id] = (status, detail)

    def write(encoder=None):
        countries, states, orgs = fixtures.build(now)
        fixtures.write_csvs(mock_dir, countries, states, orgs, collab_encoder=encoder)
        if on_write_fixtures:
            on_write_fixtures(countries, states, orgs, encoder)
        return countries, states, orgs

    countries, states, orgs = write()
    oracle = oracle_mod.compute_all_buckets(countries, states, orgs, now)

    # ---- baseline call: structural + value checks vs the oracle ----
    try:
        status, body = call({})
    except Exception as exc:  # noqa: BLE001
        status, body = None, {"__exception__": f"{type(exc).__name__}: {exc}"}

    if status != 200 or "__exception__" in body:
        record("R1 top-level keys", "ERROR", body.get("__exception__", f"status={status}"))
        for r in ["R2 bucket shape", "R3 growth_trend shape",
                  "R4 total_organizations = all-time cumulative",
                  "R5 collaborators = window-scoped",
                  "R6 sparse arrays (no empty periods)",
                  "R7 location: top-4, no Other/pct"]:
            record(r, "SKIP")
    else:
        expected_keys = {"7D", "30D", "1Y", "All", "Custom"}
        got_keys = set(body.keys())
        record("R1 top-level keys", "PASS" if got_keys == expected_keys else "FAIL",
               f"got {sorted(got_keys)}")

        bucket_shape_ok = all(
            set(body.get(b, {}).keys()) == {"growth_trend", "organizations_by_location"}
            for b in ["7D", "30D", "1Y", "All"] if b in body
        )
        record("R2 bucket shape", "PASS" if bucket_shape_ok else "FAIL")

        gt_shape_ok = all(
            set(body[b]["growth_trend"].keys()) == {"total_organizations", "collaborators"}
            for b in ["7D", "30D", "1Y", "All"] if b in body
        )
        record("R3 growth_trend shape", "PASS" if gt_shape_ok else "FAIL")

        grand_total = len(orgs)
        try:
            d_7d = body["7D"]["growth_trend"]["total_organizations"]
            last_7d = d_7d[-1]["count"] if d_7d else None
            record("R4 total_organizations = all-time cumulative",
                   "PASS" if last_7d == grand_total else "FAIL",
                   f"7D last count={last_7d}, expected grand total={grand_total}")
        except Exception as exc:  # noqa: BLE001
            record("R4 total_organizations = all-time cumulative", "ERROR", str(exc))

        try:
            oracle_7d = sum(x["count"] for x in oracle["7D"]["growth_trend"]["collaborators"])
            impl_7d = sum(x["count"] for x in body["7D"]["growth_trend"]["collaborators"])
            record("R5 collaborators = window-scoped",
                   "PASS" if impl_7d == oracle_7d else "FAIL",
                   f"got {impl_7d}, oracle {oracle_7d}")
        except Exception as exc:  # noqa: BLE001
            record("R5 collaborators = window-scoped", "ERROR", str(exc))

        try:
            all_periods = {x["period"] for x in body["All"]["growth_trend"]["collaborators"]}
            oracle_periods = {x["period"] for x in oracle["All"]["growth_trend"]["collaborators"]}
            extra = all_periods - oracle_periods
            record("R6 sparse arrays (no empty periods)",
                   "PASS" if not extra else "FAIL",
                   f"unexpected periods: {sorted(extra)}" if extra else "")
        except Exception as exc:  # noqa: BLE001
            record("R6 sparse arrays (no empty periods)", "ERROR", str(exc))

        try:
            loc = body["All"]["organizations_by_location"]
            keys_ok = all(set(x.keys()) == {"country", "count"} for x in loc)
            sorted_ok = [x["count"] for x in loc] == sorted((x["count"] for x in loc), reverse=True)
            count_ok = len(loc) <= 4
            record("R7 location: top-4, no Other/pct",
                   "PASS" if (keys_ok and sorted_ok and count_ok) else "FAIL",
                   f"n={len(loc)} keys_ok={keys_ok} sorted_ok={sorted_ok}")
        except Exception as exc:  # noqa: BLE001
            record("R7 location: top-4, no Other/pct", "ERROR", str(exc))

    # ---- lead's ruling: lone date param -> 400 ----
    try:
        status, _ = call({"start_date": "2026-01-01"})
        record("R8 lone date param -> 400 (lead's ruling)",
               "PASS" if status == 400 else "FAIL", f"status={status}")
    except Exception as exc:  # noqa: BLE001
        record("R8 lone date param -> 400 (lead's ruling)", "ERROR", str(exc))

    try:
        status, _ = call({"start_date": "not-a-date", "end_date": "2026-06-30"})
        record("R9 malformed date -> 400", "PASS" if status == 400 else "FAIL", f"status={status}")
    except Exception as exc:  # noqa: BLE001
        record("R9 malformed date -> 400", "ERROR", str(exc))

    try:
        status, _ = call({"start_date": "2026-06-30", "end_date": "2026-01-01"})
        record("R10 start > end -> 400", "PASS" if status == 400 else "FAIL", f"status={status}")
    except Exception as exc:  # noqa: BLE001
        record("R10 start > end -> 400", "ERROR", str(exc))

    # ---- is_collaborator encoding robustness ----
    encodings = {
        "true/false": lambda b: "true" if b else "false",
        "1/0": lambda b: "1" if b else "0",
        "TRUE/FALSE": lambda b: "TRUE" if b else "FALSE",
        "Y/N": lambda b: "Y" if b else "N",
    }
    grand_total_collab = sum(1 for o in orgs if o[3])
    for enc_name, encoder in encodings.items():
        write(encoder=encoder)
        try:
            status, body = call({})
            if status != 200:
                record(f"R11 is_collaborator '{enc_name}'", "ERROR (rejected)", f"status={status}")
                continue
            total = sum(x["count"] for x in body["All"]["growth_trend"]["collaborators"])
            if total == grand_total_collab:
                record(f"R11 is_collaborator '{enc_name}'", "PASS")
            elif total == 0:
                record(f"R11 is_collaborator '{enc_name}'", "FAIL",
                       f"SILENT ZERO (expected {grand_total_collab}, got 0)")
            else:
                record(f"R11 is_collaborator '{enc_name}'", "FAIL",
                       f"expected {grand_total_collab}, got {total}")
        except Exception as exc:  # noqa: BLE001
            record(f"R11 is_collaborator '{enc_name}'", "ERROR", str(exc))

    write()  # restore canonical true/false fixture

    # ---- response body must be a JSON string (API Gateway proxy contract) ----
    # Only meaningful for adapters exposing the raw handler; library callers
    # of run_conformance() that already unwrap JSON should treat R12 as N/A.
    record("R12 response body is JSON string", "SEE ADAPTER",
           "This rule must be checked on the raw handler return value, "
           "not through the (status, body) adapter -- see README.")

    try:
        status, body = call({})
        labels = [x["period"] for x in body["1Y"]["growth_trend"]["total_organizations"]]
        record("INFO 1Y period labels", f"n={len(labels)}",
               f"{labels[0]}..{labels[-1]}" if labels else "(empty)")
    except Exception as exc:  # noqa: BLE001
        record("INFO 1Y period labels", "ERROR", str(exc))

    return results


def print_report(results, target_name="target"):
    rule_w = max(len(r) for r in results) + 2
    print(f"\nConformance report for {target_name}\n")
    for rule_id, (status, detail) in results.items():
        line = f"{rule_id:<{rule_w}}{status}"
        if detail:
            line += f"  -- {detail}"
        print(line)


def _load_module(impl_path, entry_name):
    impl_path = os.path.abspath(impl_path)
    impl_dir = os.path.dirname(impl_path)
    if impl_dir not in sys.path:
        sys.path.insert(0, impl_dir)  # mirrors the Lambda zip-root import model

    spec = importlib.util.spec_from_file_location("_conformance_target", impl_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["_conformance_target"] = module
    spec.loader.exec_module(module)
    return getattr(module, entry_name), impl_dir


def _make_adapter(handler_fn):
    def call(event):
        result = handler_fn(event, None)
        body = result["body"]
        if isinstance(body, str):
            body = json.loads(body)
        return result["statusCode"], body
    return call


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--impl", required=True, help="Path to the lambda_handler's source file")
    parser.add_argument("--entry", default="lambda_handler", help="Entry point function name")
    parser.add_argument("--mock-dir", default=None,
                         help="Directory to write mock CSVs to (default: <impl-dir>/mock_data)")
    args = parser.parse_args()

    handler_fn, impl_dir = _load_module(args.impl, args.entry)
    mock_dir = args.mock_dir or os.path.join(impl_dir, "mock_data")
    os.environ["MOCK_DATA_DIR"] = mock_dir

    call = _make_adapter(handler_fn)
    results = run_conformance(call, mock_dir=mock_dir)
    print_report(results, target_name=f"{args.impl}::{args.entry}")

    # R12 checked directly against the raw handler, since run_conformance's
    # adapter contract already unwraps JSON.
    raw = handler_fn({}, None)
    body_is_str = isinstance(raw["body"], str)
    print(f"\n{'R12 response body is JSON string':<40}{'PASS' if body_is_str else 'FAIL'}"
          + ("" if body_is_str else f"  -- body is {type(raw['body']).__name__}, not str"))


if __name__ == "__main__":
    main()
