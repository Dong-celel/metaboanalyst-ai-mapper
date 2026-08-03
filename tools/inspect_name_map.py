"""Upload public names and inventory the live NameMapView DOM."""

from pathlib import Path

from modules.pathway_browser import PathwayAnalysisBrowser


PUBLIC_NAMES = [
    "1,3-Diaminopropane",
    "2-Ketobutyric acid",
    "No Match",
    "Beta-Alanine",
]


def main() -> None:
    output = Path("runs/diagnostics")
    output.mkdir(parents=True, exist_ok=True)
    browser = PathwayAnalysisBrowser(
        headless=False,
        network_mode="direct",
        browser_channel="chrome",
        timeout_ms=90_000,
    ).start()
    try:
        browser.upload_compound_list(PUBLIC_NAMES)
        page = browser.page
        assert page is not None
        page.screenshot(path=str(output / "name_map_page.png"), full_page=True)
        (output / "name_map_page.html").write_text(page.content(), encoding="utf-8")
        print(f"URL: {page.url}")
        tables = page.locator("table")
        print(f"TABLES: {tables.count()}")
        for index in range(tables.count()):
            table = tables.nth(index)
            headers = table.locator("thead th").all_text_contents()
            rows = table.locator("tbody tr")
            if headers or table.get_by_text("View", exact=True).count():
                print(
                    {
                        "index": index,
                        "id": table.get_attribute("id"),
                        "class": table.get_attribute("class"),
                        "visible": table.is_visible(),
                        "headers": headers,
                        "rows": rows.count(),
                        "views": table.get_by_text("View", exact=True).count(),
                        "first_rows": rows.nth(0).locator("td").all_text_contents() if rows.count() else [],
                    }
                )
    finally:
        browser.close()


if __name__ == "__main__":
    main()
