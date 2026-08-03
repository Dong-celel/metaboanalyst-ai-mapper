"""Official MetaboAnalyst, PubChem, and KEGG evidence helpers."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from urllib.parse import quote

import requests

from config import (
    KEGG_REST_BASE_URL,
    MAP_API_CHUNK_SIZE,
    METABOANALYST_MAP_URL,
    PUBCHEM_BASE_URL,
    REQUEST_TIMEOUT,
)
from .networking import NetworkMode, build_session


def _chunks(values: list[str], size: int) -> Iterable[list[str]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def normalize_map_response(payload: Any) -> list[dict[str, Any]]:
    """Accept the list and column-oriented shapes used by mapcompounds versions."""

    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []

    for key in ("results", "result", "data", "matches"):
        nested = payload.get(key)
        if isinstance(nested, list):
            return [dict(item) for item in nested if isinstance(item, dict)]

    list_columns = {key: value for key, value in payload.items() if isinstance(value, list)}
    if list_columns:
        size = max((len(value) for value in list_columns.values()), default=0)
        return [
            {key: (value[index] if index < len(value) else None) for key, value in list_columns.items()}
            for index in range(size)
        ]

    if payload:
        return [dict(payload)]
    return []


class MetaboAnalystMapClient:
    def __init__(
        self,
        network_mode: NetworkMode = "direct",
        proxy_server: str | None = None,
        session: requests.Session | None = None,
    ):
        self.session = session or build_session(network_mode, proxy_server)

    def map_names(self, names: list[str]) -> dict[str, dict[str, Any]]:
        mapped: dict[str, dict[str, Any]] = {}
        for chunk in _chunks(names, MAP_API_CHUNK_SIZE):
            response = self.session.post(
                METABOANALYST_MAP_URL,
                json={"queryList": ";".join(chunk), "inputType": "name"},
                headers={"Content-Type": "application/json", "cache-control": "no-cache"},
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            rows = normalize_map_response(response.json())
            for index, row in enumerate(rows):
                query = str(
                    row.get("query")
                    or row.get("Query")
                    or row.get("input")
                    or (chunk[index] if index < len(chunk) else "")
                ).strip()
                if query:
                    mapped[query] = row
        return mapped


class PubChemSynonymClient:
    def __init__(
        self,
        network_mode: NetworkMode = "direct",
        proxy_server: str | None = None,
        session: requests.Session | None = None,
    ):
        self.session = session or build_session(network_mode, proxy_server)
        self.cache: dict[str, list[str]] = {}

    def synonyms(self, cid: str | int | None) -> list[str]:
        cid_text = str(cid or "").strip()
        if not cid_text or cid_text.upper() == "NA":
            return []
        if cid_text in self.cache:
            return self.cache[cid_text]
        url = f"{PUBCHEM_BASE_URL}/compound/cid/{quote(cid_text)}/synonyms/JSON"
        try:
            response = self.session.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            info = response.json().get("InformationList", {}).get("Information", [])
            values = info[0].get("Synonym", []) if info else []
            result = [str(value) for value in values[:200]]
        except (requests.RequestException, ValueError, KeyError, TypeError):
            result = []
        self.cache[cid_text] = result
        return result


class KeggPathwayClient:
    """Resolve website-provided KEGG compound IDs to reference pathways."""

    def __init__(
        self,
        network_mode: NetworkMode = "direct",
        proxy_server: str | None = None,
        session: requests.Session | None = None,
        cache: dict[str, dict[str, Any]] | None = None,
        enabled: bool = True,
    ):
        self.session = session or build_session(network_mode, proxy_server)
        self.cache = cache if cache is not None else {}
        self.enabled = enabled

    @staticmethod
    def compound_ids(value: str | None) -> list[str]:
        import re

        return list(dict.fromkeys(re.findall(r"\bC\d{5}\b", str(value or ""), re.I)))

    def evidence(self, value: str | None) -> dict[str, Any]:
        ids = [item.upper() for item in self.compound_ids(value)]
        cache_key = "+".join(ids)
        if not ids:
            return {"status": "no_kegg", "kegg_ids": [], "pathways": [], "error": ""}
        if cache_key in self.cache:
            return dict(self.cache[cache_key])
        if not self.enabled:
            result = {
                "status": "id_only",
                "kegg_ids": ids,
                "pathways": [],
                "error": "",
            }
            self.cache[cache_key] = result
            return dict(result)

        pathway_ids: list[str] = []
        try:
            for compound_id in ids:
                response = self.session.get(
                    f"{KEGG_REST_BASE_URL}/link/pathway/cpd:{compound_id}",
                    timeout=REQUEST_TIMEOUT,
                )
                response.raise_for_status()
                for line in response.text.splitlines():
                    cells = line.split("\t")
                    if len(cells) >= 2:
                        pathway_id = cells[1].removeprefix("path:").strip()
                        if pathway_id and pathway_id not in pathway_ids:
                            pathway_ids.append(pathway_id)

            names: dict[str, str] = {}
            for chunk in _chunks(pathway_ids, 10):
                response = self.session.get(
                    f"{KEGG_REST_BASE_URL}/list/{'+'.join(chunk)}",
                    timeout=REQUEST_TIMEOUT,
                )
                response.raise_for_status()
                for line in response.text.splitlines():
                    cells = line.split("\t", 1)
                    if len(cells) == 2:
                        names[cells[0].removeprefix("path:").strip()] = cells[1].strip()
            pathways = [
                {"id": pathway_id, "name": names.get(pathway_id, pathway_id)}
                for pathway_id in pathway_ids
            ]
            result = {
                "status": "linked" if pathways else "no_link",
                "kegg_ids": ids,
                "pathways": pathways,
                "error": "",
            }
        except requests.RequestException as exc:
            result = {
                "status": "unavailable",
                "kegg_ids": ids,
                "pathways": [],
                "error": type(exc).__name__,
            }
        self.cache[cache_key] = result
        return dict(result)
