import requests

from modules.mapping_clients import KeggPathwayClient, normalize_map_response


def test_normalize_list_response():
    assert normalize_map_response([{"Query": "A"}]) == [{"Query": "A"}]


def test_normalize_wrapped_response():
    assert normalize_map_response({"results": [{"Query": "A"}]}) == [{"Query": "A"}]


def test_normalize_column_oriented_response():
    assert normalize_map_response({"Query": ["A", "B"], "HMDB": ["H1", "H2"]}) == [
        {"Query": "A", "HMDB": "H1"},
        {"Query": "B", "HMDB": "H2"},
    ]


class FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


class FakeKeggSession:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []

    def get(self, url, timeout):
        self.calls.append((url, timeout))
        if self.fail:
            raise requests.Timeout("offline")
        if "/link/pathway/" in url:
            return FakeResponse("cpd:C00031\tpath:map00010\n")
        return FakeResponse("path:map00010\tGlycolysis / Gluconeogenesis\n")


def test_kegg_pathway_evidence_is_resolved_and_cached():
    session = FakeKeggSession()
    cache = {}
    client = KeggPathwayClient(session=session, cache=cache)
    evidence = client.evidence("C00031")
    assert evidence["status"] == "linked"
    assert evidence["pathways"][0]["id"] == "map00010"
    client.evidence("C00031")
    assert len(session.calls) == 2
    assert cache


def test_kegg_failure_is_nonfatal_and_cached():
    client = KeggPathwayClient(session=FakeKeggSession(fail=True))
    evidence = client.evidence("C00031")
    assert evidence["status"] == "unavailable"
    assert evidence["error"] == "Timeout"


def test_commercial_default_can_use_kegg_id_without_api_request():
    session = FakeKeggSession()
    client = KeggPathwayClient(session=session, enabled=False)
    evidence = client.evidence("C00031")
    assert evidence["status"] == "id_only"
    assert evidence["kegg_ids"] == ["C00031"]
    assert session.calls == []
