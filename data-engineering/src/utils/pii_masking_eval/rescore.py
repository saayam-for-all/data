import json, importlib.util

def load(n):
    s = importlib.util.spec_from_file_location(n, n + '.py')
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m

D, E, T, M = load('detectors'), load('run_eval'), load('testset'), load('indep_testset')
comp = json.load(open('comprehend_spans.json'))
rx = D.build_lookup_regex(D.load_name_lookup('users.csv'))

SETS = {'theirs (84)': T.DEV + T.HELDOUT, 'independent (60)': M.ITEMS}
FILTERS = {
    'all types': None,
    'drop DATE_TIME+AGE': {'DATE_TIME', 'AGE'},
    'drop DATE_TIME+AGE+ADDRESS': {'DATE_TIME', 'AGE', 'ADDRESS'},
}

def make(base, drop):
    def fn(t):
        extra = [tuple(x) for x in comp.get(t, []) if not drop or x[2] not in drop]
        return D.merge(base(t) + extra)
    return fn

patterns = D.detect_patterns
layered = lambda t: D.detect_layered(t, rx)

for sname, items in SETS.items():
    print('=== ' + sname + ' ===')
    print('%-44s %9s %14s %9s %9s' % ('variant', 'caught', 'span recall', 'FP clean', 'spurious'))
    for fname, drop in FILTERS.items():
        for base, label in ((patterns, 'patterns'), (layered, 'layered')):
            r, _ = E.score(items, make(base, drop))
            pct = 100 * r['spans_hit'] // max(1, r['spans_gold'])
            print('%-44s %4d/%-4d %6d/%-3d (%3d%%) %4d/%-4d %9d' % (
                label + ' + Comprehend, ' + fname,
                r['caught'], r['pii_items'], r['spans_hit'], r['spans_gold'], pct,
                r['fp_clean'], r['clean_items'], r['spurious_spans_on_pii']))
    print()
