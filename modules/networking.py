"""Per-service network routing for VPN/proxy-sensitive environments."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

import requests


NetworkMode = Literal["auto", "direct", "system", "custom"]


@dataclass(frozen=True)
class ProbeResult:
    mode: str
    reachable: bool
    status_code: int | None
    elapsed_ms: int
    error: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "reachable": self.reachable,
            "status_code": self.status_code,
            "elapsed_ms": self.elapsed_ms,
            "error": self.error,
        }


def redact_proxy_url(value: str | None) -> str | None:
    if not value:
        return None
    parts = urlsplit(value)
    host = parts.hostname or ""
    port = f":{parts.port}" if parts.port else ""
    return urlunsplit((parts.scheme, f"{host}{port}", "", "", ""))


def build_session(mode: NetworkMode, proxy_server: str | None = None) -> requests.Session:
    session = requests.Session()
    if mode == "direct":
        session.trust_env = False
    elif mode == "custom":
        if not proxy_server:
            raise ValueError("custom network mode requires a proxy server")
        session.trust_env = False
        session.proxies.update({"http": proxy_server, "https": proxy_server})
    else:
        session.trust_env = True
    return session


def probe_http(
    url: str,
    mode: NetworkMode,
    proxy_server: str | None = None,
    timeout: float = 8.0,
) -> ProbeResult:
    started = time.perf_counter()
    try:
        session = build_session(mode, proxy_server)
        response = session.get(url, timeout=timeout, allow_redirects=True, stream=True)
        elapsed = int((time.perf_counter() - started) * 1000)
        return ProbeResult(mode, True, response.status_code, elapsed)
    except requests.RequestException as exc:
        elapsed = int((time.perf_counter() - started) * 1000)
        return ProbeResult(mode, False, None, elapsed, type(exc).__name__)


def choose_network_mode(
    url: str,
    requested: NetworkMode,
    proxy_server: str | None = None,
) -> tuple[str, list[ProbeResult]]:
    """Prefer a direct route, avoiding a VPN proxy that times out for MetaboAnalyst."""

    if requested != "auto":
        result = probe_http(url, requested, proxy_server)
        return requested, [result]

    probes = [probe_http(url, "direct")]
    if probes[0].reachable:
        return "direct", probes
    probes.append(probe_http(url, "system"))
    if probes[1].reachable:
        return "system", probes
    return "direct", probes


def chromium_network_options(mode: str, proxy_server: str | None = None) -> dict[str, object]:
    if mode == "direct":
        return {
            "args": [
                "--no-proxy-server",
                "--proxy-bypass-list=*;*.metaboanalyst.ca;*.xialab.ca",
            ]
        }
    if mode == "custom":
        if not proxy_server:
            raise ValueError("custom browser network mode requires --browser-proxy-server")
        return {"proxy": {"server": proxy_server}}
    return {}
