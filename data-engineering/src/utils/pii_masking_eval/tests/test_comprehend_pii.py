"""Offline tests for approach 3 plumbing. Run:  python3 -m unittest discover -s tests -v
These use a fake client; they prove the wrapper is correct, NOT how accurate Comprehend is."""
import importlib.util
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


C = load("comprehend_pii")
D = load("detectors")


class FakeClientError(Exception):
    """Mimics botocore ClientError's shape without importing botocore."""
    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class FakeComprehend:
    def __init__(self, canned=None, raises=None):
        self.canned, self.raises, self.calls = canned or {}, raises, []

    def detect_pii_entities(self, Text, LanguageCode):
        self.calls.append((Text, LanguageCode))
        if self.raises:
            raise self.raises
        return {"Entities": self.canned.get(Text, [])}


def ent(b, e, t="NAME"):
    return {"BeginOffset": b, "EndOffset": e, "Type": t, "Score": 0.99}


class TestComprehendWrapper(unittest.TestCase):
    def test_offsets_become_spans(self):
        text = "Ask for Dmitri Volkov please"
        c = FakeComprehend({text: [ent(8, 21)]})
        self.assertEqual(C.comprehend_spans(text, c), [(8, 21, "NAME")])
        self.assertEqual(text[8:21], "Dmitri Volkov")

    def test_merges_with_regex_spans(self):
        text = "I'm Tomasz Kowalski, call (480) 555-0155"
        c = FakeComprehend({text: [ent(4, 19)]})
        spans = C.detect_patterns_comprehend(text, c)
        red = D.redact(text, spans)
        self.assertNotIn("Tomasz", red)
        self.assertNotIn("555-0155", red)

    def test_overlap_is_merged_not_duplicated(self):
        text = "call 480-555-0187 now"
        c = FakeComprehend({text: [ent(5, 17, "PHONE")]})
        spans = C.detect_patterns_comprehend(text, c)
        self.assertEqual(len(spans), 1)

    def test_long_text_is_chunked_and_offsets_shifted(self):
        text = ("x" * 10) + "Priya" + ("y" * 10)
        c = FakeComprehend({text[:8]: [], text[8:16]: [ent(2, 7)]})
        spans = C.comprehend_spans(text, c, lang="en", max_chars=8)
        self.assertEqual(len(c.calls), 4)   # 25 chars in chunks of 8
        self.assertEqual(spans, [(10, 15, "NAME")])
        self.assertEqual(text[10:15], "Priya")

    def test_access_denied_falls_back_and_still_masks_patterns(self):
        text = "email me at a.b@gmail.com"
        c = FakeComprehend(raises=FakeClientError("AccessDeniedException"))
        spans = C.detect_patterns_comprehend(text, c)
        self.assertNotIn("a.b@gmail.com", D.redact(text, spans))

    def test_throttling_uses_fallback_detector(self):
        text = "my name is jose hernandez"
        c = FakeComprehend(raises=FakeClientError("ThrottlingException"))
        spans = C.detect_patterns_comprehend(text, c, fallback=lambda t: D.detect_layered(t))
        self.assertNotIn("hernandez", D.redact(text, spans))

    def test_language_choice(self):
        self.assertEqual(C.pick_language("Mi nombre es Ana y necesito ayuda"), "es")
        self.assertEqual(C.pick_language("제 이름은 김민준입니다"), "en")   # unsupported -> en
        c = FakeComprehend()
        C.comprehend_spans("necesito comida", c)
        self.assertEqual(c.calls[0][1], "es")

    def test_empty_text_makes_no_call(self):
        c = FakeComprehend()
        self.assertEqual(C.comprehend_spans("   ", c), [])
        self.assertEqual(c.calls, [])


if __name__ == "__main__":
    unittest.main()
