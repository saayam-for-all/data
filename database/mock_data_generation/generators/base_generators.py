"""Generic and semantic value generators for schema-driven mock data."""

from __future__ import annotations

import random
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from faker import Faker


class BaseValueGenerator:
    """Generate realistic fallback values based on column name and data type."""

    def __init__(self, fake: Faker, rng: random.Random):
        self.fake = fake
        self.rng = rng

    def _seeded_uuid(self) -> str:
        """UUID4 backed by the seeded rng so output is reproducible across runs."""
        return str(uuid.UUID(int=self.rng.getrandbits(128), version=4))

    def _short_phone(self) -> str:
        """Phone number in (NNN) NNN-NNNN format (14 chars, fits varchar(20)).

        Avoids leading '+' because Excel auto-interprets it as a formula
        prefix and corrupts the display when the CSV is opened directly.
        """
        return f"({self.rng.randint(200, 999)}) {self.rng.randint(200, 999)}-{self.rng.randint(1000, 9999)}"

    def generate(
        self,
        column_name: str,
        data_type: str,
        max_length: Optional[int] = None,
    ):
        column_name = str(column_name).strip()
        col = column_name.lower()
        dtype = str(data_type).strip().lower()

        if self._is_boolean(dtype):
            return self.rng.choice([True, False])

        if self._is_timestamp(dtype):
            return self._random_timestamp()

        if self._is_date(dtype):
            return self._random_date()

        if self._is_integer(dtype):
            return self._generate_integer(col)

        if self._is_numeric(dtype):
            return self._generate_numeric(col)

        if self._is_json(dtype):
            return self._generate_json(col)

        return self._generate_string(col, max_length)

    # ------------------------------------------------------------------
    # Type detection
    # ------------------------------------------------------------------

    @staticmethod
    def _is_boolean(dtype: str) -> bool:
        return "boolean" in dtype

    @staticmethod
    def _is_timestamp(dtype: str) -> bool:
        return "timestamp" in dtype or dtype == "timest"

    @staticmethod
    def _is_date(dtype: str) -> bool:
        return dtype == "date"

    @staticmethod
    def _is_integer(dtype: str) -> bool:
        return any(token in dtype for token in ["integer", "bigint", "small int", "smallint", "int"])

    @staticmethod
    def _is_numeric(dtype: str) -> bool:
        return any(token in dtype for token in ["numeric", "decimal", "real", "double"])

    @staticmethod
    def _is_json(dtype: str) -> bool:
        return "json" in dtype

    # ------------------------------------------------------------------
    # Primitive generators
    # ------------------------------------------------------------------

    def _random_timestamp(self) -> str:
        start = datetime(2022, 1, 1, 0, 0, 0)
        end = datetime(2025, 12, 31, 23, 59, 59)
        delta_seconds = int((end - start).total_seconds())
        value = start + timedelta(seconds=self.rng.randint(0, delta_seconds))
        return value.strftime("%Y-%m-%d %H:%M:%S")

    def _random_date(self) -> str:
        start = date(1950, 1, 1)
        end = date(2007, 12, 31)
        delta_days = (end - start).days
        value = start + timedelta(days=self.rng.randint(0, delta_days))
        return value.strftime("%Y-%m-%d")

    def _generate_integer(self, col: str) -> int:
        if "stage" in col or "page" in col:
            return self.rng.randint(0, 6)

        if "age" in col:
            return self.rng.randint(18, 90)

        if "hours" in col:
            return self.rng.randint(1, 72)

        if "rating" in col:
            return self.rng.randint(1, 5)

        if "count" in col or "number" in col:
            return self.rng.randint(1, 500)

        return self.rng.randint(1, 1000)

    def _generate_numeric(self, col: str):
        if "latitude" in col or "lattitude" in col:
            return str(round(self.rng.uniform(-90, 90), 6))

        if "longitude" in col:
            return str(round(self.rng.uniform(-180, 180), 6))

        if "speaker" in col:
            return str(self.rng.randint(1, 1500))

        return str(Decimal(f"{self.rng.uniform(0, 9999):.2f}"))

    def _generate_json(self, col: str) -> str:
        if "permission" in col:
            return '["read", "write"]'

        if "skill" in col:
            return '["food_support", "transport", "translation"]'

        if "availability" in col:
            return '{"days":["Mon","Wed","Fri"],"time":"evening"}'

        if "profile_links" in col:
            return '{"website":"https://example.org"}'

        return "{}"

    # ------------------------------------------------------------------
    # Semantic string generation
    # ------------------------------------------------------------------

    def _generate_string(self, col: str, max_length: Optional[int]) -> str:
        value = self._semantic_string(col)
        return self._truncate(value, max_length)

    def _semantic_string(self, col: str) -> str:
        if col.endswith("_id") and "user" in col:
            return f"USR-{self._seeded_uuid()}"

        if col.endswith("_id") and ("req" in col or "request" in col):
            return f"REQ-{self._seeded_uuid()}"

        if col.endswith("_id") and "org" in col:
            return f"ORG-{self._seeded_uuid()}"

        if "email" in col:
            return self.fake.email()

        if "phone" in col or "mobile" in col:
            return self._short_phone()

        if col == "first_name":
            return self.fake.first_name()

        if col == "middle_name":
            return self.fake.first_name() if self.rng.random() < 0.35 else ""

        if col == "last_name":
            return self.fake.last_name()

        if "full_name" in col or col == "name":
            return self.fake.name()

        if "addr_ln1" in col or col == "street":
            return self.fake.street_address()

        if "addr_ln2" in col:
            return self.fake.secondary_address() if self.rng.random() < 0.4 else ""

        if "addr_ln3" in col:
            return ""

        if "city" in col:
            return self.fake.city()

        if "zip" in col or "postal" in col:
            return self.fake.postcode()

        if "country_code" in col:
            return self.fake.country_code()

        if "state_code" in col:
            return self.fake.state_abbr()

        if "time_zone" in col:
            return self.rng.choice(
                [
                    "America/New_York",
                    "America/Chicago",
                    "America/Denver",
                    "America/Los_Angeles",
                    "Europe/London",
                    "Europe/Berlin",
                    "Asia/Kolkata",
                    "Asia/Tokyo",
                ]
            )

        if "location" in col or col == "req_loc":
            return f"{self.fake.city()}, {self.fake.state_abbr()}"

        if col == "gender" or "gender" in col:
            return self.rng.choice(
                ["MALE", "FEMALE", "NON_BINARY", "PREFER_NOT_TO_SAY"]
            )

        if "language" in col:
            return self.rng.choice(
                ["English", "Spanish", "Hindi", "French", "Arabic"]
            )

        if "provider" in col and "auth" in col:
            return self.rng.choice(
                ["GOOGLE", "FACEBOOK", "APPLE", "MICROSOFT", "EMAIL"]
            )

        if "picture" in col or "path" in col:
            return ""

        # Audio request description: most requests are typed, not voice-recorded.
        # When present, it would be a transcript — not Faker word salad.
        if col == "audio_req_desc":
            if self.rng.random() < 0.90:
                return ""
            return self.rng.choice([
                "I need help with grocery shopping this week, my mobility is limited.",
                "Looking for someone to drive me to a medical appointment Tuesday morning.",
                "Need a volunteer to help fill out housing application forms.",
                "Requesting tutoring support for my child in middle school math.",
                "Hoping to find help moving some furniture this weekend.",
            ])

        # Document link: most requests don't attach a doc.
        if col == "req_doc_link":
            if self.rng.random() < 0.80:
                return ""
            return f"/uploads/req/{self.rng.randint(10000, 99999)}.pdf"

        if col == "req_subj":
            return self.rng.choice(
                [
                    "Need help with grocery shopping",
                    "Require transportation to hospital",
                    "Looking for food assistance",
                    "Need tutoring support",
                    "Need help setting up smartphone",
                    "Require medication delivery",
                    "Need urgent house repair help",
                ]
            )

        if col == "req_desc":
            return self.rng.choice(
                [
                    "Urgently need assistance with this request. Please contact me as soon as possible.",
                    "This is a non urgent request but volunteer support would be very helpful.",
                    "Looking for support on behalf of a family member who needs assistance.",
                    "Please reach out by phone or message to coordinate details.",
                    "Flexible on timing and available on most weekday afternoons.",
                ]
            )

        if "desc" in col or "description" in col:
            return self.fake.sentence(nb_words=10)

        if "reason" in col:
            return self.fake.sentence(nb_words=8)

        if "message" in col:
            return self.fake.paragraph(nb_sentences=2)

        if "headline" in col:
            return self.fake.sentence(nb_words=6)

        if "snippet" in col:
            return self.fake.paragraph(nb_sentences=2)

        if "subject" in col:
            return self.fake.sentence(nb_words=6)

        if "status" in col:
            return self.rng.choice(["ACTIVE", "INACTIVE", "PENDING"])

        if "type" in col:
            return self.fake.word().upper()

        if "role" in col:
            return self.rng.choice(["ADMIN", "VOLUNTEER", "BENEFICIARY", "STEWARD"])

        if "code" in col:
            return self.fake.bothify(text="??##").upper()

        if "url" in col or "link" in col:
            return self.fake.url()

        if "mission" in col:
            return self.fake.paragraph(nb_sentences=3)

        if "feedback" in col:
            return self.fake.sentence(nb_words=12)

        if "comment" in col:
            return self.fake.sentence(nb_words=12)

        if "locale" in col:
            return self.rng.choice(["en_US", "es_ES", "hi_IN", "fr_FR"])

        if "direction" in col:
            return self.rng.choice(["LTR", "RTL"])

        if "value" in col:
            return self.fake.word()

        return self.fake.word()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _truncate(value: str, max_length: Optional[int]) -> str:
        if max_length is None:
            return value
        return value[:max_length]