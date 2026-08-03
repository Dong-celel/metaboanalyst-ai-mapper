import os

import pytest

from modules.input_validator import validate_concentration_table
from modules.networking import choose_network_mode
from modules.pathway_browser import PathwayAnalysisBrowser
from config import METABOANALYST_PATHWAY_UPLOAD_URL


@pytest.mark.live
@pytest.mark.skipif(
    os.getenv("RUN_LIVE_METABOANALYST") != "1",
    reason="set RUN_LIVE_METABOANALYST=1 to upload the public fixture",
)
def test_public_fixture_reaches_name_check():
    fixture = validate_concentration_table("tests/fixtures/pathway_small.csv")
    mode, probes = choose_network_mode(METABOANALYST_PATHWAY_UPLOAD_URL, "auto")
    assert any(probe.reachable for probe in probes), probes
    browser = PathwayAnalysisBrowser(
        headless=False,
        network_mode=mode,
        browser_channel="chrome",
    ).start()
    try:
        browser.upload_concentration_table(fixture.path)
        rows = browser.read_mapping_rows()
        assert [row["Query"] for row in rows] == list(fixture.feature_names)
    finally:
        browser.close()
