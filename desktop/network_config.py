"""App-scoped proxy configuration shared by the desktop launcher and probes.

The local SOCKS endpoint is always bound to loopback. Two upstream modes are
supported:

- ``ssh``: start ``ssh -D`` to a remote host (recommended for a fixed Japan exit).
- ``socks5``: start the built-in bridge to an upstream SOCKS5 server.

Neither mode changes Windows system proxy, VPN, DNS, or routing settings.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NETWORK_ENV = PROJECT_ROOT / "input" / "network.env"
_TRUE_VALUES = {"1", "true", "yes", "on"}
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost"}
_PROXY_MODES = {"ssh", "socks5"}


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
    return not normalized or normalized.startswith("your_") or normalized.startswith("<")


@dataclass(frozen=True)
class AppProxyConfig:
    enabled: bool = False
    mode: str = "ssh"
    expected_country: str = "JP"
    listen_host: str = "127.0.0.1"
    listen_port: int = 1080

    # Generic upstream SOCKS5 mode.
    upstream_host: str = ""
    upstream_port: int = 1080
    upstream_username: str = ""
    upstream_password: str = ""

    # SSH dynamic-forward mode. Recommended for a Tokyo VPS.
    ssh_host: str = ""
    ssh_port: int = 22
    ssh_user: str = ""
    ssh_key_file: str = ""

    @property
    def browser_proxy_url(self) -> str:
        return f"socks5://{self.listen_host}:{self.listen_port}"

    @property
    def danbooru_proxy_url(self) -> str:
        # requests/PySocks uses socks5h so target DNS is resolved through the proxy.
        return f"socks5h://{self.listen_host}:{self.listen_port}"

    @property
    def uses_upstream_auth(self) -> bool:
        return not _is_placeholder(self.upstream_username) and not _is_placeholder(
            self.upstream_password
        )

    @property
    def ssh_target(self) -> str:
        return f"{self.ssh_user}@{self.ssh_host}"

    @property
    def ssh_key_path(self) -> Path:
        expanded = os.path.expandvars(os.path.expanduser(self.ssh_key_file))
        path = Path(expanded)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path

    def validate(self) -> None:
        if not self.enabled:
            return
        if self.listen_host not in _LOOPBACK_HOSTS:
            raise ValueError(
                "CATALOGUE_APP_PROXY_HOST must be loopback (127.0.0.1 or localhost)"
            )
        if self.mode not in _PROXY_MODES:
            raise ValueError("CATALOGUE_APP_PROXY_MODE must be 'ssh' or 'socks5'")

        country = self.expected_country.strip().upper()
        if country and (len(country) != 2 or not country.isalpha()):
            raise ValueError("CATALOGUE_PROXY_EXPECTED_COUNTRY must be a 2-letter country code")

        if self.mode == "ssh":
            if _is_placeholder(self.ssh_host):
                raise ValueError("SSH proxy mode requires CATALOGUE_PROXY_SSH_HOST")
            if _is_placeholder(self.ssh_user):
                raise ValueError("SSH proxy mode requires CATALOGUE_PROXY_SSH_USER")
            if _is_placeholder(self.ssh_key_file):
                raise ValueError("SSH proxy mode requires CATALOGUE_PROXY_SSH_KEY_FILE")
            return

        if _is_placeholder(self.upstream_host):
            raise ValueError("SOCKS5 proxy mode requires an upstream SOCKS5 host")
        username_set = not _is_placeholder(self.upstream_username)
        password_set = not _is_placeholder(self.upstream_password)
        if username_set != password_set:
            raise ValueError("Upstream SOCKS5 username and password must be configured together")
        if self.upstream_host.lower().endswith(".nordhold.net") and not username_set:
            raise ValueError(
                "NordVPN SOCKS5 requires service credentials; fill the upstream username/password"
            )


def load_app_proxy_config(path: Path = DEFAULT_NETWORK_ENV) -> AppProxyConfig:
    values = _read_env_file(path)

    enabled_raw = _value(values, "CATALOGUE_APP_PROXY_ENABLED", default="0")
    mode = _value(values, "CATALOGUE_APP_PROXY_MODE", default="ssh").lower()
    expected_country = _value(values, "CATALOGUE_PROXY_EXPECTED_COUNTRY", default="JP").upper()
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

    ssh_host = _value(values, "CATALOGUE_PROXY_SSH_HOST")
    ssh_port = _int_value(
        _value(values, "CATALOGUE_PROXY_SSH_PORT", default="22"),
        name="CATALOGUE_PROXY_SSH_PORT",
        default=22,
    )
    ssh_user = _value(values, "CATALOGUE_PROXY_SSH_USER")
    ssh_key_file = _value(values, "CATALOGUE_PROXY_SSH_KEY_FILE")

    config = AppProxyConfig(
        enabled=enabled_raw.strip().lower() in _TRUE_VALUES,
        mode=mode,
        expected_country=expected_country,
        listen_host=listen_host,
        listen_port=listen_port,
        upstream_host=upstream_host,
        upstream_port=upstream_port,
        upstream_username=upstream_username,
        upstream_password=upstream_password,
        ssh_host=ssh_host,
        ssh_port=ssh_port,
        ssh_user=ssh_user,
        ssh_key_file=ssh_key_file,
    )
    config.validate()
    return config
