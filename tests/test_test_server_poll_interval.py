"""Regression contracts for the pytest-only server polling override."""

import socketserver

import conftest


def test_default_test_server_poll_interval_is_short(monkeypatch):
    calls = []
    sentinel = object()

    def fake_serve_forever(server, poll_interval=0.5):
        calls.append((server, poll_interval))
        return sentinel

    monkeypatch.setattr(conftest, "_ORIGINAL_SERVE_FOREVER", fake_serve_forever)
    server = object()

    assert conftest._serve_forever(server) is sentinel
    assert calls == [(server, 0.01)]
    assert socketserver.BaseServer.serve_forever is conftest._serve_forever


def test_explicit_test_server_poll_interval_is_preserved(monkeypatch):
    calls = []

    def fake_serve_forever(server, poll_interval=0.5):
        calls.append((server, poll_interval))

    monkeypatch.setattr(conftest, "_ORIGINAL_SERVE_FOREVER", fake_serve_forever)
    server = object()

    conftest._serve_forever(server, poll_interval=0.25)

    assert calls == [(server, 0.25)]
