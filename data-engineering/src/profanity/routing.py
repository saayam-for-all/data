"""Route a Help Request according to its sentiment score (issue #422).

Policy, from the maintainer note on #422 (2026-10-21): a score of 0 continues
into the normal matching workflow; scores 1, 2 and 3 are "special requests"
and are diverted out of it.

    0  Good Request            -> ALLOW,  caller continues normal intake
    1  Foul Language           -> DIVERT, stored with ref_code = 1
    2  Depressive or Suicidal  -> DIVERT, stored with ref_code = 2, escalated
    3  Threatening             -> DIVERT, stored with ref_code = 3, blocked

Two deliberate boundaries:

1. Score 0 performs no insert. Creating the request row is the existing intake
   service's job and reimplementing it here would duplicate that logic; this
   module returns ALLOW and lets intake proceed.

2. Scores 1-3 are written to `fraud_requests`, which is the only table that
   currently has the `ref_code` column (NOT NULL, FK to sentiment_codes) and
   can therefore record a sentiment score at all. The alternative discussed on
   the issue - keeping special requests in `requests` under an "SP" sequence -
   needs a schema change first; see SPECIAL_REQUEST_TABLE and the PR notes.

Code 2 is a distress signal, not a profanity problem. This module will not
return a "please reword your request" outcome for it: `requires_human_review`
and `escalate` are set so the caller routes the person to a human. What that
escalation actually does is a product decision and is not implemented here.
"""

import os
import re

from src.profanity.severity import (
    DEPRESSIVE_OR_SUICIDAL,
    SAFE,
    THREATENING,
)

# --- Configuration -------------------------------------------------------

SCHEMA_NAME = os.environ.get("SAAYAM_DB_SCHEMA", "virginia_dev_saayam_rdbms")

# Table that receives scores 1-3. Switch to "requests" once that table gains a
# ref_code column and the SP sequence exists.
SPECIAL_REQUEST_TABLE = os.environ.get("SPECIAL_REQUEST_TABLE",
                                       "fraud_requests")

# Sequence used to mint ids for diverted requests. Only consulted when the
# caller does not already carry a req_id.
SPECIAL_REQUEST_SEQUENCE = os.environ.get("SPECIAL_REQUEST_SEQUENCE",
                                          "special_request_id_seq")

SPECIAL_REQUEST_ID_PREFIX = os.environ.get("SPECIAL_REQUEST_ID_PREFIX", "SP")

# Status applied to a diverted request, resolved by name through
# request_status so no numeric id is hardcoded.
STATUS_FOR_SPECIAL_REQUEST = os.environ.get("STATUS_FOR_SPECIAL_REQUEST",
                                            "CREATED")

DIVERTED_CODES = {
    int(code) for code in
    os.environ.get("DIVERTED_SENTIMENT_CODES", "1,2,3").split(",")
    if code.strip()
}

ALLOW = "ALLOW"
DIVERT = "DIVERT"

REQUIRED_PAYLOAD_FIELDS = (
    "req_user_id", "req_for_id", "req_islead_id", "req_cat_id",
    "req_type_id", "req_priority_id", "req_subj", "req_desc",
)

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _ident(name, kind):
    """Identifiers cannot be bound as parameters, so validate them instead."""
    if not _IDENTIFIER.match(name or ""):
        raise ValueError("Invalid {}: {!r}".format(kind, name))
    return name


def _schema():
    return _ident(SCHEMA_NAME, "schema name")


# --- Lookups -------------------------------------------------------------

def resolve_code_label(cursor, code):
    """Authoritative (label, description) for a sentiment code.

    Works with both RealDictCursor and a plain tuple cursor.
    """
    cursor.execute(
        "SELECT code_label, code_desc FROM {schema}.sentiment_codes "
        "WHERE code = %(code)s".format(schema=_schema()),
        {"code": code})
    row = cursor.fetchone()
    if not row:
        raise LookupError("sentiment_codes has no row for code {}".format(code))
    if isinstance(row, dict):
        return row["code_label"], row["code_desc"]
    return row[0], row[1]


def resolve_status_id(cursor, status_name):
    """req_status_id for a status name - never a hardcoded integer."""
    cursor.execute(
        "SELECT req_status_id FROM {schema}.request_status "
        "WHERE UPPER(req_status) = UPPER(%(name)s)".format(schema=_schema()),
        {"name": status_name})
    row = cursor.fetchone()
    if not row:
        raise LookupError(
            "request_status has no status named {!r}; set "
            "STATUS_FOR_SPECIAL_REQUEST to a status that exists"
            .format(status_name))
    return row["req_status_id"] if isinstance(row, dict) else row[0]


def next_special_request_id(cursor):
    """Mint an id for a diverted request from the SP sequence.

    Interim: the maintainer note asks for an "SP" sequence but none exists in
    the schema yet, so this reads a sequence the operator creates (see the PR
    notes for the DDL) rather than inventing ids that could collide with a
    real sequence later.
    """
    sequence = _ident(SPECIAL_REQUEST_SEQUENCE, "sequence name")
    cursor.execute(
        "SELECT nextval('{schema}.{sequence}') AS seq".format(
            schema=_schema(), sequence=sequence))
    row = cursor.fetchone()
    seq = row["seq"] if isinstance(row, dict) else row[0]

    padded = str(seq).zfill(13)
    return "{prefix}-{a}-{b}-{c}-{d}".format(
        prefix=SPECIAL_REQUEST_ID_PREFIX, a=padded[0:3], b=padded[3:6],
        c=padded[6:9], d=padded[9:13])


# --- Routing -------------------------------------------------------------

def missing_fields(payload):
    return [f for f in REQUIRED_PAYLOAD_FIELDS
            if payload.get(f) in (None, "")]


def store_special_request(cursor, payload, classification):
    """Insert a diverted request and return its req_id."""
    table = _ident(SPECIAL_REQUEST_TABLE, "table name")
    req_id = payload.get("req_id") or next_special_request_id(cursor)
    status_id = resolve_status_id(cursor, STATUS_FOR_SPECIAL_REQUEST)

    columns = [
        "req_id", "req_user_id", "req_for_id", "req_islead_id", "req_cat_id",
        "req_type_id", "req_priority_id", "req_status_id", "req_loc",
        "iscalamity", "req_subj", "req_desc", "req_doc_link",
        "audio_req_desc", "submission_date", "to_public", "ref_code",
    ]
    params = {
        "req_id": req_id,
        "req_user_id": payload["req_user_id"],
        "req_for_id": payload["req_for_id"],
        "req_islead_id": payload["req_islead_id"],
        "req_cat_id": payload["req_cat_id"],
        "req_type_id": payload["req_type_id"],
        "req_priority_id": payload["req_priority_id"],
        "req_status_id": status_id,
        "req_loc": payload.get("req_loc"),
        "iscalamity": payload.get("iscalamity", False),
        "req_subj": payload["req_subj"],
        "req_desc": payload["req_desc"],
        "req_doc_link": payload.get("req_doc_link"),
        "audio_req_desc": payload.get("audio_req_desc"),
        # Left to the column default when the caller does not supply one.
        "submission_date": payload.get("submission_date"),
        # A diverted request is never publicly visible.
        "to_public": False,
        "ref_code": classification["severity_score"],
    }

    cursor.execute(
        "INSERT INTO {schema}.{table} ({columns}) VALUES ({placeholders}) "
        "RETURNING req_id".format(
            schema=_schema(), table=table,
            columns=", ".join(columns),
            placeholders=", ".join("%({})s".format(c) for c in columns)),
        params)
    row = cursor.fetchone()
    return row["req_id"] if isinstance(row, dict) else row[0]


def route(cursor, payload, classification):
    """Decide where a scored help request goes, and persist it if diverted.

    Returns the routing decision; the caller owns the HTTP response and, for
    ALLOW, the normal request insert.
    """
    score = classification["severity_score"]

    label, description = None, None
    try:
        label, description = resolve_code_label(cursor, score)
    except LookupError:
        # An unseeded lookup table should not stop a request being routed.
        label = classification.get("severity_label")

    decision = {
        "severity_score": score,
        "severity_label": label,
        "severity_description": description,
        "matched_codes": classification.get("matched_codes", []),
        "action": ALLOW,
        "stored_in": None,
        "req_id": payload.get("req_id"),
        "requires_human_review": False,
        "escalate": False,
        "blocked": False,
    }

    if score not in DIVERTED_CODES:
        if score != SAFE:
            # Configured out of diversion but still not clean - say so rather
            # than letting it look like a clean request.
            decision["requires_human_review"] = True
        return decision

    decision["action"] = DIVERT
    decision["requires_human_review"] = True
    decision["blocked"] = score == THREATENING
    # Distress goes to a person, not to a moderation queue.
    decision["escalate"] = score == DEPRESSIVE_OR_SUICIDAL
    decision["req_id"] = store_special_request(cursor, payload, classification)
    decision["stored_in"] = "{}.{}".format(SCHEMA_NAME, SPECIAL_REQUEST_TABLE)
    return decision
