"""FastAPI wrapper for curl-based testability."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI
from pydantic import BaseModel, Field

from .config import GenerationConfig
from .generate_tables import MockDataGenerationService

app = FastAPI(title="Saayam Mock Data Generator", version="1.1.0")


class GenerateRequest(BaseModel):
    schema_path: str
    lookup_dir: str
    output_dir: str
    tables: List[str] = Field(default_factory=lambda: ["users", "request"])
    row_counts: Dict[str, int] = Field(default_factory=lambda: {"users": 5000, "request": 20000})
    seed: int = 42


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/generate")
def generate(payload: GenerateRequest) -> dict:
    config = GenerationConfig(
        schema_path=Path(payload.schema_path),
        lookup_dir=Path(payload.lookup_dir),
        output_dir=Path(payload.output_dir),
        seed=payload.seed,
        row_counts=payload.row_counts,
    )
    service = MockDataGenerationService(config)
    return service.generate(payload.tables)


@app.get("/validate")
def validate(
    schema_path: str,
    lookup_dir: str,
    output_dir: str,
    tables: str = "users,request",
    seed: Optional[int] = 42,
) -> dict:
    config = GenerationConfig(
        schema_path=Path(schema_path),
        lookup_dir=Path(lookup_dir),
        output_dir=Path(output_dir),
        seed=seed or 42,
        row_counts={},
    )
    service = MockDataGenerationService(config)
    return service.validate([table.strip() for table in tables.split(",") if table.strip()])
