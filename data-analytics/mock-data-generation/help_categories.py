"""Generates the help_categories table.

cat_id follows the existing hierarchical convention used elsewhere in this
repo's mock-data scripts (database/mock-data-generation/utils.py CAT_IDS),
e.g. '1', '1.1', '1.1.1'.
"""

from typing import Dict, List

from reference_data import CAT_IDS, CATEGORY_LABEL_BANKS, TOP_LEVEL_CATEGORY_NAMES
from utils import format_ts, random_datetime_in_window


def generate_help_categories() -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    bank_cursor = {top: 0 for top in TOP_LEVEL_CATEGORY_NAMES}

    for cat_id in CAT_IDS:
        if cat_id == "0.0.0.0.0":
            cat_name = "Uncategorized"
            cat_desc = "General or unspecified request category (catch-all when no specific category applies)."
        else:
            top = cat_id.split(".")[0]
            top_name = TOP_LEVEL_CATEGORY_NAMES[top]
            if "." not in cat_id:
                cat_name = top_name
                cat_desc = f"Top-level category covering {top_name.lower()}."
            else:
                bank = CATEGORY_LABEL_BANKS[top]
                label = bank[bank_cursor[top] % len(bank)]
                bank_cursor[top] += 1
                cat_name = f"{top_name}: {label}"
                cat_desc = f"Help related to {label.lower()} under {top_name.lower()}."

        rows.append({
            "cat_id": cat_id,
            "cat_name": cat_name[:100],
            "cat_desc": cat_desc[:150],
            "last_updated_at": format_ts(random_datetime_in_window()),
        })

    return rows
