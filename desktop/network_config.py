"""App-scoped proxy configuration shared by the desktop launcher and SOCKS bridge.

The proxy is intentionally bound to loopback so enabling it never changes Windows
system proxy/VPN settings and never exposes the local forwarding port to the LAN.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NETWORK_ENV = PROJECT_ROOT / "input" / "network.env"
_TRUE_VALUES = {"1", "true", "yes", "on"}
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost"}


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values

    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _value(values: dict[str, str], *names: str, default: str = "") -> str:
    for name in names:
        env_value = os.environ.get(name)
        if env_value is not None:
            return env_value.strip()
        if name in values:
            return values[name].strip()
    return default


def _int_value(raw: str, *, name: str, default: int) -> int:
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not 1 <= value <= 65535:
        raise ValueError(f"{name} must be between 1 and 65535")
    return value


def _is_placeholder(value: str) -> bool:
    normalized = value.strip().lower()
    return not normalized or normalized.startswith("your_")


@dataclass(frozen=True)
class AppProxyConfig:
    enabled: bool = False
    listen_host: str = "127.0.0.1"
    listen_port: int = 1080
    upstream_host: str = ""
    upstream_port: int = 1080
    upstream_username: str = ""
    upstream_password: str = ""

    @property
    def browser_proxy_url(self) -> str:
        return f"socks5://{self.listen_host}:{self.listen_port}"

    @property
    def danbooru_proxy_url(self) -> str:
        # requests/PySocks uses socks5h to force target DNS through the proxy.
        return f"socks5h://{self.listen_host}:{self.listen_port}"

    def validate(self) -> None:
        if not self.enabled:
            return
        if self.listen_host not in _LOOPBACK_HOSTS:
            raise ValueError(
                "CATALOGUE_APP_PROXY_HOST must be loopback (127.0.0.1 or localhost)"
            )
        if _is_placeholder(self.upstream_host):
            raise ValueError("Proxy is enabled but upstream SOCKS5 host is not configured")

        username_set = not _is_placeholder(self.upstream_username)
        password_set = not _is_placeholder(self.upstream_password)
        if username_set != password_set:
            raise ValueError("Upstream SOCKS5 username and password must be configured together")
        if self.upstream_host.lower().endswith(".nordhold.net") and not username_set:
            raise ValueError(
                "NordVPN SOCKS5 requires service credentials; fill the upstream username/password"
            )

    @property
    def uses_upstream_auth(self) -> bool:
        return not _is_placeholder(self.upstream_username) and not _is_placeholder(
            self.upstream_password
        )


def load_app_proxy_config(path: Path = DEFAULT_NETWORK_ENV) -> AppProxyConfig:
    values = _read_env_file(path)

    enabled_raw = _value(values, "CATALOGUE_APP_PROXY_ENABLED", default="0")
    listen_host = _value(values, "CATALOGUE_APP_PROXY_HOST", default="127.0.0.1")
    listen_port = _int_value(
        _value(values, "CATALOGUE_APP_PROXY_PORT", default="1080"),
        name="CATALOGUE_APP_PROXY_PORT",
        default=1080,
    )
    upstream_host = _value(
        values,
        "CATALOGUE_PROXY_UPSTREAM_HOST",
        "nord_socks_host",
    )
    upstream_port = _int_value(
        _value(
            values,
            "CATALOGUE_PROXY_UPSTREAM_PORT",
            "nord_socks_port",
            default="1080",
        ),
        name="CATALOGUE_PROXY_UPSTREAM_PORT",
        default=1080,
    )
    upstream_username = _value(
        values,
        "CATALOGUE_PROXY_UPSTREAM_USERNAME",
        "nord_service_username",
    )
    upstream_password = _value(
        values,
        "CATALOGUE_PROXY_UPSTREAM_PASSWORD",
        "nord_service_password",
    )

    config = AppProxyConfig(
        enabled=enabled_raw.strip().lower() in _TRUE_VALUES,
        listen_host=listen_host,
        listen_port=listen_port,
        upstream_host=upstream_host,
        upstream_port=upstream_port,
        upstream_username=upstream_username,
        upstream_password=upstream_password,
    )
    config.validate()
    return config
