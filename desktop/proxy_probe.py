"""Runtime probe for Catalogue Manager's app-scoped proxy."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import requests

from desktop import app_launcher
from desktop.network_config import AppProxyConfig, load_app_proxy_config

TRACE_URL = "https://www.cloudflare.com/cdn-cgi/trace"
DANBOORU_PROBE_URL = "https://danbooru.donmai.us/tags.json"


@contextmanager
def _ensure_local_proxy(config: AppProxyConfig) -> Iterator[None]:
    already_running = app_launcher._port_is_open(config.listen_host, config.listen_port)
    if not already_running:
        app_launcher._start_proxy_endpoint(config)
    try:
        yield
    finally:
        if not already_running:
            app_launcher._stop_proxy_endpoint()


def _trace(session: requests.Session) -> dict[str, str]:
    response = session.get(TRACE_URL, timeout=15)
    response.raise_for_status()
    result: dict[str, str] = {}
    for line in response.text.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key] = value
    return result


def _direct_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    return session


def _proxy_session(config: AppProxyConfig) -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    session.proxies.update(
        {
            "http": config.danbooru_proxy_url,
            "https": config.danbooru_proxy_url,
        }
    )
    return session


def run_probe(config: AppProxyConfig | None = None) -> int:
    config = config or load_app_proxy_config()
    if not config.enabled:
        print("[probe] App proxy is disabled. Enable it in input/network.env.")
        return 2

    config.validate()
    with _ensure_local_proxy(config):
        direct = _trace(_direct_session())
        proxied_session = _proxy_session(config)
        proxied = _trace(proxied_session)
        danbooru = proxied_session.get(
            DANBOORU_PROBE_URL,
            params={"limit": 1},
            timeout=20,
        )
        danbooru.raise_for_status()

    direct_ip = direct.get("ip", "unknown")
    direct_country = direct.get("loc", "unknown").upper()
    proxy_ip = proxied.get("ip", "unknown")
    proxy_country = proxied.get("loc", "unknown").upper()
    expected_country = config.expected_country.strip().upper()

    print(f"[probe] direct : {direct_ip} ({direct_country})")
    print(f"[probe] proxy  : {proxy_ip} ({proxy_country})")
    print(f"[probe] expected proxy country: {expected_country or 'ANY'}")
    print(f"[probe] Danbooru via proxy: HTTP {danbooru.status_code}")

    if direct_ip == "unknown" or proxy_ip == "unknown":
        print("[probe] FAILED: could not read public IP from trace endpoint.")
        return 3
    if direct_ip == proxy_ip:
        print("[probe] FAILED: direct and proxy public IP are identical.")
        return 4
    if expected_country and proxy_country != expected_country:
        print(
            f"[probe] FAILED: proxy country is {proxy_country}, expected {expected_country}."
        )
        return 5

    print(
        "[probe] OK: app proxy uses the expected exit country while the direct "
        "connection remains separate."
    )
    return 0


def main() -> None:
    try:
        raise SystemExit(run_probe())
    except (OSError, RuntimeError, ValueError, requests.RequestException) as exc:
        print(f"[probe] FAILED: {exc}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
