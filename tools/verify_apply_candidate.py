"""Live regression: apply one unambiguous View choice and verify its row."""

from modules.pathway_browser import PathwayAnalysisBrowser


def main() -> None:
    query = "17beta Estradiol"
    browser = PathwayAnalysisBrowser(
        headless=False,
        network_mode="direct",
        browser_channel="chrome",
        timeout_ms=90_000,
    ).start()
    try:
        # Multiple rows reproduce the duplicate-dialog DOM emitted by the live
        # page, while the query itself is a non-exact spelling from name_map.csv.
        browser.upload_compound_list(
            [query, "Pectinolide C", "Homaxinolide A", "Gelomulide I"]
        )
        candidates = browser.inspect_candidates(query)
        selected = [candidate for candidate in candidates if candidate["name"] == "Estradiol"]
        if len(selected) != 1:
            raise RuntimeError(f"expected one Estradiol candidate, found {len(selected)}")
        result = browser.apply_candidate(query, selected[0])
        print(result)
        if result["Match"] != "Estradiol" or result["Comment"] != "1":
            raise RuntimeError(f"website did not confirm the expected mapping: {result}")
    finally:
        browser.close()


if __name__ == "__main__":
    main()
