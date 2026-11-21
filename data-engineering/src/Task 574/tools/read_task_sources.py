"""Download public, read-only task references; never call a write API."""

import json
from pathlib import Path
from urllib.request import Request, urlopen


def main():
    """Save authoritative Task 1 attachments and print PR discussion only."""
    destination = Path(__file__).resolve().parents[1] / "references"
    destination.mkdir(exist_ok=True)
    attachments = {
        "saayam_schema.sql": "https://github.com/user-attachments/files/33914221/saayam_schema.sql",
        "requests_reference_columns.xlsx": "https://github.com/user-attachments/files/34229000/requests_reference_columns.xlsx",
    }
    for name, url in attachments.items():
        request = Request(url, headers={"User-Agent": "task574-local-development"})
        with urlopen(request, timeout=30) as response:
            data = response.read()
        (destination / name).write_bytes(data)
        print(f"Saved {name}: {len(data)} bytes from {url}")
    for number in (633, 647):
        url = f"https://api.github.com/repos/saayam-for-all/data/issues/{number}/comments"
        with urlopen(Request(url, headers={"User-Agent": "task574-local-development"}), timeout=30) as response:
            comments = json.load(response)
        for comment in comments:
            print(json.dumps({"url": comment["html_url"], "author": comment["user"]["login"], "body": comment["body"]}))


if __name__ == "__main__":
    main()
