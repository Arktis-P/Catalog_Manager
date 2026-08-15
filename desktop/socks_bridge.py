"""Loopback SOCKS5 bridge for Catalogue Manager.

Chrome does not support SOCKS5 username/password authentication. This bridge accepts
no-auth SOCKS5 connections only on loopback and forwards them through an optional
authenticated upstream SOCKS5 server (for example a NordVPN SOCKS5 endpoint).

Only TCP CONNECT is implemented because that is what Chromium URL loads and Requests
need for HTTP/HTTPS traffic.
"""

from __future__ import annotations

import select
import socket
import socketserver
from dataclasses import dataclass

from desktop.network_config import AppProxyConfig, load_app_proxy_config

SOCKS_VERSION = 5
CMD_CONNECT = 1
AUTH_NONE = 0
AUTH_USERPASS = 2


class SocksProtocolError(RuntimeError):
    pass


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = sock.recv(remaining)
        if not chunk:
            raise SocksProtocolError("SOCKS connection closed unexpectedly")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _read_address(sock: socket.socket, atyp: int) -> bytes:
    if atyp == 1:  # IPv4
        return _recv_exact(sock, 4)
    if atyp == 3:  # domain
        length = _recv_exact(sock, 1)
        return length + _recv_exact(sock, length[0])
    if atyp == 4:  # IPv6
        return _recv_exact(sock, 16)
    raise SocksProtocolError(f"Unsupported SOCKS address type: {atyp}")


def _negotiate_local_client(client: socket.socket) -> tuple[int, bytes, bytes]:
    version, method_count = _recv_exact(client, 2)
    if version != SOCKS_VERSION:
        raise SocksProtocolError("Only SOCKS5 clients are supported")
    methods = _recv_exact(client, method_count)
    if AUTH_NONE not in methods:
        client.sendall(bytes([SOCKS_VERSION, 0xFF]))
        raise SocksProtocolError("Local SOCKS client must support no-auth mode")
    client.sendall(bytes([SOCKS_VERSION, AUTH_NONE]))

    version, command, _reserved, atyp = _recv_exact(client, 4)
    if version != SOCKS_VERSION or command != CMD_CONNECT:
        client.sendall(b"\x05\x07\x00\x01\x00\x00\x00\x00\x00\x00")
        raise SocksProtocolError("Only SOCKS5 CONNECT is supported")
    address = _read_address(client, atyp)
    port = _recv_exact(client, 2)
    return atyp, address, port


def _authenticate_upstream(upstream: socket.socket, config: AppProxyConfig) -> None:
    requested_method = AUTH_USERPASS if config.uses_upstream_auth else AUTH_NONE
    upstream.sendall(bytes([SOCKS_VERSION, 1, requested_method]))
    version, selected_method = _recv_exact(upstream, 2)
    if version != SOCKS_VERSION or selected_method == 0xFF:
        raise SocksProtocolError("Upstream SOCKS5 server rejected authentication methods")

    if selected_method == AUTH_NONE:
        return
    if selected_method != AUTH_USERPASS or not config.uses_upstream_auth:
        raise SocksProtocolError("Upstream SOCKS5 server requires unsupported authentication")

    username = config.upstream_username.encode("utf-8")
    password = config.upstream_password.encode("utf-8")
    if not (1 <= len(username) <= 255 and 1 <= len(password) <= 255):
        raise SocksProtocolError("Upstream SOCKS5 credentials must be 1-255 bytes")

    upstream.sendall(
        bytes([1, len(username)])
        + username
        + bytes([len(password)])
        + password
    )
    auth_version, auth_status = _recv_exact(upstream, 2)
    if auth_version != 1 or auth_status != 0:
        raise SocksProtocolError("Upstream SOCKS5 username/password authentication failed")


def _connect_upstream(
    config: AppProxyConfig,
    atyp: int,
    address: bytes,
    port: bytes,
) -> tuple[socket.socket, bytes]:
    upstream = socket.create_connection(
        (config.upstream_host, config.upstream_port),
        timeout=15,
    )
    try:
        _authenticate_upstream(upstream, config)
        upstream.sendall(bytes([SOCKS_VERSION, CMD_CONNECT, 0, atyp]) + address + port)

        header = _recv_exact(upstream, 4)
        version, reply, _reserved, bound_atyp = header
        if version != SOCKS_VERSION:
            raise SocksProtocolError("Invalid reply from upstream SOCKS5 server")
        bound_address = _read_address(upstream, bound_atyp)
        bound_port = _recv_exact(upstream, 2)
        response = header + bound_address + bound_port
        if reply != 0:
            raise SocksProtocolError(f"Upstream SOCKS5 CONNECT failed with code {reply}")
        upstream.settimeout(None)
        return upstream, response
    except Exception:
        upstream.close()
        raise


def _relay(left: socket.socket, right: socket.socket) -> None:
    sockets = [left, right]
    while True:
        readable, _writable, exceptional = select.select(sockets, [], sockets, 60)
        if exceptional:
            return
        if not readable:
            continue
        for source in readable:
            try:
                data = source.recv(65536)
            except OSError:
                return
            if not data:
                return
            target = right if source is left else left
            target.sendall(data)


@dataclass
class BridgeState:
    config: AppProxyConfig


class _BridgeHandler(socketserver.BaseRequestHandler):
    server: "SocksBridgeServer"

    def handle(self) -> None:
        client: socket.socket = self.request
        upstream: socket.socket | None = None
        try:
            atyp, address, port = _negotiate_local_client(client)
            upstream, response = _connect_upstream(self.server.state.config, atyp, address, port)
            client.sendall(response)
            _relay(client, upstream)
        except (OSError, SocksProtocolError) as exc:
            if upstream is None:
                try:
                    client.sendall(b"\x05\x01\x00\x01\x00\x00\x00\x00\x00\x00")
                except OSError:
                    pass
            print(f"[proxy] connection failed: {exc}", flush=True)
        finally:
            if upstream is not None:
                upstream.close()


class SocksBridgeServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, config: AppProxyConfig):
        config.validate()
        self.state = BridgeState(config=config)
        super().__init__((config.listen_host, config.listen_port), _BridgeHandler)


def run_bridge(config: AppProxyConfig | None = None) -> None:
    config = config or load_app_proxy_config()
    if not config.enabled:
        raise RuntimeError("App proxy is disabled in input/network.env")
    config.validate()

    auth_mode = "authenticated" if config.uses_upstream_auth else "no-auth"
    print(
        f"[proxy] {config.listen_host}:{config.listen_port} -> "
        f"{config.upstream_host}:{config.upstream_port} ({auth_mode} upstream)",
        flush=True,
    )
    with SocksBridgeServer(config) as server:
        server.serve_forever(poll_interval=0.25)


def main() -> None:
    try:
        run_bridge()
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"[proxy] failed to start: {exc}", flush=True)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
