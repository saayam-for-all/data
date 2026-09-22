"""Export one national number per ISO code for the lead's simplified format."""

from collections import Counter

if __package__:
    from .build_emergency_numbers import BASE_DIR, build_with_provenance, save_dataset
else:
    from build_emergency_numbers import BASE_DIR, build_with_provenance, save_dataset

OUTPUT_FILE = BASE_DIR / "datasets/cleaned/emergency_numbers_single.json"
REPORT_FILE = BASE_DIR / "datasets/cleaned/emergency_numbers_single_provenance.json"


def select_single_numbers(dataset):
    """Prefer general emergency, then national police; otherwise emit blank.

    Regional, mobile-only and other restricted contacts are not national
    fallbacks. A police fallback is not a claim of combined-service dispatch.
    """
    numbers, selected_services = {}, {}
    for code, country in sorted(dataset.items()):
        national = country["default"]
        service = next((key for key in ("general_emergency", "police")
                        if national.get(key)), None)
        numbers[code] = national[service] if service else ""
        selected_services[code] = service
    return numbers, selected_services


def build_single_numbers():
    """Rebuild from reviewed inputs and retain the selected contact's source."""
    dataset, provenance = build_with_provenance()
    numbers, services = select_single_numbers(dataset)
    indexed = {tuple(row["path"]): row for row in provenance["contacts"]}
    report = {
        "selection_rule": "general_emergency, otherwise national police, otherwise empty string",
        "police_fallback_note": "Police numbers may not provide ambulance or fire assistance.",
        "source_counts": dict(Counter(service or "blank" for service in services.values())),
        "countries_without_number": [code for code, number in numbers.items() if not number],
        "contacts": [],
    }
    for code, service in services.items():
        if service:
            report["contacts"].append({
                "country": code, "selected_service": service,
                **indexed[(code, "default", service)],
            })
    return numbers, report


if __name__ == "__main__":
    numbers, report = build_single_numbers()
    save_dataset(numbers, OUTPUT_FILE)
    save_dataset(report, REPORT_FILE)
    print(f"Exported {len(numbers)} ISO entries: {report['source_counts']}")
