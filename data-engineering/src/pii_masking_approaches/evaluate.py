"""Run every approach on the labelled test set and write results/.

    python evaluate.py                      # approaches 1, 2, 4 (+5 if spaCy is installed)
    python evaluate.py --comprehend         # also approach 3 (needs AWS credentials)
    python evaluate.py --set holdout        # holdout set (never used to tune approach 4)
    python evaluate.py --users path/to/users.csv

Scoring, per labelled detail:
  caught   every letter/digit of the detail is inside a redacted span
  partly   some of it is redacted (e.g. first name masked, surname left)
  missed   none of it is redacted
False positives:
  wrongly redacted clean texts  C-records with any redaction
  false-positive redactions     redacted spans that touch no labelled detail
"""

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from comprehend_adapter import ComprehendDetector, credentials_available, monthly_cost  # noqa: E402
from detectors import (improved_plus_spacy, improved_rules, pipeline_plus_lookup,  # noqa: E402
                       redact, spacy_available)
from name_lookup import load_name_parts  # noqa: E402
from pipeline_patterns import pipeline_spans  # noqa: E402

REPO_ROOT = HERE.parents[2]
DEFAULT_USERS = [REPO_ROOT / "data-analytics" / "sql" / "users.csv", HERE / "data" / "mock_users.csv"]
TYPES = ["NAME", "PHONE", "EMAIL", "ADDRESS", "ID", "CARD", "URL", "DOB"]


def load_test_set(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _covered(text, spans, start, end):
    """Return (alnum chars covered, alnum chars total) for text[start:end]."""
    covered = total = 0
    for i in range(start, end):
        if text[i].isalnum():
            total += 1
            if any(s <= i < e for s, e, _ in spans):
                covered += 1
    return covered, total


def score(records, spans_by_id):
    per_label, fp_spans, clean_hit = [], 0, []
    for r in records:
        spans = spans_by_id[r["id"]]
        label_ranges = {"subj": [], "desc": []}
        for lab in r["pii"]:
            text = r[lab["field"]]
            start = text.find(lab["text"])
            end = start + len(lab["text"])
            label_ranges[lab["field"]].append((start, end))
            cov, tot = _covered(text, spans[lab["field"]], start, end)
            status = "caught" if cov == tot else ("partly" if cov else "missed")
            per_label.append({"id": r["id"], "type": lab["type"], "text": lab["text"], "status": status})
        any_span = False
        for field in ("subj", "desc"):
            for s, e, _ in spans[field]:
                any_span = True
                if not any(s < le and ls < e for ls, le in label_ranges[field]):
                    fp_spans += 1
        if not r["pii"] and any_span:
            clean_hit.append(r["id"])
    return per_label, fp_spans, clean_hit


def run(detector, records, name_parts, repeats):
    """Return spans per record and the mean milliseconds per request."""
    spans_by_id = {r["id"]: {f: detector(r[f], name_parts) for f in ("subj", "desc")} for r in records}
    timings = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        for r in records:
            detector(r["subj"], name_parts)
            detector(r["desc"], name_parts)
        timings.append((time.perf_counter() - t0) * 1000 / len(records))
    return spans_by_id, statistics.median(timings)


def summarise(name, records, spans_by_id, ms, extra=""):
    per_label, fp_spans, clean_hit = score(records, spans_by_id)
    n = len(per_label)
    counts = {k: sum(1 for p in per_label if p["status"] == k) for k in ("caught", "partly", "missed")}
    pii_records = [r for r in records if r["pii"]]
    fully = sum(1 for r in pii_records
                if all(p["status"] == "caught" for p in per_label if p["id"] == r["id"]))
    by_type = {}
    for t in TYPES:
        items = [p for p in per_label if p["type"] == t]
        if items:
            by_type[t] = f"{sum(p['status'] == 'caught' for p in items)}/{len(items)}"
    return {
        "approach": name, "labels": n, **counts,
        "caught_pct": round(100 * counts["caught"] / n, 1),
        "pii_requests_fully_cleaned": f"{fully}/{len(pii_records)}",
        "clean_requests_wrongly_redacted": f"{len(clean_hit)}/{len(records) - len(pii_records)}",
        "clean_ids_wrongly_redacted": clean_hit,
        "false_positive_redactions": fp_spans,
        "ms_per_request": round(ms, 4), "note": extra,
        "by_type": by_type,
        "not_fully_caught": [f"{p['id']} {p['type']} ({p['status']})" for p in per_label if p["status"] != "caught"],
    }


def write_markdown(path, results, records, outputs, meta):
    lines = [f"# Results: PII masking approaches (#585), {meta['set']} set\n",
             f"Test set: {meta['requests']} requests ({meta['with_pii']} with personal details, "
             f"{meta['clean']} without), {meta['labels']} labelled details. "
             f"Users-table names: {meta['name_parts']} name parts, loaded in {meta['lookup_ms']} ms.\n",
             "| Approach | Caught | Partly | Missed | PII requests fully cleaned | Clean requests wrongly redacted | False-positive redactions | Time per request |",
             "|---|---|---|---|---|---|---|---|"]
    for r in results:
        if r.get("skipped"):
            lines.append(f"| {r['approach']} | not run: {r['skipped']} | | | | | | |")
            continue
        lines.append(f"| {r['approach']} | {r['caught']} ({r['caught_pct']}%) | {r['partly']} | {r['missed']} | "
                     f"{r['pii_requests_fully_cleaned']} | {r['clean_requests_wrongly_redacted']} | "
                     f"{r['false_positive_redactions']} | {r['ms_per_request']} ms |")
    lines += ["", "## Caught per type", "",
              "| Approach | " + " | ".join(TYPES) + " |", "|---|" + "---|" * len(TYPES)]
    for r in results:
        if not r.get("skipped"):
            lines.append(f"| {r['approach']} | " + " | ".join(r["by_type"].get(t, "-") for t in TYPES) + " |")
    lines += ["", "## Not fully caught", ""]
    for r in results:
        if not r.get("skipped"):
            lines.append(f"- **{r['approach']}**: {', '.join(r['not_fully_caught']) or 'none'}")
    lines += ["", "## Clean requests wrongly redacted", ""]
    for r in results:
        if not r.get("skipped"):
            lines.append(f"- **{r['approach']}**: {', '.join(r['clean_ids_wrongly_redacted']) or 'none'}")
    lines += ["", "## Masked output per request", ""]
    for rec in records:
        lines.append(f"<details><summary>{rec['id']}</summary>\n")
        lines.append(f"- original: `{rec['subj']}` / `{rec['desc']}`")
        for name, out in outputs.items():
            lines.append(f"- {name}: `{out[rec['id']]['subj']}` / `{out[rec['id']]['desc']}`")
        lines.append("\n</details>\n")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--set", choices=["main", "holdout"], default="main",
                    help="main = data/test_set.jsonl, holdout = data/holdout_set.jsonl")
    ap.add_argument("--users", nargs="*", default=[str(p) for p in DEFAULT_USERS])
    ap.add_argument("--comprehend", action="store_true", help="call Amazon Comprehend (needs AWS credentials)")
    ap.add_argument("--region", default="us-east-1")
    ap.add_argument("--repeats", type=int, default=50)
    ap.add_argument("--out", default=str(HERE / "results"))
    args = ap.parse_args(argv)

    set_file = "test_set.jsonl" if args.set == "main" else "holdout_set.jsonl"
    suffix = "" if args.set == "main" else "_holdout"
    records = load_test_set(HERE / "data" / set_file)
    t0 = time.perf_counter()
    name_parts = load_name_parts(args.users)
    lookup_ms = round((time.perf_counter() - t0) * 1000, 1)

    approaches = [
        ("1. Pipeline patterns only", lambda t, n: pipeline_spans(t), None),
        ("2. Pipeline + users-table lookup", pipeline_plus_lookup, None),
        ("3. Pipeline + Amazon Comprehend", None, "comprehend"),
        ("4. Improved rules (patterns + users names + name cues)", improved_rules, None),
        ("5. Improved patterns + spaCy small model (reference)", improved_plus_spacy, "spacy"),
    ]

    results, outputs = [], {}
    comprehend = None
    for name, fn, needs in approaches:
        if needs == "comprehend":
            if not args.comprehend:
                results.append({"approach": name, "skipped": "no AWS access yet (run with --comprehend)"})
                continue
            if not credentials_available():
                results.append({"approach": name, "skipped": "no AWS credentials found"})
                continue
            comprehend = ComprehendDetector(region=args.region)
            fn = comprehend
            repeats = 1
        elif needs == "spacy":
            if not spacy_available():
                results.append({"approach": name, "skipped": "spaCy / en_core_web_sm not installed"})
                continue
            repeats = max(1, args.repeats // 10)
        else:
            repeats = args.repeats
        spans_by_id, ms = run(fn, records, name_parts, repeats)
        if comprehend is not None and fn is comprehend:
            comprehend.save_cache()
        results.append(summarise(name, records, spans_by_id, ms))
        outputs[name.split(".")[0]] = {
            rid: {f: redact(next(r for r in records if r["id"] == rid)[f], sp[f]) for f in ("subj", "desc")}
            for rid, sp in spans_by_id.items()}

    avg_chars = statistics.mean(len(r["subj"]) + len(r["desc"]) + 1 for r in records)
    cost = {}
    for volume in (1_000, 10_000, 100_000):
        paid, units = monthly_cost(volume, avg_chars)
        free_tier, _ = monthly_cost(volume, avg_chars, free_units=50_000)
        cost[volume] = {"units_per_request": units, "usd_per_month": paid, "usd_with_free_tier": free_tier}

    meta = {"set": args.set, "requests": len(records), "with_pii": sum(1 for r in records if r["pii"]),
            "clean": sum(1 for r in records if not r["pii"]),
            "labels": sum(len(r["pii"]) for r in records),
            "name_parts": len(name_parts), "lookup_ms": lookup_ms,
            "avg_chars_per_request": round(avg_chars, 1), "comprehend_cost": cost}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"results{suffix}.json").write_text(json.dumps({"meta": meta, "results": results}, indent=2, ensure_ascii=False),
                                      encoding="utf-8")
    write_markdown(out / f"results{suffix}.md", results, records, outputs, meta)

    for r in results:
        if r.get("skipped"):
            print(f"{r['approach']}: not run ({r['skipped']})")
        else:
            print(f"{r['approach']}: caught {r['caught']}/{r['labels']} ({r['caught_pct']}%), "
                  f"partly {r['partly']}, missed {r['missed']}, clean wrongly redacted "
                  f"{r['clean_requests_wrongly_redacted']}, FP redactions {r['false_positive_redactions']}, "
                  f"{r['ms_per_request']} ms/request")
    print(f"Comprehend cost (avg {meta['avg_chars_per_request']} chars/request): {cost}")
    return results


if __name__ == "__main__":
    main()
