"""Inventory a live View dialog for one non-exact compound name."""

import argparse
from pathlib import Path

from modules.pathway_browser import PathwayAnalysisBrowser


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("query", nargs="?", default="Pectinolide C")
    args = parser.parse_args()
    query = args.query
    output = Path("runs/diagnostics")
    output.mkdir(parents=True, exist_ok=True)
    browser = PathwayAnalysisBrowser(
        headless=False,
        network_mode="direct",
        browser_channel="chrome",
        timeout_ms=90_000,
    ).start()
    try:
        browser.upload_compound_list([query])
        dialog = browser._open_view(query)
        page = browser.page
        assert page is not None
        page.screenshot(path=str(output / "view_dialog.png"), full_page=True)
        (output / "view_dialog.html").write_text(dialog.evaluate("el => el.outerHTML"), encoding="utf-8")
        print("DIALOG TEXT:")
        print(dialog.inner_text())
        print("PARSED CANDIDATES:")
        for candidate in browser._parse_dialog(dialog):
            print(candidate)
        print("INPUTS:")
        print(
            dialog.locator("input").evaluate_all(
                "els => els.map(el => ({id: el.id, type: el.type, value: el.value, name: el.name}))"
            )
        )
        print("TABLES:")
        tables = dialog.locator("table")
        for index in range(tables.count()):
            table = tables.nth(index)
            print(
                {
                    "index": index,
                    "headers": table.locator(":scope > thead > tr > th").all_text_contents(),
                    "direct_rows": table.locator(":scope > tbody > tr").count(),
                    "all_rows": table.locator("tbody tr").count(),
                    "radios": table.locator("input[type=radio]").count(),
                    "checkboxes": table.locator("input[type=checkbox]").count(),
                }
            )
    finally:
        browser.close()


if __name__ == "__main__":
    main()
