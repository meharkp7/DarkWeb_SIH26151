"""Live-socket contract tests.

The socket carries the whole Command Center, and it is the one authenticated
surface where a mistake is invisible until a console sits there showing
nothing. These tests drive a real handshake against a running server rather
than calling the handler directly, because the parts most likely to be wrong
— subprotocol negotiation, the pre-accept close, the poll loop — only exist at
the protocol level.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
import uvicorn
from fastapi.testclient import TestClient
from sqlalchemy import text
from websockets.exceptions import InvalidStatus

from aegis.api.app import app
from aegis.api.auth import issue_access_token
from aegis.db.session import engine

# --------------------------------------------------------------------------
# Server fixture
# --------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _database_ready() -> bool:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 - any driver error means "unavailable"
        return False


@contextmanager
def _running_server() -> Iterator[str]:
    """Run the real ASGI app under uvicorn for the duration of the block.

    `TestClient` cannot exercise a websocket, and the handshake is precisely
    what these tests are about, so the app runs for real on a spare port.
    """
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 20
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    if not server.started:  # pragma: no cover - only on a badly loaded machine
        server.should_exit = True
        raise RuntimeError("uvicorn did not start in time")
    try:
        yield f"ws://127.0.0.1:{port}/api/v1/live"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


@pytest.fixture(scope="module")
def live_url() -> Iterator[str]:
    if not _database_ready():
        pytest.skip("PostgreSQL unavailable")
    with _running_server() as url:
        yield url


def _connect(url: str, subprotocols: list[str] | None) -> Any:
    import websockets

    return websockets.connect(url, subprotocols=subprotocols)


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------


def test_socket_authenticates_with_a_session_subprotocol(live_url: str) -> None:
    async def run() -> None:
        token, _expires_at = issue_access_token()
        async with _connect(live_url, ["aegis", token]) as socket:
            # RFC 6455 §4.1: the server may only select a subprotocol the
            # client offered. Selecting one unconditionally is a protocol
            # violation that some clients treat as a failed connection.
            assert socket.subprotocol == "aegis"
            frame = json.loads(await asyncio.wait_for(socket.recv(), timeout=15))
            assert frame["type"] == "snapshot"
            # The snapshot must be the same typed frame the REST path serves,
            # or the console renders two different things depending on whether
            # the socket happened to be up.
            assert {"command_posture", "evidence_velocity", "investigation_pressure"} <= set(frame)
            assert {"attribution_posture", "case_summaries", "counts"} <= set(frame)
            for entry in frame["investigation_pressure"]:
                assert {"score", "observed", "ceiling"} <= set(entry)

    asyncio.run(run())


def test_socket_refuses_an_anonymous_handshake(live_url: str) -> None:
    async def run() -> None:
        with pytest.raises(InvalidStatus) as caught:
            async with _connect(live_url, None):
                pass
        # Rejected before accept, so the client never observes an open socket
        # that is about to be torn down. 1008 is the policy-violation code the
        # server sends.
        assert caught.value.response.status_code == 403

    asyncio.run(run())


def test_socket_refuses_a_forged_token(live_url: str) -> None:
    async def run() -> None:
        # A correctly-shaped token with a bad signature must be refused exactly
        # as an absent credential is: validation fails closed, not open.
        with pytest.raises(InvalidStatus) as caught:
            async with _connect(live_url, ["aegis", "v3.forged.signature"]):
                pass
        assert caught.value.response.status_code == 403

    asyncio.run(run())


def test_socket_sends_a_heartbeat_when_nothing_changed(live_url: str) -> None:
    async def run() -> None:
        token, _expires_at = issue_access_token()
        async with _connect(live_url, ["aegis", token]) as socket:
            first = json.loads(await asyncio.wait_for(socket.recv(), timeout=15))
            assert first["type"] == "snapshot"
            # The audit tail has not moved, so the next frame must be a
            # heartbeat rather than a full re-serialisation of the same
            # snapshot. Without this the socket pushes a few hundred kilobytes
            # every two seconds for an idle platform.
            second = json.loads(await asyncio.wait_for(socket.recv(), timeout=15))
            assert second["type"] == "heartbeat"
            assert "server_time" in second

    asyncio.run(run())


def test_socket_ignores_client_commands(live_url: str) -> None:
    async def run() -> None:
        token, _expires_at = issue_access_token()
        async with _connect(live_url, ["aegis", token]) as socket:
            await asyncio.wait_for(socket.recv(), timeout=15)
            # A write attempt must not produce an acknowledgement or an error
            # frame: the socket is read-only by design, and echoing back
            # anything a browser sends would be a command channel.
            await socket.send(json.dumps({"type": "command", "action": "delete_case"}))
            frame = json.loads(await asyncio.wait_for(socket.recv(), timeout=15))
            assert frame["type"] in {"heartbeat", "snapshot"}

    asyncio.run(run())


def test_snapshot_matches_the_rest_endpoint(live_url: str) -> None:
    """The socket and REST must not be two implementations of one payload."""

    async def run() -> dict[str, Any]:
        token, _expires_at = issue_access_token()
        async with _connect(live_url, ["aegis", token]) as socket:
            frame = json.loads(await asyncio.wait_for(socket.recv(), timeout=15))
        return frame

    live = asyncio.run(run())
    token, _expires_at = issue_access_token()
    rest = (
        TestClient(app)
        .get(
            "/api/v1/dashboard/summary",
            headers={"Authorization": f"Bearer {token}"},
        )
        .json()
    )
    assert live["counts"] == rest["counts"]
    assert live["command_posture"]["pressure_index"] == rest["command_posture"]["pressure_index"]
    assert [point["label"] for point in live["evidence_velocity"]] == [
        point["label"] for point in rest["evidence_velocity"]
    ]


def test_live_endpoint_is_not_reachable_over_rest(live_url: str) -> None:
    """A GET on the socket path must not be answered as if it were a route."""
    from urllib.parse import urlparse

    parsed = urlparse(live_url)
    http = f"http://{parsed.hostname}:{parsed.port}/api/v1/live"
    try:
        status = os.popen(f"curl -s -o /dev/null -w '%{{http_code}}' {http}").read().strip()
    except Exception:  # noqa: BLE001 - fall through to the assertion below
        pytest.skip("curl unavailable")
    assert status in {"404", "405", "403", "401"}, f"unexpected status {status}"
