"""Upload 30 mapping queries and inventory the NameMap paginator."""

import argparse
from pathlib import Path

from modules.input_validator import validate_mapping_table
from modules.pathway_browser import PathwayAnalysisBrowser


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--test-views", action="store_true")
    args = parser.parse_args()
    validation = validate_mapping_table("name_map.csv")
    names = list(validation.feature_names[: args.limit])
    output = Path("runs/diagnostics")
    output.mkdir(parents=True, exist_ok=True)
    browser = PathwayAnalysisBrowser(
        headless=False,
        network_mode="direct",
        browser_channel="chrome",
        timeout_ms=120_000,
    ).start()
    try:
        browser.upload_compound_list(names)
        page = browser.page
        assert page is not None
        (output / "paginator_page.html").write_text(page.content(), encoding="utf-8")
        rows = browser.read_mapping_rows()
        print(f"ALL ROWS: {len(rows)}")
        print(f"QUERY PAGES: {browser.mapping_query_pages}")
        if [row["Query"] for row in rows] != names:
            raise RuntimeError("paginated mapping rows did not preserve the input order")
        if args.test_views:
            first_candidates = browser.inspect_candidates(names[0])
            print(
                f"FIRST-PAGE VIEW: {names[0]!r}, candidates={len(first_candidates)}, "
                f"active_page={browser._active_mapping_page()}"
            )
            last_candidates = browser.inspect_candidates(names[-1])
            print(
                f"LAST-PAGE VIEW: {names[-1]!r}, candidates={len(last_candidates)}, "
                f"active_page={browser._active_mapping_page()}"
            )
        table = browser._mapping_table()
        print(f"CURRENT VISIBLE ROWS: {table.locator(':scope > tbody > tr').count()}")
        print("PAGINATORS:")
        print(
            page.locator(".ui-paginator").evaluate_all(
                "els => els.map(el => ({id: el.id, className: el.className, text: el.innerText, html: el.outerHTML}))"
            )
        )
        print("SELECTS:")
        print(
            page.locator("select").evaluate_all(
                "els => els.map(el => ({id: el.id, className: el.className, value: el.value, "
                "options: [...el.options].map(o => ({text: o.textContent.trim(), value: o.value}))}))"
            )
        )
    finally:
        browser.close()


if __name__ == "__main__":
    main()
