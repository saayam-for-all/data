"""Tests for data-engineering/src/pii_masking_approaches (issue #585)."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / "src" / "pii_masking_approaches"
sys.path.insert(0, str(PKG))
sys.path.insert(0, str(PKG / "data"))

import build_test_set  # noqa: E402
import comprehend_adapter  # noqa: E402
import evaluate  # noqa: E402
from detectors import (improved_pattern_spans, improved_rules, lookup_spans_naive,  # noqa: E402
                       merge_spans, name_cue_spans, pipeline_plus_lookup, redact)
from name_lookup import load_name_parts  # noqa: E402
from pipeline_patterns import pipeline_spans  # noqa: E402

NAMES = {"maria", "gonzalez", "hope", "williams", "may", "lin", "wei", "zhang"}


def masked(fn, text, names=NAMES):
    return redact(text, fn(text, names))


def improved(text, names=NAMES):
    return redact(text, improved_rules(text, names))


class TestTestSet(unittest.TestCase):
    def setUp(self):
        self.main = build_test_set.build(build_test_set.RECORDS)
        self.holdout = build_test_set.build(build_test_set.HOLDOUT_RECORDS)

    def test_size_and_clean_share(self):
        self.assertGreaterEqual(len(self.main), 50)
        self.assertGreaterEqual(sum(1 for r in self.main if not r["pii"]), 15)

    def test_labels_are_substrings(self):
        for r in self.main + self.holdout:
            for lab in r["pii"]:
                self.assertIn(lab["text"], r[lab["field"]], r["id"])

    def test_covers_required_kinds(self):
        kinds = {lab["type"] for r in self.main for lab in r["pii"]}
        self.assertTrue({"NAME", "PHONE", "EMAIL", "ADDRESS"} <= kinds)
        texts = " ".join(lab["text"] for r in self.main for lab in r["pii"])
        self.assertIn("José Hernández", texts)          # non-English name
        self.assertIn("सुनीता शर्मा", texts)              # non-Latin script
        self.assertIn("five seven one", texts)          # spelled-out number

    def test_jsonl_files_match_builder(self):
        for name, records in (("test_set.jsonl", self.main), ("holdout_set.jsonl", self.holdout)):
            on_disk = evaluate.load_test_set(PKG / "data" / name)
            self.assertEqual(on_disk, records, f"{name} is stale: run data/build_test_set.py")

    def test_holdout_ids_do_not_overlap(self):
        self.assertFalse({r["id"] for r in self.main} & {r["id"] for r in self.holdout})


class TestPipelinePatterns(unittest.TestCase):
    def test_known_formats(self):
        text = "Call 571-555-0142 or mail a.b@example.com, SSN 123-45-6789"
        self.assertEqual(redact(text, pipeline_spans(text)), "Call [PHONE] or mail [EMAIL], SSN [SSN]")

    def test_names_untouched(self):
        self.assertEqual(pipeline_spans("My name is Priya Venkataraman"), [])


class TestNaiveLookup(unittest.TestCase):
    def test_matches_any_case(self):
        self.assertEqual(masked(pipeline_plus_lookup, "maria needs food"), "[NAME] needs food")

    def test_common_words_become_false_positives(self):
        # The weakness approach 4 fixes: "may" and "hope" are also names.
        spans = lookup_spans_naive("I hope we may get help", NAMES)
        self.assertEqual(len(spans), 2)


class TestImprovedPatterns(unittest.TestCase):
    def test_phone_formats(self):
        for phone in ["(703) 555 0198", "+1 202 555 0175", "703.555.0123", "+91 98450 12345",
                      "0412 345 678", "+44 7700 900123", "(571)555-0134", "7 0 3 5 5 5 0 1 6 6",
                      "9876543210"]:
            self.assertEqual(improved(f"call {phone} today"), "call [PHONE] today", phone)

    def test_numbers_that_are_not_phones(self):
        for text in ["sizes 8, 10 and 12", "quote was 300-400 dollars", "at 10:30 on 11/20",
                     "Order #45821", "paying $18.50/hour", "Reference number 2026 1104 5567 89"]:
            self.assertEqual(improved_pattern_spans(text), [], text)

    def test_spelled_out_number(self):
        self.assertEqual(improved("dial nine eight seven six five four three two one zero."),
                         "dial [PHONE].")
        self.assertEqual(improved_pattern_spans("a family of five"), [])

    def test_obfuscated_email(self):
        self.assertEqual(improved("Email: fatima dot alsayed at gmail dot com"), "Email: [EMAIL]")
        self.assertEqual(improved("mail wei.zhang [at] example [dot] com now"), "mail [EMAIL] now")

    def test_card_needs_valid_checksum(self):
        self.assertEqual(improved("Card 4111 1111 1111 1111 exp"), "Card [CARD] exp")
        self.assertEqual(improved_pattern_spans("Card 4111 1111 1111 1112 exp"), [])

    def test_addresses(self):
        self.assertEqual(improved("I live at 1428 Elm Street, Apt 3B, Reston"), "I live at [ADDRESS], Reston")
        self.assertEqual(improved("Deliver to Flat 12, 4 Park Road, Mumbai"), "Deliver to [ADDRESS], Mumbai")
        self.assertEqual(improved("I'm at 15 Rue de la Paix, call"), "I'm at [ADDRESS], call")
        self.assertEqual(improved_pattern_spans("The Main Street food bank on Route 7"), [])

    def test_id_and_dob(self):
        self.assertEqual(improved("My passport number is K1234567, thanks"), "My passport number is [ID], thanks")
        self.assertEqual(improved("Patient DOB 03/14/1958 here"), "Patient DOB [DOB] here")


class TestNameRules(unittest.TestCase):
    def test_cues(self):
        cases = {
            "Hi, my name is Priya Venkataraman and we need rice": "Hi, my name is [NAME] and we need rice",
            "My name is grace kim and I need help": "My name is [NAME] and I need help",
            "My son Mateo needs help": "My son [NAME] needs help",
            "Ask for Mr. Mehta.": "Ask for Mr. [NAME].",
            "Reach me (Aisha) on Monday": "Reach me ([NAME]) on Monday",
            "Text me. Thanks, Maria": "Text me. Thanks, [NAME]",
            "Me llamo José Hernández, mi": "Me llamo [NAME], mi",
            "Name: O. Adeyemi": "Name: [NAME]",
            "मेरा नाम सुनीता शर्मा है, I need": "मेरा नाम [NAME] है, I need",
        }
        for text, expected in cases.items():
            self.assertEqual(redact(text, name_cue_spans(text)), expected, text)

    def test_cues_ignore_ordinary_words(self):
        for text in ["I am short on rent", "I'm staying at my cousin's", "My grandmother needs care",
                     "Contact me at noon", "Call 9876543210 now"]:
            self.assertEqual(name_cue_spans(text), [], text)

    def test_common_word_names_only_next_to_a_name(self):
        self.assertEqual(improved("I hope we may get help in May"), "I hope we may get help in May")
        self.assertEqual(improved("Hope Williams here"), "[NAME] here")


class TestMerge(unittest.TestCase):
    def test_overlaps_merge(self):
        self.assertEqual(merge_spans([(0, 5, "A"), (3, 8, "B"), (10, 12, "C")]), [(0, 8, "A"), (10, 12, "C")])


class FakeComprehend:
    def __init__(self):
        self.calls = 0

    def detect_pii_entities(self, Text, LanguageCode):
        self.calls += 1
        ents = []
        start = Text.find("Priya")
        if start >= 0:
            ents.append({"Type": "NAME", "Score": 0.99, "BeginOffset": start, "EndOffset": start + 5})
        friday = Text.find("Friday")
        if friday >= 0:
            ents.append({"Type": "DATE_TIME", "Score": 0.99, "BeginOffset": friday, "EndOffset": friday + 6})
        return {"Entities": ents}


class TestComprehendAdapter(unittest.TestCase):
    def setUp(self):
        self._cache = comprehend_adapter.CACHE_PATH
        self.tmp = tempfile.TemporaryDirectory()
        comprehend_adapter.CACHE_PATH = Path(self.tmp.name) / "cache.json"

    def tearDown(self):
        comprehend_adapter.CACHE_PATH = self._cache
        self.tmp.cleanup()

    def test_names_masked_dates_ignored_and_cached(self):
        client = FakeComprehend()
        det = comprehend_adapter.ComprehendDetector(client=client)
        text = "Priya needs a ride on Friday, call 571-555-0142"
        self.assertEqual(redact(text, det(text)), "[NAME] needs a ride on Friday, call [PHONE]")
        det(text)
        self.assertEqual(client.calls, 1)
        det.save_cache()
        self.assertTrue(comprehend_adapter.CACHE_PATH.exists())

    def test_monthly_cost(self):
        self.assertEqual(comprehend_adapter.monthly_cost(10_000, 76), (3.0, 3))
        self.assertEqual(comprehend_adapter.monthly_cost(10_000, 450), (5.0, 5))
        self.assertEqual(comprehend_adapter.monthly_cost(10_000, 76, free_units=50_000), (0.0, 3))


class TestNameLookup(unittest.TestCase):
    def test_load_skips_nulls_and_splits_hyphens(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "users.csv"
            path.write_text("first_name,middle_name,last_name\nFatima,NULL,Al-Sayed\n", encoding="utf-8")
            parts = load_name_parts([path, Path(tmp) / "missing.csv"])
        self.assertEqual(parts, {"fatima", "al-sayed", "al", "sayed"})


class TestEvaluate(unittest.TestCase):
    def test_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            results = evaluate.main(["--repeats", "1", "--out", tmp])
            data = json.loads((Path(tmp) / "results.json").read_text(encoding="utf-8"))
            self.assertTrue((Path(tmp) / "results.md").exists())
        by_name = {r["approach"][0]: r for r in results}
        self.assertIn("skipped", by_name["3"])                      # no AWS in tests
        self.assertEqual(data["meta"]["requests"], 72)
        for key in ("1", "2", "4"):
            r = by_name[key]
            self.assertEqual(r["caught"] + r["partly"] + r["missed"], r["labels"])
        # Approach 4 must beat today's pipeline and the naive lookup.
        self.assertGreater(by_name["4"]["caught"], by_name["2"]["caught"])
        self.assertGreater(by_name["2"]["caught"], by_name["1"]["caught"])

    def test_score_counts_partial_and_false_positives(self):
        recs = [{"id": "P1", "subj": "", "desc": "Hi Wei Zhang", "pii": [{"field": "desc", "text": "Wei Zhang", "type": "NAME"}]},
                {"id": "C1", "subj": "", "desc": "Need food", "pii": []}]
        spans = {"P1": {"subj": [], "desc": [(3, 6, "NAME")]}, "C1": {"subj": [], "desc": [(5, 9, "X")]}}
        per_label, fp, clean = evaluate.score(recs, spans)
        self.assertEqual(per_label[0]["status"], "partly")
        self.assertEqual((fp, clean), (1, ["C1"]))


if __name__ == "__main__":
    unittest.main()
