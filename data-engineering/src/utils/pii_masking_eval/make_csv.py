"""Write testset_labelled.csv (id, split, has_pii, text, pii_spans) from testset.py."""
import csv
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("testset", os.path.join(HERE, "testset.py"))
T = importlib.util.module_from_spec(spec)
spec.loader.exec_module(T)

out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "testset_labelled.csv")
items = [("dev", t, g) for t, g in T.DEV] + [("heldout", t, g) for t, g in T.HELDOUT]

# utf-8-sig so Excel on Windows shows the Hindi/Korean names correctly
with open(out, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["id", "split", "has_pii", "text", "pii_spans(type:text)"])
    for n, (split, text, gold) in enumerate(items, 1):
        w.writerow([n, split, "yes" if gold else "no", text, " | ".join(f"{t}:{s}" for s, t in gold)])
print("wrote", out, "-", len(items), "rows")