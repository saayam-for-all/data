"""Names from the ``users`` table, used by approaches 2 and 4.

In Lambda the names would come from one query when the function starts::

    SELECT first_name, middle_name, last_name
    FROM virginia_dev_saayam_rdbms.users

For this evaluation they come from CSV exports with the same columns: the
repo's ``data-analytics/sql/users.csv`` (dev export) plus ``data/mock_users.csv``
(the fictional registered users that the test texts mention).
"""

import csv
import re
from pathlib import Path

NULLS = {"", "null", "none", "nan"}
_SPLIT = re.compile(r"[\s\-]+")


def load_name_parts(csv_paths):
    """Return the set of lower-cased name parts found in the given CSVs.

    Each first, middle and last name is split on spaces and hyphens, so
    "Al-Sayed" gives "al" and "sayed" as well as "al-sayed".
    """
    parts = set()
    for path in csv_paths:
        path = Path(path)
        if not path.exists():
            continue
        with path.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                for col in ("first_name", "middle_name", "last_name"):
                    value = (row.get(col) or "").strip()
                    if value.lower() in NULLS:
                        continue
                    parts.add(value.lower())
                    for piece in _SPLIT.split(value):
                        if piece:
                            parts.add(piece.lower())
    return parts
