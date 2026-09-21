"""Virginia analytics schema used by the mock-data generator and validator.

Source of truth: the "Changes to the Database, Waiting for Microservice" page of
the saayam-for-all/database wiki (table names reflect the 8/17/2026 pluralization
rename: states, cities, countries). Column order here is the CSV column order and
the DDL column order. `schema.sql` in this folder is the matching DDL.

Type vocabulary (used by validate_mock_data.py to check every cell):
    varchar(n) | text | int | bigint | serial | bool | timestamp | date
    decimal(p,s) | point | geography_point | jsonb | enum:<name>
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

ENUMS: Dict[str, Tuple[str, ...]] = {
    "skill_levels": ("BEGINNER", "INTERMEDIATE", "ADVANCED", "EXPERT"),
    "org_type_enum": ("non_profit", "for_profit"),
    "org_size_enum": ("small", "medium", "large"),
}


@dataclass(frozen=True)
class Column:
    name: str
    type: str
    nullable: bool = True


@dataclass(frozen=True)
class ForeignKey:
    column: str
    ref_table: str
    ref_column: str


@dataclass(frozen=True)
class Table:
    name: str
    columns: Tuple[Column, ...]
    primary_key: Tuple[str, ...]
    foreign_keys: Tuple[ForeignKey, ...] = field(default_factory=tuple)

    @property
    def column_names(self) -> List[str]:
        return [c.name for c in self.columns]

    def column(self, name: str) -> Column:
        return next(c for c in self.columns if c.name == name)


def _cols(*specs) -> Tuple[Column, ...]:
    """(name, type) is nullable; (name, type, False) is NOT NULL."""
    return tuple(Column(s[0], s[1], s[2] if len(s) > 2 else True) for s in specs)


COUNTRIES = Table(
    "countries",
    _cols(
        ("country_id", "serial", False),
        ("country_name", "varchar(100)", False),
        ("phone_code", "varchar(5)", False),
        ("country_code", "varchar(6)", False),
        ("last_updated_at", "timestamp"),
        ("is_eu_member", "bool"),
    ),
    ("country_id",),
)

STATES = Table(
    "states",
    _cols(
        ("state_id", "varchar(50)", False),
        ("country_id", "int", False),
        ("state_name", "varchar(100)", False),
        ("state_code", "varchar(6)"),
        ("last_updated_at", "timestamp"),
    ),
    ("state_id",),
    (ForeignKey("country_id", "countries", "country_id"),),
)

# The wiki DDL spells the coordinate column `lattitude` (sic); kept verbatim.
CITIES = Table(
    "cities",
    _cols(
        ("city_id", "serial", False),
        ("state_id", "varchar(50)", False),
        ("city_name", "varchar(30)", False),
        ("lattitude", "decimal(9,6)"),
        ("longitude", "decimal(9,6)"),
        ("last_updated_at", "timestamp"),
    ),
    ("city_id",),
    (ForeignKey("state_id", "states", "state_id"),),
)

HELP_CATEGORIES = Table(
    "help_categories",
    _cols(
        ("cat_id", "varchar(50)", False),
        ("cat_name", "varchar(100)", False),
        ("cat_desc", "varchar(150)", False),
        ("last_updated_at", "timestamp"),
    ),
    ("cat_id",),
)

USERS = Table(
    "users",
    _cols(
        ("user_id", "varchar(255)", False),
        ("state_id", "varchar(30)"),
        ("country_id", "int"),
        ("user_status_id", "int"),
        ("full_name", "varchar(255)"),
        ("first_name", "varchar(255)"),
        ("middle_name", "varchar(255)"),
        ("last_name", "varchar(255)"),
        ("primary_email_address", "varchar(255)"),
        ("primary_phone_number", "varchar(255)"),
        ("addr_ln1", "varchar(255)"),
        ("addr_ln2", "varchar(255)"),
        ("addr_ln3", "varchar(255)"),
        ("city_name", "varchar(255)"),
        ("zip_code", "varchar(255)"),
        ("last_location", "point"),
        ("last_updated_at", "timestamp"),
        ("time_zone", "varchar(255)"),
        ("profile_picture_path", "varchar(255)"),
        ("gender", "varchar(255)"),
        ("language_1", "bigint"),
        ("language_2", "bigint"),
        ("language_3", "bigint"),
        ("promotion_wizard_stage", "int"),
        ("promotion_wizard_last_updated_at", "timestamp"),
        ("external_auth_provider", "varchar(20)"),
        ("dob", "date"),
        ("is_eu", "bool"),
    ),
    ("user_id",),
    (
        ForeignKey("country_id", "countries", "country_id"),
        ForeignKey("state_id", "states", "state_id"),
    ),
)

VOLUNTEER_DETAILS = Table(
    "volunteer_details",
    _cols(
        ("user_id", "varchar(255)", False),
        ("terms_and_conditions", "bool"),
        ("terms_accepted_at", "timestamp"),
        ("govt_id_path1", "text"),
        ("govt_id_path2", "text"),
        ("path1_updated_at", "timestamp"),
        ("path2_updated_at", "timestamp"),
        ("availability_days", "jsonb"),
        ("availability_times", "jsonb"),
        ("created_at", "timestamp"),
        ("last_updated_at", "timestamp"),
    ),
    ("user_id",),
    (ForeignKey("user_id", "users", "user_id"),),
)

USER_SKILLS = Table(
    "user_skills",
    _cols(
        ("user_id", "varchar(255)", False),
        ("cat_id", "varchar(50)", False),
        ("skill_level", "enum:skill_levels"),
        ("created_at", "timestamp"),
        ("last_updated_at", "timestamp"),
    ),
    ("user_id", "cat_id"),
    (
        ForeignKey("user_id", "users", "user_id"),
        ForeignKey("cat_id", "help_categories", "cat_id"),
    ),
)

VOLUNTEER_LOCATIONS = Table(
    "volunteer_locations",
    _cols(
        ("user_id", "varchar(255)", False),
        ("prev_loc", "geography_point"),
        ("curr_loc", "geography_point"),
        ("last_updated_at", "timestamp"),
    ),
    ("user_id",),
    (ForeignKey("user_id", "volunteer_details", "user_id"),),
)

USER_LOCATIONS = Table(
    "user_locations",
    _cols(
        ("user_id", "varchar(255)", False),
        ("prev_loc", "geography_point"),
        ("curr_loc", "geography_point"),
        ("last_updated_at", "timestamp"),
    ),
    ("user_id",),
    (ForeignKey("user_id", "users", "user_id"),),
)

ORGANIZATIONS = Table(
    "organizations",
    _cols(
        ("org_id", "varchar(255)", False),
        ("org_name", "varchar(125)", False),
        ("street", "varchar(255)"),
        ("city_name", "varchar(100)"),
        ("state_id", "varchar(50)"),
        ("zip_code", "varchar(10)"),
        ("mission", "text"),
        ("web_url", "varchar(255)"),
        ("phone", "varchar(20)"),
        ("email", "varchar(255)"),
        ("org_type", "enum:org_type_enum"),
        ("org_size", "enum:org_size_enum"),
        ("org_rating", "int"),
        ("is_collaborator", "bool"),
        ("is_contributor", "bool"),
        ("created_at", "timestamp"),
        ("last_updated_at", "timestamp"),
    ),
    ("org_id",),
    (ForeignKey("state_id", "states", "state_id"),),
)

# Parents before children: this is also the generation and load order.
TABLES: Dict[str, Table] = {
    t.name: t
    for t in (
        COUNTRIES,
        STATES,
        CITIES,
        HELP_CATEGORIES,
        USERS,
        VOLUNTEER_DETAILS,
        USER_SKILLS,
        VOLUNTEER_LOCATIONS,
        USER_LOCATIONS,
        ORGANIZATIONS,
    )
}

# CHECK constraints from the DDL that the validator re-verifies row by row.
ORG_RATING_RANGE: Tuple[int, int] = (1, 5)
