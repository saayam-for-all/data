"""Cache public FCDO source documents for offline, country-by-country review.

This collector does not certify or publish contacts. Its output is research
material in the ignored raw-data directory. Review the emergency-service
sections before adding records to the curated contacts.
"""

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

OUTPUT_DIR = Path(__file__).resolve().parents[3] / "datasets/raw/official_emergency_sources"
INDEX_URL = "https://www.gov.uk/api/content/foreign-travel-advice"


def collect_sources():
    """Download each indexed public country document once, with six workers."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    response = requests.get(INDEX_URL, timeout=30)
    response.raise_for_status()
    index = response.json()
    (OUTPUT_DIR / "index.json").write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")

    def fetch(entry):
        slug = entry["base_path"].rsplit("/", 1)[-1]
        if not re.fullmatch(r"[a-z0-9-]+", slug):
            raise ValueError(f"Unexpected country slug: {slug}")
        target = OUTPUT_DIR / f"{slug}.json"
        if target.exists():
            return slug, "cached"
        url = "https://www.gov.uk/api/content" + entry["base_path"]
        document = requests.get(url, timeout=30)
        document.raise_for_status()
        content = document.json()
        if content.get("document_type") != "travel_advice":
            raise ValueError(f"Unexpected document type for {slug}")
        target.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
        return slug, "downloaded"

    errors = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        jobs = {pool.submit(fetch, entry): entry["base_path"] for entry in index["links"]["children"]}
        for count, future in enumerate(as_completed(jobs), 1):
            try:
                future.result()
            except Exception as error:
                errors.append({"path": jobs[future], "error": str(error)})
            if count % 25 == 0:
                print(f"Processed {count}/{len(jobs)} countries", flush=True)
    print(json.dumps({"documents": len(jobs), "errors": errors}), flush=True)


if __name__ == "__main__":
    collect_sources()
