"""Approach 3: patterns + Amazon Comprehend, with the AWS client injected so it can be mocked.

The client is any object with ``detect_pii_entities(Text=..., LanguageCode=...)`` that returns
``{"Entities": [{"BeginOffset": int, "EndOffset": int, "Type": str, ...}]}``.
Production: ``boto3.client("comprehend")``.  Tests / no AWS access: ``FakeComprehend`` (tests/test_comprehend_pii.py).
No boto3 import here, so this module is Lambda-light and importable without AWS.
"""
import importlib.util
import logging
import os

log = logging.getLogger(__name__)
_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("detectors", os.path.join(_HERE, "detectors.py"))
_D = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_D)

MAX_CHARS = 20_000        # stay well under Comprehend's 100 KB sync limit (UTF-8 can be 4 bytes/char)
_ES_MARKERS = ("necesito", "nombre es", "me llamo", "mi hija", "mi hijo", "tengo", "ayuda con", " soy ")


def pick_language(text):
    """Comprehend PII supports only 'en' and 'es'. Everything else is sent as 'en'."""
    low = f" {text.lower()} "
    return "es" if any(m in low for m in _ES_MARKERS) else "en"


def _error_code(exc):
    return getattr(exc, "response", {}).get("Error", {}).get("Code", type(exc).__name__)


def comprehend_spans(text, client, lang=None, max_chars=MAX_CHARS):
    """Return [(start, end, TYPE)] for `text`, splitting long text and fixing offsets.

    Raises whatever the client raises; use detect_patterns_comprehend() for the safe version.
    """
    lang = lang or pick_language(text)
    spans = []
    for off in range(0, max(len(text), 1), max_chars):
        chunk = text[off:off + max_chars]
        if not chunk.strip():
            continue
        resp = client.detect_pii_entities(Text=chunk, LanguageCode=lang)
        for e in resp.get("Entities", []):
            spans.append((off + e["BeginOffset"], off + e["EndOffset"], e["Type"]))
    return spans


def detect_patterns_comprehend(text, client, fallback=None, lang=None):
    """Approach 3: regex patterns + Comprehend.

    On any Comprehend failure (AccessDenied, Throttling, unsupported language, size...) we log the
    error code and fall back to `fallback(text)` (e.g. the layered detector) or to patterns only,
    so one bad call never leaks raw text or kills the pipeline.
    """
    base = _D.detect_patterns(text)
    try:
        return _D.merge(base + comprehend_spans(text, client, lang))
    except Exception as exc:          # noqa: BLE001 - deliberate: never fail open silently
        log.warning("comprehend failed (%s); using fallback", _error_code(exc))
        extra = fallback(text) if fallback else []
        return _D.merge(base + extra)
