"""Synthetic PostgreSQL fixture; contains no copied user records."""

from datetime import datetime

from psycopg import sql

SOURCE_COLUMNS = [
    "req_id",
    "creator_id",
    "req_for_id",
    "req_islead_id",
    "req_cat_id",
    "req_type_id",
    "req_priority_id",
    "req_status_id",
    "req_loc",
    "iscalamity",
    "req_subj",
    "req_desc",
    "req_doc_link",
    "audio_req_desc",
    "submission_date",
    "serviced_date",
    "last_updated_at",
    "to_public",
    "beneficiary_id",
    "lead_volunteer_id",
    "deletion_reason",
]


def create_fixture(conn, config):
    """Create six eligible and three ineligible synthetic requests."""
    with conn.cursor() as cur:
        cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(config.schema)))
        definitions = []
        for column in SOURCE_COLUMNS:
            kind = "text"
            if column in {
                "req_for_id",
                "req_islead_id",
                "req_type_id",
                "req_priority_id",
                "req_status_id",
            }:
                kind = "integer"
            elif column in {"submission_date", "serviced_date", "last_updated_at"}:
                kind = "timestamp"
            elif column in {"iscalamity", "to_public"}:
                kind = "boolean"
            definitions.append(
                sql.SQL("{} {}").format(sql.Identifier(column), sql.SQL(kind))
            )
        cur.execute(
            sql.SQL("CREATE TABLE {} ({})").format(
                sql.Identifier(config.schema, config.table),
                sql.SQL(", ").join(definitions),
            )
        )
        seen = set()
        for ref in config.references:
            if ref.table in seen:
                continue
            seen.add(ref.table)
            kind = "text" if ref.table in {"users", "help_category"} else "integer"
            cur.execute(
                sql.SQL("CREATE TABLE {} ({} {}, {} text)").format(
                    sql.Identifier(config.schema, ref.table),
                    sql.Identifier(ref.key),
                    sql.SQL(kind),
                    sql.Identifier(ref.label),
                )
            )
            values = {
                "users": [
                    ("U1", "Alex Example"),
                    ("U2", "Alex Example"),
                    ("UBLANK", ""),
                ],
                "help_category": [("FOOD", "Food assistance")],
                "request_for": [(1, "Self")],
                "request_isleadvol": [(1, "No")],
                "request_type": [(1, "One-time")],
                "request_priority": [(1, "High")],
                "request_statuses": [(3, "Completed"), (4, "Cancelled"), (1, "New")],
            }[ref.table]
            cur.executemany(
                sql.SQL("INSERT INTO {} VALUES (%s, %s)").format(
                    sql.Identifier(config.schema, ref.table)
                ),
                values,
            )
        rows = []
        for i in range(1, 10):
            row = dict.fromkeys(SOURCE_COLUMNS)
            row.update(
                req_id=f"REQ-{i:03}",
                creator_id="U1",
                req_for_id=1,
                req_islead_id=1,
                req_cat_id="FOOD",
                req_type_id=1,
                req_priority_id=1,
                req_status_id=3,
                req_loc="Example City",
                iscalamity=False,
                req_subj="Food support",
                req_desc="Synthetic example",
                submission_date=datetime(2025, 1, 1),
                serviced_date=datetime(2025, 6, 1),
                last_updated_at=datetime(2025, 6, 2),
                to_public=False,
                beneficiary_id="U2",
                lead_volunteer_id="U1",
            )
            if i == 2:
                for ref in config.references:
                    row[ref.column] = None
            elif i == 3:
                for ref in config.references:
                    row[ref.column] = (
                        "MISSING" if ref.table in {"users", "help_category"} else 999
                    )
            elif i == 4:
                row.update(
                    creator_id="UBLANK",
                    beneficiary_id="UBLANK",
                    lead_volunteer_id="UBLANK",
                )
            elif i == 5:
                row.update(creator_id="U2", req_status_id=4, req_desc="")
            elif i == 6:
                row.update(
                    req_subj='Food, "care" and shelter',
                    req_desc="Line 1\nLine 2 — café",
                    req_doc_link=r"\N",
                    deletion_reason="",
                )
            elif i == 7:
                row["serviced_date"] = datetime(2026, 2, 1)
            elif i == 8:
                row["serviced_date"] = datetime(2026, 1, 1)
            elif i == 9:
                row["serviced_date"] = None
            rows.append(tuple(row[c] for c in SOURCE_COLUMNS))
        cur.executemany(
            sql.SQL("INSERT INTO {} VALUES ({})").format(
                sql.Identifier(config.schema, config.table),
                sql.SQL(",").join(sql.Placeholder() for _ in SOURCE_COLUMNS),
            ),
            rows,
        )
    conn.commit()
