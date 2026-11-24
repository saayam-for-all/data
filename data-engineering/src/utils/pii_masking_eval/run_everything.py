"""Fill in the missing Comprehend row for issue #585, on two test sets.

  python run_everything.py                 # runs Comprehend + scores everything
  python run_everything.py --no-aws        # local approaches only, no AWS calls

Needs boto3 and credentials allowed to call comprehend:DetectPiiEntities.
144 texts, about 432 Comprehend units. Free tier is 50,000 units/month.
"""
import importlib.util, json, os, sys, time, statistics

HERE = os.path.dirname(os.path.abspath(__file__))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, name + ".py"))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

D, E, C = load("detectors"), load("run_eval"), load("comprehend_pii")
THEIRS = load("testset"); MINE = load("indep_testset")

SETS = {
    "theirs (84, author-written)": THEIRS.DEV + THEIRS.HELDOUT,
    "independent (60, new)":       MINE.ITEMS,
}

toks = D.load_name_lookup(os.path.join(HERE, "users.csv"))
rx = D.build_lookup_regex(toks)

def timing(items, fn, loops=200):
    per = []
    for t, _ in items:
        a = time.perf_counter()
        for _ in range(loops): fn(t)
        per.append((time.perf_counter() - a) / loops * 1e6)
    per.sort()
    return f"{statistics.mean(per):7.1f} us"

# ---------------------------------------------------------------- Comprehend
comp = {}
lat = []
if "--no-aws" not in sys.argv:
    import boto3
    region = os.environ.get("AWS_REGION", "us-east-1")
    client = boto3.client("comprehend", region_name=region)
    texts = [t for items in SETS.values() for t, _ in items]
    print(f"Calling Comprehend on {len(texts)} texts in {region} ...", flush=True)
    for i, t in enumerate(texts, 1):
        a = time.perf_counter()
        comp[t] = [list(s) for s in C.comprehend_spans(t, client)]
        lat.append((time.perf_counter() - a) * 1000)
        if i % 25 == 0: print(f"  {i}/{len(texts)}", flush=True)
    lat.sort()
    print(f"Comprehend: {len(lat)} calls, mean {statistics.mean(lat):.0f} ms, "
          f"p95 {lat[int(.95*(len(lat)-1))]:.0f} ms\n")
    json.dump(comp, open(os.path.join(HERE, "comprehend_spans.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

APPROACHES = {
    "1 patterns only":          D.detect_patterns,
    "2 patterns + users lookup": lambda t: D.detect_patterns_lookup(t, rx),
    "4 layered (proposed)":     lambda t: D.detect_layered(t, rx),
}
if comp:
    APPROACHES["3 patterns + Comprehend"] = lambda t: D.merge(
        D.detect_patterns(t) + [tuple(x) for x in comp.get(t, [])])
    APPROACHES["3+4 Comprehend + layered"] = lambda t: D.merge(
        D.detect_layered(t, rx) + [tuple(x) for x in comp.get(t, [])])

report = {}
for set_name, items in SETS.items():
    n_pii = sum(1 for _, g in items if g); n_clean = len(items) - n_pii
    print(f"=== {set_name}: {n_pii} with PII, {n_clean} clean ===")
    print(f"{'approach':28s} {'caught':>9s} {'partial':>8s} {'missed':>7s} {'span recall':>13s} {'FP clean':>9s} {'spurious':>9s}  time")
    report[set_name] = {}
    for name, fn in APPROACHES.items():
        r, detail = E.score(items, fn)
        t = "    (API)" if name.startswith("3 ") or name.startswith("3+") else timing(items, fn)
        print(f"{name:28s} {r['caught']:4d}/{r['pii_items']:<4d} {r['partial']:8d} {r['missed']:7d} "
              f"{r['spans_hit']:5d}/{r['spans_gold']:<3d} ({100*r['spans_hit']//max(1,r['spans_gold']):3d}%) "
              f"{r['fp_clean']:4d}/{r['clean_items']:<4d} {r['spurious_spans_on_pii']:9d}  {t}")
        report[set_name][name] = r
        if detail:
            report[set_name][name]["_detail"] = [[k, txt, ex] for k, txt, ex in detail]
    print()

json.dump({"comprehend_latency_ms": {"mean": statistics.mean(lat), "p95": lat[int(.95*(len(lat)-1))]} if lat else None,
           "results": report}, open(os.path.join(HERE, "results.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("wrote results.json" + (" and comprehend_spans.json" if comp else ""))
