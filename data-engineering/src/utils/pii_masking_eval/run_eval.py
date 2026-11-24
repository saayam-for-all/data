"""Score PII approaches on the labelled test set.

usage: python3 -I run_eval.py <users.csv> <out_dir> [comprehend_spans.json]
"""
import importlib.util
import json
import os
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if hasattr(sys.stdout, "reconfigure"):          # Windows consoles default to cp1252
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


D = load("detectors")
T = load("testset")


def locate(text, sub):
    i = text.find(sub)
    assert i >= 0, (text, sub)
    return i, i + len(sub)


def coverage(gold, spans):
    gs, ge = gold
    covered = 0
    for s, e, _ in spans:
        covered += max(0, min(e, ge) - max(s, gs))
    return covered / max(1, ge - gs)


def score(items, predict):
    r = dict(n=len(items), pii_items=0, clean_items=0, caught=0, partial=0, missed=0,
             fp_clean=0, spans_gold=0, spans_hit=0, spurious_spans_on_pii=0)
    detail = []
    for text, gold in items:
        spans = predict(text)
        if not gold:
            r["clean_items"] += 1
            if spans:
                r["fp_clean"] += 1
                detail.append(("FALSE_POSITIVE", text, [text[s:e] for s, e, _ in spans]))
            continue
        r["pii_items"] += 1
        hits = []
        for sub, typ in gold:
            g = locate(text, sub)
            hit = coverage(g, spans) >= 0.8
            hits.append(hit)
            r["spans_gold"] += 1
            r["spans_hit"] += hit
        if all(hits):
            r["caught"] += 1
        elif any(hits):
            r["partial"] += 1
            detail.append(("PARTIAL", text, [g[0] for g, h in zip(gold, hits) if not h]))
        else:
            r["missed"] += 1
            detail.append(("MISSED", text, [g[0] for g in gold]))
        golds = [locate(text, sub) for sub, _ in gold]
        for s, e, _ in spans:
            if not any(min(e, ge) > max(s, gs) for gs, ge in golds):
                r["spurious_spans_on_pii"] += 1
                detail.append(("SPURIOUS_SPAN", text, [text[s:e]]))
    return r, detail


def timing(items, predict, loops=300):
    texts = [t for t, _ in items]
    per = []
    for t in texts:
        best = []
        for _ in range(loops):
            a = time.perf_counter()
            predict(t)
            best.append(time.perf_counter() - a)
        per.append(statistics.mean(best))
    per_us = sorted(x * 1e6 for x in per)
    return dict(mean_us=round(statistics.mean(per_us), 1),
                p95_us=round(per_us[int(0.95 * (len(per_us) - 1))], 1),
                max_us=round(per_us[-1], 1))


def main():
    users_csv, out_dir = sys.argv[1], sys.argv[2]
    ext = sys.argv[3] if len(sys.argv) > 3 else None
    os.makedirs(out_dir, exist_ok=True)

    t0 = time.perf_counter()
    toks = D.load_name_lookup(users_csv)
    rx = D.build_lookup_regex(toks)
    init_ms = (time.perf_counter() - t0) * 1000

    approaches = {
        "1_patterns_only": D.detect_patterns,
        "2_patterns_users_lookup": lambda t: D.detect_patterns_lookup(t, rx),
        "4_layered_no_deps": lambda t: D.detect_layered(t, rx),
    }
    if ext:
        with open(ext, encoding="utf-8") as f:
            ext_spans = json.load(f)
        approaches["3_patterns_comprehend"] = lambda t: D.merge(
            D.detect_patterns(t) + [tuple(x) for x in ext_spans.get(t, [])])

    sets = {"dev": T.DEV, "heldout": T.HELDOUT, "all": T.DEV + T.HELDOUT}
    results = {"lookup_tokens": len(toks), "lookup_init_ms": round(init_ms, 1),
               "counts": {k: dict(items=len(v), clean=sum(1 for _, g in v if not g)) for k, v in sets.items()}}
    for name, fn in approaches.items():
        results[name] = {}
        for sname, items in sets.items():
            r, detail = score(items, fn)
            results[name][sname] = r
            if sname == "all":
                with open(os.path.join(out_dir, f"details_{name}.txt"), "w", encoding="utf-8") as f:
                    for kind, text, extra in detail:
                        f.write(f"{kind}\t{text}\t{extra}\n")
        if not name.startswith("3_"):
            results[name]["timing"] = timing(sets["all"], fn)
    with open(os.path.join(out_dir, "results.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=1)

    # dump a redacted sample and spans for each local approach
    samples = []
    for text, gold in sets["all"]:
        samples.append(dict(text=text, gold=[g[0] for g in gold],
                            **{n: D.redact(text, f(text)) for n, f in approaches.items()}))
    with open(os.path.join(out_dir, "redacted_samples.json"), "w", encoding="utf-8") as f:
        json.dump(samples, f, indent=1, ensure_ascii=False)

    for name in approaches:
        for sname in ("dev", "heldout", "all"):
            r = results[name][sname]
            print(f"{name:26s} {sname:8s} caught {r['caught']:2d}/{r['pii_items']:2d}  partial {r['partial']:2d}  "
                  f"missed {r['missed']:2d}  span-recall {r['spans_hit']}/{r['spans_gold']}  "
                  f"FP-clean {r['fp_clean']}/{r['clean_items']}  spurious-on-pii {r['spurious_spans_on_pii']}")
        if "timing" in results[name]:
            print("   timing(us/text)", results[name]["timing"])
    print("lookup tokens", len(toks), "init ms", round(init_ms, 1))


if __name__ == "__main__":
    main()
