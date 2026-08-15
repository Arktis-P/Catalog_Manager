from __future__ import annotations

from pathlib import Path

import pytest

from desktop.network_config import load_app_proxy_config


def test_missing_network_file_keeps_proxy_disabled(tmp_path: Path) -> None:
    config = load_app_proxy_config(tmp_path / "missing.env")

    assert config.enabled is False
    assert config.mode == "ssh"
    assert config.expected_country == "JP"
    assert config.browser_proxy_url == "socks5://127.0.0.1:1080"
    assert config.danbooru_proxy_url == "socks5h://127.0.0.1:1080"


def test_enabled_japan_ssh_proxy_reads_settings(tmp_path: Path) -> None:
    env_file = tmp_path / "network.env"
    env_file.write_text(
        "\n".join(
            [
                "CATALOGUE_APP_PROXY_ENABLED=1",
                "CATALOGUE_APP_PROXY_MODE=ssh",
                "CATALOGUE_PROXY_EXPECTED_COUNTRY=JP",
                "CATALOGUE_APP_PROXY_HOST=127.0.0.1",
                "CATALOGUE_APP_PROXY_PORT=1180",
                "CATALOGUE_PROXY_SSH_HOST=203.0.113.10",
                "CATALOGUE_PROXY_SSH_PORT=22",
                "CATALOGUE_PROXY_SSH_USER=ubuntu",
                "CATALOGUE_PROXY_SSH_KEY_FILE=test-key",
            ]
        ),
        encoding="utf-8",
    )

    config = load_app_proxy_config(env_file)

    assert config.enabled is True
    assert config.mode == "ssh"
    assert config.expected_country == "JP"
    assert config.ssh_target == "ubuntu@203.0.113.10"
    assert config.browser_proxy_url == "socks5://127.0.0.1:1180"
    assert config.danbooru_proxy_url == "socks5h://127.0.0.1:1180"


def test_enabled_generic_socks5_settings_remain_supported(tmp_path: Path) -> None:
    env_file = tmp_path / "network.env"
    env_file.write_text(
        "\n".join(
            [
                "CATALOGUE_APP_PROXY_ENABLED=1",
                "CATALOGUE_APP_PROXY_MODE=socks5",
                "CATALOGUE_PROXY_EXPECTED_COUNTRY=JP",
                "CATALOGUE_PROXY_UPSTREAM_HOST=proxy.example.test",
                "CATALOGUE_PROXY_UPSTREAM_PORT=1080",
                "CATALOGUE_PROXY_UPSTREAM_USERNAME=user",
                "CATALOGUE_PROXY_UPSTREAM_PASSWORD=pass",
            ]
        ),
        encoding="utf-8",
    )

    config = load_app_proxy_config(env_file)

    assert config.upstream_host == "proxy.example.test"
    assert config.uses_upstream_auth is True


def test_proxy_listener_must_stay_on_loopback(tmp_path: Path) -> None:
    env_file = tmp_path / "network.env"
    env_file.write_text(
        "\n".join(
            [
                "CATALOGUE_APP_PROXY_ENABLED=1",
                "CATALOGUE_APP_PROXY_MODE=ssh",
                "CATALOGUE_APP_PROXY_HOST=0.0.0.0",
                "CATALOGUE_PROXY_SSH_HOST=203.0.113.10",
                "CATALOGUE_PROXY_SSH_USER=ubuntu",
                "CATALOGUE_PROXY_SSH_KEY_FILE=test-key",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="loopback"):
        load_app_proxy_config(env_file)


def test_ssh_mode_requires_host_user_and_key(tmp_path: Path) -> None:
    env_file = tmp_path / "network.env"
    env_file.write_text(
        "\n".join(
            [
                "CATALOGUE_APP_PROXY_ENABLED=1",
                "CATALOGUE_APP_PROXY_MODE=ssh",
                "CATALOGUE_PROXY_SSH_HOST=203.0.113.10",
                "CATALOGUE_PROXY_SSH_USER=ubuntu",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="SSH_KEY_FILE"):
        load_app_proxy_config(env_file)


def test_partial_socks5_credentials_are_rejected(tmp_path: Path) -> None:
    env_file = tmp_path / "network.env"
    env_file.write_text(
        "\n".join(
            [
                "CATALOGUE_APP_PROXY_ENABLED=1",
                "CATALOGUE_APP_PROXY_MODE=socks5",
                "CATALOGUE_PROXY_UPSTREAM_HOST=proxy.example.test",
                "CATALOGUE_PROXY_UPSTREAM_USERNAME=user",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="configured together"):
        load_app_proxy_config(env_file)
