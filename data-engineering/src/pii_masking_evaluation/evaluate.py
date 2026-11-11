"""Run every approach on the labelled test set and write the results (#585).

    python evaluate.py                      # approaches 1, 2, 4 (+3 if a Comprehend cache exists)
    python evaluate.py --comprehend live    # also call Amazon Comprehend (needs AWS credentials
                                            # with comprehend:DetectPiiEntities) and save a cache
    python evaluate.py --comprehend off     # skip approach 3

Writes results/results.json and results/results.md (results_holdout.* with --set holdout).

How an answer is scored, per approach:
  * Every whole-word occurrence of a labelled detail in the subject or the
    description is one detail. (An occurrence inside a longer labelled detail,
    like "Grace" inside "Grace Thompson", only counts once, as the longer one.)
  * caught   every letter and digit of it is redacted
    partial  some of it is redacted, some is left (counted as a miss: the rest leaks)
    missed   none of it is redacted
  * wrongly redacted clean text: a text with no personal details where the
    approach redacted anything.
  * false-positive redactions: redacted pieces that don't touch any labelled
    detail, in all 70 texts.
"""

import argparse
import json
import math
import os
import re
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from detectors import (FIELDS, ComprehendDetector, Improved, NameIndex, Patterns,  # noqa: E402
                       PatternsComprehend, PatternsUsers, merge_spans, redact)

REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
DEFAULT_USERS = os.path.join(REPO_ROOT, "data-analytics", "sql", "users.csv")
MOCK_USERS = os.path.join(HERE, "data", "mock_users.csv")
SETS = {"main": os.path.join(HERE, "data", "test_set.jsonl"),
        "holdout": os.path.join(HERE, "data", "holdout_set.jsonl")}
CACHE = os.path.join(HERE, "results", "comprehend_responses.json")
OUT_DIR = os.path.join(HERE, "results")

COMPREHEND_PRICE_PER_UNIT = 0.0001   # DetectPiiEntities, USD per 100 characters
COMPREHEND_MIN_UNITS = 3             # minimum charge per request
TYPES = ["NAME", "PHONE", "EMAIL", "ADDRESS", "ID", "CARD", "URL"]


def load_items(path=SETS["main"]):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def gold_occurrences(item):
    """[(field, start, end, entity)] for every labelled occurrence."""
    occ = []
    for field in FIELDS:
        text = item[field] or ""
        found = []
        for ent in item["pii"]:
            pattern = r"(?<!\w)" + re.escape(ent["text"]) + r"(?!\w)"
            for m in re.finditer(pattern, text):
                found.append((m.start(), m.end(), ent))
        for s, e, ent in found:
            nested = any(s2 <= s and e <= e2 and (e2 - s2) > (e - s) for s2, e2, _ in found)
            if not nested:
                occ.append((field, s, e, ent))
    return occ


def coverage(text, start, end, spans):
    chars = [i for i in range(start, end) if text[i].isalnum()]
    covered = [i for i in chars if any(s <= i < e for s, e, _ in spans)]
    if len(covered) == len(chars):
        return "caught"
    return "partial" if covered else "missed"


def score(items, approach):
    per_type = {t: {"caught": 0, "partial": 0, "missed": 0} for t in TYPES}
    rows, fp_spans, clean_flagged, pii_fully_clean = [], 0, [], 0
    names_registered = {"caught": 0, "total": 0}
    names_unregistered = {"caught": 0, "total": 0}
    for item in items:
        spans = approach.detect(item)
        spans = {f: merge_spans(spans[f]) for f in FIELDS}
        gold = gold_occurrences(item)
        results = []
        for field, s, e, ent in gold:
            res = coverage(item[field], s, e, spans[field])
            per_type[ent["type"]][res] += 1
            results.append((ent["text"], ent["type"], res))
            if ent["type"] == "NAME":
                bucket = names_registered if ent.get("registered") else names_unregistered
                bucket["total"] += 1
                bucket["caught"] += res == "caught"
        for field in FIELDS:
            for s, e, label in spans[field]:
                if not any(f == field and s < ge and gs < e for f, gs, ge, _ in gold):
                    fp_spans += 1
        any_redaction = any(spans[f] for f in FIELDS)
        if not item["has_pii"] and any_redaction:
            clean_flagged.append(item["id"])
        if item["has_pii"] and all(r[2] == "caught" for r in results):
            pii_fully_clean += 1
        rows.append({
            "id": item["id"],
            "subject": redact(item["subject"], spans["subject"]),
            "description": redact(item["description"], spans["description"]),
            "details": results,
        })
    totals = {k: sum(per_type[t][k] for t in TYPES) for k in ("caught", "partial", "missed")}
    return {
        "per_type": per_type, "totals": totals, "false_positive_redactions": fp_spans,
        "clean_texts_wrongly_redacted": clean_flagged,
        "pii_texts_fully_cleaned": pii_fully_clean,
        "names_registered": names_registered, "names_unregistered": names_unregistered,
        "rows": rows,
    }


def time_approach(items, approach, repeats):
    runs = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        for item in items:
            approach.detect(item)
        runs.append(time.perf_counter() - t0)
    per_text_ms = statistics.median(runs) / len(items) * 1000
    return {"ms_per_request": round(per_text_ms, 4), "repeats": repeats}


def comprehend_cost(items):
    units = [max(COMPREHEND_MIN_UNITS, math.ceil(len(i["subject"] + "\n" + i["description"]) / 100))
             for i in items]
    avg_units = sum(units) / len(units)
    avg_chars = sum(len(i["subject"] + "\n" + i["description"]) for i in items) / len(items)
    per_request = avg_units * COMPREHEND_PRICE_PER_UNIT
    return {"avg_chars": round(avg_chars, 1), "avg_units": round(avg_units, 2),
            "usd_per_request": per_request,
            "monthly": {str(v): round(v * per_request, 2) for v in (1000, 10000, 100000)}}


def pct(a, b):
    return f"{(100 * a / b):.0f}%" if b else "-"


def write_markdown(res, path):
    L = []
    ap = res["approaches"]
    L.append(f"Test set: {res['n_items']} requests, {res['n_pii_items']} with personal details, "
             f"{res['n_clean_items']} without. {res['n_details']} labelled details.\n")
    L.append("| Approach | Caught | Partly caught | Missed | PII texts fully cleaned | "
             "Clean texts wrongly redacted | False-positive redactions | Time per request |")
    L.append("|---|---|---|---|---|---|---|---|")
    for k, a in ap.items():
        if a.get("skipped"):
            L.append(f"| {k}. {a['title']} | not run: {a['skipped']} | | | | | | |")
            continue
        t, n = a["totals"], res["n_details"]
        L.append(f"| {k}. {a['title']} | {t['caught']} ({pct(t['caught'], n)}) | {t['partial']} | "
                 f"{t['missed']} | {a['pii_texts_fully_cleaned']} / {res['n_pii_items']} | "
                 f"{len(a['clean_texts_wrongly_redacted'])} / {res['n_clean_items']} | "
                 f"{a['false_positive_redactions']} | {a['timing']} |")
    L.append("\nCaught per type (caught / total):\n")
    L.append("| Approach | " + " | ".join(TYPES) + " | Names of users | Names of non-users |")
    L.append("|---|" + "---|" * (len(TYPES) + 2))
    for k, a in ap.items():
        if a.get("skipped"):
            continue
        cells = []
        for t in TYPES:
            d = a["per_type"][t]
            cells.append(f"{d['caught']}/{d['caught'] + d['partial'] + d['missed']}")
        nr, nu = a["names_registered"], a["names_unregistered"]
        cells += [f"{nr['caught']}/{nr['total']}", f"{nu['caught']}/{nu['total']}"]
        L.append(f"| {k} | " + " | ".join(cells) + " |")
    L.append("\nClean texts wrongly redacted:\n")
    for k, a in ap.items():
        if not a.get("skipped"):
            L.append(f"- **{k}**: {', '.join(a['clean_texts_wrongly_redacted']) or 'none'}")
    c = res["comprehend_cost"]
    L.append(f"\nComprehend cost: average request {c['avg_chars']} characters = {c['avg_units']} units "
             f"(minimum 3) = ${c['usd_per_request']:.5f} per request. "
             + ", ".join(f"{int(k):,} requests/month = ${v}" for k, v in c["monthly"].items()) + ".")
    L.append(f"\nName lookup: {res['name_index_parts']} name parts, built in {res['name_index_ms']} ms.")
    L.append("\n## Redacted output per request\n")
    for idx, item_id in enumerate(r["id"] for r in next(a for a in ap.values()
                                                            if not a.get("skipped"))["rows"]):
        L.append(f"<details><summary>{item_id}</summary>\n")
        for k, a in ap.items():
            if a.get("skipped"):
                continue
            row = a["rows"][idx]
            misses = [f"{d[0]} ({d[2]})" for d in row["details"] if d[2] != "caught"]
            L.append(f"- **{k}** `{row['subject']}` / `{row['description']}`"
                     + (f"  \n  not caught: {', '.join(misses)}" if misses else ""))
        L.append("\n</details>\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--comprehend", choices=("auto", "live", "cache", "off"), default="auto")
    ap.add_argument("--region", default="us-east-1")
    ap.add_argument("--users", default=DEFAULT_USERS,
                    help="users table export (first_name, middle_name, last_name)")
    ap.add_argument("--repeats", type=int, default=200)
    ap.add_argument("--set", choices=sorted(SETS), default="main",
                    help="main = the 70-request test set, holdout = 24 requests written "
                         "after approach 4 and never used to tune it")
    args = ap.parse_args(argv)

    items = load_items(SETS[args.set])
    suffix = "" if args.set == "main" else "_" + args.set
    t0 = time.perf_counter()
    names = NameIndex.from_csv(args.users, MOCK_USERS)
    index_ms = round((time.perf_counter() - t0) * 1000, 2)

    approaches = [Patterns(), PatternsUsers(names)]
    comprehend = None
    mode = args.comprehend
    if mode == "auto":
        mode = "cache" if os.path.exists(CACHE) else "off"
    if mode != "off":
        comprehend = ComprehendDetector(mode=mode, cache_path=CACHE, region=args.region)
    approaches.append(PatternsComprehend(comprehend) if comprehend else None)
    approaches.append(Improved(names))

    out = {"n_items": len(items), "n_pii_items": sum(i["has_pii"] for i in items),
           "n_clean_items": sum(not i["has_pii"] for i in items),
           "n_details": sum(len(gold_occurrences(i)) for i in items),
           "name_index_parts": len(names), "name_index_ms": index_ms,
           "comprehend_cost": comprehend_cost(items), "approaches": {}}
    for key, appr in zip("1234", approaches):
        if appr is None:
            out["approaches"][key] = {"title": PatternsComprehend.title,
                                      "skipped": "no AWS access yet (run with --comprehend live)"}
            continue
        result = score(items, appr)
        if isinstance(appr, PatternsComprehend):
            meta_key = "_meta_" + args.set
            lat = comprehend.call_seconds or comprehend.cache.get(meta_key, {}).get("call_seconds", [])
            if comprehend.mode == "live":
                comprehend.cache[meta_key] = {"call_seconds": comprehend.call_seconds,
                                              "region": args.region}
                comprehend.save()
            local = time_approach(items, Patterns(), args.repeats)["ms_per_request"]
            api_ms = statistics.median(lat) * 1000 if lat else None
            result["timing"] = (f"{api_ms:.0f} ms (API call, median)" if api_ms
                                else "API latency not recorded")
            result["timing_detail"] = {"api_ms_median": api_ms, "local_ms": local}
        else:
            t = time_approach(items, appr, args.repeats)
            result["timing"] = f"{t['ms_per_request']:.3f} ms"
            result["timing_detail"] = t
        result["title"] = appr.title
        out["approaches"][key] = result

    os.makedirs(OUT_DIR, exist_ok=True)
    out["test_set"] = args.set
    with open(os.path.join(OUT_DIR, f"results{suffix}.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    write_markdown(out, os.path.join(OUT_DIR, f"results{suffix}.md"))

    for key, a in out["approaches"].items():
        if a.get("skipped"):
            print(f"{key}. {a['title']}: not run ({a['skipped']})")
            continue
        t = a["totals"]
        print(f"{key}. {a['title']}: caught {t['caught']}/{out['n_details']}, partial {t['partial']}, "
              f"missed {t['missed']}, clean wrongly redacted "
              f"{len(a['clean_texts_wrongly_redacted'])}/{out['n_clean_items']}, "
              f"FP redactions {a['false_positive_redactions']}, {a['timing']}")


if __name__ == "__main__":
    main()
