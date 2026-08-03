"""Upload the public concentration fixture and inventory SanityCheck.xhtml."""

from pathlib import Path

from modules.input_validator import validate_concentration_table
from modules.pathway_browser import PathwayAnalysisBrowser


def main() -> None:
    output = Path("runs/diagnostics")
    output.mkdir(parents=True, exist_ok=True)
    fixture = validate_concentration_table("tests/fixtures/pathway_small.csv")
    browser = PathwayAnalysisBrowser(
        headless=False,
        network_mode="direct",
        browser_channel="chrome",
        timeout_ms=90_000,
    ).start()
    try:
        # Stop after the first upload transition so the intermediate page can
        # be inspected independently of wait_for_name_check().
        browser.wait_for_name_check = lambda: None  # type: ignore[method-assign]
        browser.upload_concentration_table(fixture.path)
        page = browser.page
        assert page is not None
        page.screenshot(path=str(output / "sanity_check.png"), full_page=True)
        (output / "sanity_check.html").write_text(page.content(), encoding="utf-8")
        print(f"URL: {page.url}")
        print(page.locator("body").inner_text())
        print("CONTROLS:")
        print(
            page.locator("button, input[type=submit], a").evaluate_all(
                "els => els.map(el => ({"
                "tag: el.tagName, id: el.id, text: (el.innerText || el.value || '').trim(), "
                "href: el.getAttribute('href'), visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length)"
                "})).filter(x => x.visible && (x.text || x.id))"
            )
        )
    finally:
        browser.close()


if __name__ == "__main__":
    main()
