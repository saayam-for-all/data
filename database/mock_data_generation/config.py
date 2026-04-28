"""Configuration helpers for schema-driven mock data generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict


@dataclass(slots=True)
class GenerationConfig:
    """Runtime configuration for the generator."""

    schema_path: Path
    lookup_dir: Path
    output_dir: Path
    seed: int = 42
    row_counts: Dict[str, int] = field(
        default_factory=lambda: {"users": 5000, "request": 20000}
    )

    def resolve(self) -> "GenerationConfig":
        """Return a copy-like resolved config with absolute paths."""
        self.schema_path = self.schema_path.resolve()
        self.lookup_dir = self.lookup_dir.resolve()
        self.output_dir = self.output_dir.resolve()
        return self
