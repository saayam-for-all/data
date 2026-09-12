from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GeneratorConfig:
    """
    Configuration for synthetic mock-data generation.

    The defaults are intended to create a reasonably sized dataset for
    dashboard development and API testing while keeping generation fast.
    """

    seed: int = 42

    users: int = 400
    organizations: int = 400

    cities_per_state: int = 10

    volunteer_ratio: float = 0.45
    user_location_ratio: float = 0.70
    volunteer_location_ratio: float = 1.00

    skills_per_user_min: int = 1
    skills_per_user_max: int = 3

    location_jitter_degrees: float = 0.08

    def validate(self) -> None:
        integer_fields = {
            "seed": self.seed,
            "users": self.users,
            "organizations": self.organizations,
            "cities_per_state": self.cities_per_state,
            "skills_per_user_min": self.skills_per_user_min,
            "skills_per_user_max": self.skills_per_user_max,
        }

        for field_name, value in integer_fields.items():
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{field_name} must be an integer")

        if self.users < 0:
            raise ValueError("users must be >= 0")

        if self.organizations < 0:
            raise ValueError("organizations must be >= 0")

        if self.cities_per_state <= 0:
            raise ValueError("cities_per_state must be > 0")

        if self.skills_per_user_min < 0:
            raise ValueError("skills_per_user_min must be >= 0")

        if self.skills_per_user_max < self.skills_per_user_min:
            raise ValueError(
                "skills_per_user_max must be >= skills_per_user_min"
            )

        ratio_fields = {
            "volunteer_ratio": self.volunteer_ratio,
            "user_location_ratio": self.user_location_ratio,
            "volunteer_location_ratio": self.volunteer_location_ratio,
        }

        for field_name, value in ratio_fields.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{field_name} must be numeric")

            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{field_name} must be between 0 and 1")

        if self.location_jitter_degrees <= 0:
            raise ValueError("location_jitter_degrees must be > 0")


DEFAULT_CONFIG = GeneratorConfig()