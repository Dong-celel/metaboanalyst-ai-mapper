"""Print a compact live-page inventory when MetaboAnalyst changes its UI."""

from pathlib import Path

from playwright.sync_api import sync_playwright

from config import METABOANALYST_PATHWAY_UPLOAD_URL


def main() -> None:
    output = Path("runs/diagnostics")
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            channel="chrome",
            headless=False,
            args=["--no-proxy-server", "--proxy-bypass-list=*"],
        )
        page = browser.new_page()
        page.goto(METABOANALYST_PATHWAY_UPLOAD_URL, wait_until="domcontentloaded", timeout=120_000)
        page.screenshot(path=str(output / "upload_page.png"), full_page=True)
        (output / "upload_page.html").write_text(page.content(), encoding="utf-8")
        print(f"URL: {page.url}")
        print(f"TITLE: {page.title()}")
        print(f"FRAMES: {[frame.url for frame in page.frames]}")
        print("INPUTS:")
        for item in page.locator("input").evaluate_all(
            """els => els.map(el => ({
                id: el.id, type: el.type, name: el.name, value: el.value,
                accept: el.accept, className: el.className,
                visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length)
            }))"""
        ):
            print(item)
        print("SELECTS:")
        for item in page.locator("select").evaluate_all(
            """els => els.map(el => ({
                id: el.id, name: el.name,
                options: [...el.options].map(o => ({label: o.textContent.trim(), value: o.value}))
            }))"""
        ):
            print(item)
        print("BUTTONS/LINKS:")
        for item in page.locator("button, input[type=submit], a").evaluate_all(
            """els => els.map(el => ({
                tag: el.tagName, id: el.id, text: (el.innerText || el.value || '').trim(),
                href: el.getAttribute('href'), className: el.className
            })).filter(x => x.text || x.id).slice(0, 100)"""
        ):
            print(item)
        browser.close()


if __name__ == "__main__":
    main()
