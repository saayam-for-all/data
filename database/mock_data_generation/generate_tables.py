"""CLI entrypoint for schema-driven mock data generation."""

from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path
from typing import Dict, List

from faker import Faker

from .config import GenerationConfig
from .dependency_resolver import resolve_generation_order
from .generators.base_generators import BaseValueGenerator
from .generators.table_rules import apply_table_rules, seed_rules_rng
from .lookup_loader import (
    LookupLoader,
    build_location_reference_rows,
    build_state_country_pairs,
)
from .schema_parser import SchemaParser
from .validators import validate_csv_outputs

DEFAULT_FK_MAP: Dict[str, Dict[str, str]] = {
    "users": {
        "state_id": "state.state_id",
        "country_id": "country.country_id",
        "user_status_id": "user_status.user_status_id",
        "user_category_id": "user_category.user_category_id",
    },
    "request": {
        "req_user_id": "users.user_id",
        "req_for_id": "request_for.req_for_id",
        "req_islead_id": "request_isleadvol.req_islead_id",
        "req_cat_id": "help_categories.cat_id",
        "req_type_id": "request_type.req_type_id",
        "req_priority_id": "request_priority.req_priority_id",
        "req_status_id": "request_status.req_status_id",
    },
}

LOOKUP_ID_OVERRIDES = {
    "help_categories": "cat_id",
    "location_reference": "location_id",
}

NON_BLANK_COLUMNS = {
    "users": {
        "user_id",
        "state_id",
        "country_id",
        "user_status_id",
        "user_category_id",
        "first_name",
        "last_name",
        "full_name",
        "primary_email_address",
        "primary_phone_number",
        "addr_ln1",
        "city_name",
        "zip_code",
        "last_location",
        "last_update_date",
        "time_zone",
        "gender",
        "language_1",
        "promotion_wizard_stage",
        "promotion_wizard_last_update_date",
        "external_auth_provider",
        "dob",
    },
    "request": {
        "req_id",
        "req_user_id",
        "req_for_id",
        "req_islead_id",
        "req_cat_id",
        "req_type_id",
        "req_priority_id",
        "req_status_id",
        "req_loc",
        "req_subj",
        "req_desc",
        "submission_date",
        "last_update_date",
        "to_public",
    },
}


class MockDataGenerationService:
    """Main service for schema-driven CSV generation."""

    def __init__(self, config: GenerationConfig):
        self.config = config.resolve()

        self.fake = Faker()
        self.rng = random.Random(self.config.seed)
        Faker.seed(self.config.seed)
        self.fake.seed_instance(self.config.seed)
        seed_rules_rng(self.config.seed)

        self.schema = SchemaParser(explicit_fk_map=DEFAULT_FK_MAP).parse(
            self.config.schema_path
        )
        self.lookups = LookupLoader(
            id_column_overrides=LOOKUP_ID_OVERRIDES
        ).load(self.config.lookup_dir)
        self.base_generator = BaseValueGenerator(fake=self.fake, rng=self.rng)

        self.generated_pk_pools: Dict[str, List[str]] = {}
        self.lookup_value_pools: Dict[str, List[str]] = {
            name: [str(v) for v in lookup.ids]
            for name, lookup in self.lookups.items()
        }

        self.state_country_pairs = (
            build_state_country_pairs(self.lookups["state"])
            if "state" in self.lookups
            else []
        )

        self.location_reference_rows = (
            build_location_reference_rows(self.lookups["location_reference"])
            if "location_reference" in self.lookups
            else []
        )

        self.language_values = self._extract_lookup_values(
            lookup_name="supporting_languages",
            column_name="language_name",
        )

    def generate(self, tables: List[str]) -> Dict[str, object]:
        ordered_tables = resolve_generation_order(self.schema, tables)
        self.config.output_dir.mkdir(parents=True, exist_ok=True)

        for table_name in ordered_tables:
            row_count = self.config.row_counts.get(table_name, 100)
            rows = self._generate_table(table_name, row_count)
            self._write_csv(table_name, rows)

            pk_name = self.schema.require_table(table_name).primary_key
            if pk_name:
                self.generated_pk_pools[table_name] = [
                    str(row[pk_name]) for row in rows
                ]

        return self.validate(tables, ordered_tables=ordered_tables)

    def validate(
        self,
        tables: List[str],
        ordered_tables: List[str] | None = None,
    ) -> Dict[str, object]:
        validation_results = validate_csv_outputs(
            schema=self.schema,
            output_dir=self.config.output_dir,
            selected_tables=tables,
            parent_value_pools=self.generated_pk_pools,
            lookup_value_pools=self.lookup_value_pools,
        )

        output_tables = ordered_tables or tables
        return {
            "ordered_tables": output_tables,
            "output_dir": str(self.config.output_dir),
            "files": [
                str(self.config.output_dir / f"{table}.csv")
                for table in output_tables
            ],
            "validation": [
                {
                    "table": result.table_name,
                    "passed": result.passed,
                    "errors": result.errors,
                }
                for result in validation_results
            ],
        }

    def _generate_table(self, table_name: str, row_count: int) -> List[dict]:
        table = self.schema.require_table(table_name)
        rows: List[dict] = []

        # Track unique values for columns that must be unique within the table.
        seen_emails: set = set() if table_name == "users" else None

        for _ in range(row_count):
            row: Dict[str, object] = {}

            chosen_state_country = (
                self.rng.choice(self.state_country_pairs)
                if table_name == "users" and self.state_country_pairs
                else None
            )

            chosen_user_location = (
                self.rng.choice(self.location_reference_rows)
                if table_name == "users" and self.location_reference_rows
                else None
            )

            for column in table.columns:
                row[column.name] = self._generate_column_value(
                    table_name=table_name,
                    column=column,
                    current_row=row,
                    chosen_state_country=chosen_state_country,
                    chosen_user_location=chosen_user_location,
                )

            # Email uniqueness for users — retry up to 5 times on collision.
            # Re-derive from the same name with a fresh suffix so the email
            # still matches the row's identity.
            if seen_emails is not None:
                email = str(row.get("primary_email_address", "")).strip()
                attempts = 0
                first = str(row.get("first_name", "")).strip().lower()
                last = str(row.get("last_name", "")).strip().lower()
                first_clean = "".join(c for c in first if c.isalnum())
                last_clean = "".join(c for c in last if c.isalnum())
                while email and email in seen_emails and attempts < 5:
                    if first_clean and last_clean:
                        domain = self.rng.choice([
                            "gmail.com", "yahoo.com", "outlook.com",
                            "hotmail.com", "icloud.com", "protonmail.com",
                        ])
                        email = f"{first_clean}.{last_clean}{self.rng.randint(1, 99999)}@{domain}"
                    else:
                        email = self.base_generator.generate(
                            "primary_email_address", "character varying (255)", 255
                        )
                    attempts += 1
                row["primary_email_address"] = email
                if email:
                    seen_emails.add(email)

            row = apply_table_rules(table_name, row)
            rows.append(row)

        return rows

    def _generate_column_value(
        self,
        table_name: str,
        column,
        current_row: Dict[str, object],
        chosen_state_country,
        chosen_user_location,
    ):
        fk_map = DEFAULT_FK_MAP.get(table_name, {})
        col_name = str(column.name).strip().lower()
        normalized_fk_map = {str(k).strip().lower(): v for k, v in fk_map.items()}

        # Geographic integrity for users:
        # - state_id / country_id come from real state.csv pairs (chosen_state_country)
        # - time_zone comes from location_reference when available (5,000 users
        #   spread across 18 seeded TZs is acceptable — there are only ~24 TZs anyway)
        # - city_name / last_location fall through to Faker for diversity
        #   (location_reference shadowing them produced only 18 cities for 5k users)
        if table_name == "users" and chosen_user_location:
            if col_name == "time_zone":
                return str(chosen_user_location[col_name])

        # Explicit FK enforcement
        if col_name in normalized_fk_map:
            ref_table, _ref_column = normalized_fk_map[col_name].split(".", maxsplit=1)

            # fallback for users if no location reference rows exist
            if (
                table_name == "users"
                and col_name in {"state_id", "country_id"}
                and chosen_state_country
            ):
                return str(chosen_state_country[col_name])

            # FK to previously generated parent tables
            if ref_table in self.generated_pk_pools and self.generated_pk_pools[ref_table]:
                return str(self.rng.choice(self.generated_pk_pools[ref_table]))

            # FK to lookup tables
            if ref_table in self.lookups and self.lookups[ref_table].ids:
                return str(self.rng.choice(self.lookups[ref_table].ids))

        # Build full_name from already generated name parts
        if col_name == "full_name":
            first = str(current_row.get("first_name", "")).strip()
            middle = str(current_row.get("middle_name", "")).strip()
            last = str(current_row.get("last_name", "")).strip()
            parts = [part for part in [first, middle, last] if part]
            if parts:
                return " ".join(parts)

        # Build email from already-generated name parts so it matches the user's
        # actual name. Without this, fake.email() emits a random unrelated address
        # (e.g. "Jeffrey Doyle" was getting "garzaanthony@example.org").
        if col_name == "primary_email_address":
            first = str(current_row.get("first_name", "")).strip().lower()
            last = str(current_row.get("last_name", "")).strip().lower()
            if first and last:
                domain = self.rng.choice([
                    "gmail.com", "yahoo.com", "outlook.com",
                    "hotmail.com", "icloud.com", "protonmail.com",
                ])
                # Strip non-ASCII / spaces from name parts to keep emails valid
                first_clean = "".join(c for c in first if c.isalnum())
                last_clean = "".join(c for c in last if c.isalnum())
                if first_clean and last_clean:
                    return f"{first_clean}.{last_clean}{self.rng.randint(1, 9999)}@{domain}"

        # Prefer lookup-driven language values, with deduplication so
        # language_2 != language_1 and language_3 != {language_1, language_2}.
        if (
            table_name == "users"
            and col_name in {"language_1", "language_2", "language_3"}
            and self.language_values
        ):
            if col_name == "language_1":
                return (
                    "English"
                    if "English" in self.language_values
                    else self.language_values[0]
                )

            if self.rng.random() < 0.25:
                return ""

            already = {
                str(current_row.get("language_1", "")).strip(),
                str(current_row.get("language_2", "")).strip(),
            }
            available = [v for v in self.language_values if v not in already]
            if not available:
                return ""
            return self.rng.choice(available)

        non_blank = (
            str(column.name).strip() in NON_BLANK_COLUMNS.get(table_name, set())
            or column.is_primary_key
            or col_name in normalized_fk_map
        )

        if not non_blank and column.is_nullable and self.rng.random() < 0.15:
            return ""

        return self.base_generator.generate(
            column.name,
            column.data_type,
            column.max_length,
        )

    def _extract_lookup_values(self, lookup_name: str, column_name: str) -> List[str]:
        lookup = self.lookups.get(lookup_name)
        if not lookup:
            return []

        values: List[str] = []
        for row in lookup.rows:
            value = row.get(column_name)
            if value not in (None, ""):
                values.append(str(value))

        return values

    def _write_csv(self, table_name: str, rows: List[dict]) -> None:
        table = self.schema.require_table(table_name)
        path = self.config.output_dir / f"{table_name}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)

        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=table.column_order)
            writer.writeheader()
            writer.writerows(rows)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate schema-driven mock CSV files."
    )
    parser.add_argument("--schema", required=True, help="Path to db_info.json")
    parser.add_argument(
        "--lookup-dir",
        required=True,
        help="Path to lookup table CSV directory",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory for generated CSV output",
    )
    parser.add_argument(
        "--tables",
        default="users,request",
        help="Comma-separated list of tables to generate",
    )
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument(
        "--row-counts",
        default="",
        help='JSON string like {"users":5000,"request":20000}',
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Only validate existing CSVs in output-dir",
    )
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    row_counts = (
        json.loads(args.row_counts)
        if args.row_counts
        else {"users": 5000, "request": 20000}
    )

    config = GenerationConfig(
        schema_path=Path(args.schema),
        lookup_dir=Path(args.lookup_dir),
        output_dir=Path(args.output_dir),
        seed=args.seed,
        row_counts=row_counts,
    )

    service = MockDataGenerationService(config)
    tables = [table.strip() for table in args.tables.split(",") if table.strip()]
    result = (
        service.validate(tables)
        if args.validate_only
        else service.generate(tables)
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()