"""Application configuration loaded from environment variables.

Secrets must never be committed to this repository.  Set ``DEEPSEEK_API_KEY``
in the environment (or in a local, ignored ``.env`` file loaded by the shell)
before running the website workflow.
"""

from __future__ import annotations

import os


# DeepSeek uses an OpenAI-compatible API.  Read the key dynamically so the
# CLI can place a getpass() value into this process environment after imports.
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
DEEPSEEK_REASONING_EFFORT = os.getenv("DEEPSEEK_REASONING_EFFORT", "high")
_thinking_override = os.getenv("DEEPSEEK_THINKING_ENABLED", "").strip().casefold()
DEEPSEEK_THINKING_ENABLED = (
    _thinking_override in {"1", "true", "yes", "on"}
    if _thinking_override
    else DEEPSEEK_MODEL.casefold() == "deepseek-v4-pro"
)

# Public services used only for compound names and identifiers.
PUBCHEM_BASE_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
KEGG_REST_BASE_URL = "https://rest.kegg.jp"
HMDB_BASE_URL = "https://hmdb.ca"
METABOANALYST_MAP_URL = "https://rest.xialab.ca/api/mapcompounds"
METABOANALYST_PATHWAY_UPLOAD_URL = (
    "https://www.metaboanalyst.ca/MetaboAnalyst/upload/PathUploadView.xhtml"
)

# Network and matching defaults.
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "30"))
MAX_CANDIDATES = int(os.getenv("MAX_CANDIDATES", "10"))
ENABLE_CACHE = True
OUTPUT_SUFFIX = "_matched"
GENERATE_REPORT = True

AUTO_LOCAL_SCORE = float(os.getenv("AUTO_LOCAL_SCORE", "0.95"))
AUTO_AI_CONFIDENCE = float(os.getenv("AUTO_AI_CONFIDENCE", "0.90"))
AUTO_SCORE_MARGIN = float(os.getenv("AUTO_SCORE_MARGIN", "0.15"))
MAP_API_CHUNK_SIZE = int(os.getenv("MAP_API_CHUNK_SIZE", "100"))
BROWSER_TIMEOUT_MS = int(os.getenv("BROWSER_TIMEOUT_MS", "120000"))


def deepseek_api_key() -> str:
    """Read the current process key without caching or persisting it."""

    return os.getenv("DEEPSEEK_API_KEY", "").strip()


def deepseek_is_configured() -> bool:
    """Return whether an API key is available without exposing its value."""

    return bool(deepseek_api_key())
