"""Take browser screenshots of the actual local execution report, offline."""

import argparse
from pathlib import Path


def main():
    """Capture validation and CSV preview sections without opening external URLs."""
    from playwright.sync_api import sync_playwright

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", default="chrome", help="Installed browser channel, e.g. chrome or msedge")
    args = parser.parse_args()
    evidence = Path(__file__).resolve().parents[1] / "evidence"
    report = evidence / "report.html"
    if not report.exists():
        raise SystemExit("Run local_run.py first")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=args.channel, headless=True)
        try:
            page = browser.new_page(viewport={"width": 1540, "height": 1100}, device_scale_factor=1)
            page.route("http://**/*", lambda route: route.abort())
            page.route("https://**/*", lambda route: route.abort())
            page.goto(report.as_uri(), wait_until="load")
            for section, filename in (("execution", "execution.png"), ("export", "export.png")):
                target = evidence / filename
                page.locator(f"#{section}").screenshot(path=str(target))
                print(f"Saved browser screenshot: {target.name}")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
