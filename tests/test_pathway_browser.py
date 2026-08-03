from modules.pathway_browser import _website_query_equivalent, candidate_from_cells


def test_candidate_table_parser_uses_headers_not_positions():
    candidate = candidate_from_cells(
        ["", "Hit", "PubChem", "HMDB", "KEGG", "ChEBI", "MetLin"],
        ["", "Fumaric acid", "444972", "HMDB0000134", "C00122", "CHEBI:18012", "NA"],
        "choice-1",
        0,
    )
    assert candidate["name"] == "Fumaric acid"
    assert candidate["pubchem"] == "444972"
    assert candidate["hmdb"] == "HMDB0000134"
    assert candidate["selection_key"] == "choice-1"


def test_website_query_equivalence_allows_only_observed_trailing_stripping():
    assert _website_query_equivalent("Fema No. 3989, 3-Hydroxy-", "Fema No. 3989, 3-Hydroxy")
    assert _website_query_equivalent("Hexose +", "Hexose")
    assert _website_query_equivalent(
        "4-(4-Hydroxyphenyl)-2-butanone O-[2-galloylglucoside]",
        "4-(4-Hydroxyphenyl)-2-butanone O-[2-galloylglucoside",
    )
    assert not _website_query_equivalent("Estradiol", "Estriol")
    assert not _website_query_equivalent("A-B", "AB")
