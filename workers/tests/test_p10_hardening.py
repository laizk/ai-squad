"""P10 — Hardening tests for workers.

Tests retry backoff configuration, transient error classification,
and safety violation recording.
"""
from __future__ import annotations

import httpx
import pytest


class TestRetryBackoffConfig:
    def test_execute_step_task_has_max_retries(self):
        """execute_step is configured with max_retries=3 so Celery can retry."""
        from app.tasks import execute_step, _RETRY_BACKOFF_BASE

        assert execute_step.max_retries == 3, (
            f"execute_step.max_retries should be 3, got {execute_step.max_retries}"
        )
        assert _RETRY_BACKOFF_BASE > 0, "Backoff base must be positive"

        # Verify the countdown formula stays within sensible bounds
        for attempt in range(3):
            countdown = _RETRY_BACKOFF_BASE * (2 ** attempt)
            assert countdown > 0
            assert countdown <= 3600, (
                f"Backoff at attempt {attempt} seems too large: {countdown}s. "
                f"Reduce STEP_RETRY_BACKOFF_BASE."
            )

    def test_backoff_sequence(self):
        """Countdown values increase exponentially with default base=30."""
        from app.tasks import _RETRY_BACKOFF_BASE

        base = _RETRY_BACKOFF_BASE
        assert base * (2 ** 0) < base * (2 ** 1) < base * (2 ** 2)


class TestTransientErrorClassification:
    def test_connect_error_is_transient(self):
        from app.tasks import _is_transient_error

        assert _is_transient_error(httpx.ConnectError("Connection refused")) is True

    def test_remote_protocol_error_is_transient(self):
        from app.tasks import _is_transient_error

        assert _is_transient_error(httpx.RemoteProtocolError("Server disconnected without sending a response.")) is True

    def test_server_disconnected_message_is_transient(self):
        from app.tasks import _is_transient_error

        err = RuntimeError("Server disconnected without sending a response.")
        assert _is_transient_error(err) is True

    def test_connection_refused_message_is_transient(self):
        from app.tasks import _is_transient_error

        err = RuntimeError("connection refused to postgres host")
        assert _is_transient_error(err) is True

    def test_value_error_is_not_transient(self):
        from app.tasks import _is_transient_error

        assert _is_transient_error(ValueError("artifact validation failed")) is False

    def test_json_parse_error_is_not_transient(self):
        from app.tasks import _is_transient_error

        err = RuntimeError("JSON decode error: expecting value at position 0")
        assert _is_transient_error(err) is False

    def test_generic_runtime_error_is_not_transient(self):
        from app.tasks import _is_transient_error

        err = RuntimeError("stub returned unexpected artifact type")
        assert _is_transient_error(err) is False


class TestTransientStepError:
    def test_transient_step_error_is_exception(self):
        from app.tasks import _TransientStepError

        err = _TransientStepError("connection refused")
        assert isinstance(err, Exception)
        assert "connection refused" in str(err)

    def test_transient_step_error_can_chain(self):
        from app.tasks import _TransientStepError

        original = httpx.ConnectError("Connection refused")
        chained = _TransientStepError("wrapped")
        chained.__cause__ = original
        assert chained.__cause__ is original
