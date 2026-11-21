"""Synthetic fixtures only; no repository CSVs or personal records are read."""

import sqlite3
from contextlib import closing
from pathlib import Path


REQUEST_COLUMNS = (
    "req_id", "creator_id", "beneficiary_id", "lead_volunteer_id", "req_cat_id",
    "req_for_id", "req_islead_id", "req_type_id", "req_priority_id", "req_status_id",
    "req_subj", "req_desc", "req_doc_link", "audio_req_desc", "deletion_reason",
    "req_loc", "created_loc", "iscalamity", "to_public", "submission_date",
    "serviced_date", "last_updated_at",
)

LOOKUP_DATA = (
    ("help_categories", "cat_id TEXT", "cat_name TEXT", [("1.3", "Food assistance"), ("2.1", "Education")]),
    ("request_for", "req_for_id INTEGER", "req_for TEXT", [(0, "SELF"), (1, "OTHER")]),
    ("request_isleadvol", "req_islead_id INTEGER", "req_islead TEXT", [(0, "NO"), (1, "YES")]),
    ("request_types", "req_type_id INTEGER", "req_type TEXT", [(0, "IN_PERSON"), (1, "REMOTE"), (2, None)]),
    ("request_priorities", "req_priority_id INTEGER", "req_priority TEXT",
     [(0, "LOW"), (1, "MEDIUM"), (2, "HIGH"), (3, "CRITICAL")]),
    ("request_statuses", "req_status_id INTEGER", "req_status TEXT",
     list(enumerate(("CREATED", "MATCHING_VOLUNTEER", "IN_PROGRESS", "RESOLVED",
                     "CANCELLED", "DELETED", "RATED_BY_REQUESTER", "RATED_BY_VOLUNTEER",
                     "VOLUNTEER_NOT_FOUND")))),
)


def create_fixture(path: Path):
    """Create a fresh database, relaxing constraints to exercise bad references."""
    if path.exists():
        raise FileExistsError("Use a fresh temporary path for the synthetic fixture")
    with closing(sqlite3.connect(path)) as connection, connection:
        for table, key, label, values in LOOKUP_DATA:
            connection.execute(f"CREATE TABLE {table} ({key}, {label})")
            connection.executemany(f"INSERT INTO {table} VALUES (?, ?)", values)
        integer_columns = {"req_for_id", "req_islead_id", "req_type_id", "req_priority_id",
                           "req_status_id", "iscalamity", "to_public"}
        definitions = ", ".join(f"{name} {'INTEGER' if name in integer_columns else 'TEXT'}"
                                for name in REQUEST_COLUMNS)
        # No PK/FK/NOT NULL constraints: corruption tests must be able to insert failures.
        connection.execute(f"CREATE TABLE requests ({definitions})")
        rows = []
        for index in range(1, 13):
            values = dict.fromkeys(REQUEST_COLUMNS)
            values.update(req_id=f"SYN-REQ-{index:03}", creator_id="SYN-USER-001",
                          beneficiary_id="SYN-USER-002" if index % 2 else None,
                          lead_volunteer_id="SYN-USER-003" if index == 1 else None,
                          req_cat_id="1.3" if index % 2 else "2.1", req_for_id=index % 2,
                          req_islead_id=0, req_type_id=index % 2, req_priority_id=index % 4,
                          req_status_id=(index - 1) % 9, req_subj=f"Synthetic request {index}",
                          req_desc='Please bring rice, "beans" and tea.\nThank you — नमस्ते.',
                          req_loc="0101000020E610000000000000008052C00000000000404440",
                          created_loc=None, iscalamity=0, to_public=0,
                          submission_date="2026-10-23 08:00:00.000000",
                          last_updated_at=f"2026-10-{23 + index:02} 12:00:00.000000"
                          if index <= 8 else f"2026-11-{index - 8:02} 12:00:00.000000")
            if index == 3:
                values["last_updated_at"] = None
            if index in {10, 11}:
                for column in ("req_cat_id", "req_for_id", "req_islead_id", "req_type_id",
                               "req_priority_id", "req_status_id"):
                    values[column] = None if index == 10 else ("missing-category" if column == "req_cat_id" else 999)
            if index == 12:
                values["req_type_id"] = 2  # Existing target with a NULL readable label.
            rows.append(tuple(values[name] for name in REQUEST_COLUMNS))
        placeholders = ",".join("?" for _ in REQUEST_COLUMNS)
        connection.executemany(f"INSERT INTO requests VALUES ({placeholders})", rows)


class LocalS3:
    """An upload_fileobj-compatible sink that only writes into a local folder."""

    def __init__(self, destination: Path):
        """Choose one local CSV path; no AWS client is ever constructed."""
        self.destination = destination
        self.calls = []

    def upload_fileobj(self, fileobj, bucket, key, ExtraArgs):
        """Write the validated byte stream atomically and record upload metadata."""
        temporary = self.destination.with_suffix(".partial")
        try:
            with temporary.open("wb") as output:
                while chunk := fileobj.read(65536):
                    output.write(chunk)
            temporary.replace(self.destination)
        finally:
            temporary.unlink(missing_ok=True)
        self.calls.append({"bucket": bucket, "key": key, "extra_args": ExtraArgs})
