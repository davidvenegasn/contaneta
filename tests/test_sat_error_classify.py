"""Tests for SAT error categorization and retry strategy."""

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if not os.environ.get("APP_DB_PATH"):
    _fd, _p = tempfile.mkstemp(suffix=".db", prefix="test_sat_error_")
    os.close(_fd)
    os.environ["APP_DB_PATH"] = _p
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = "test-secret-sat-error"

from services.sat.sat_job_handlers import (  # noqa: E402
    classify_sat_error,
    RETRY_DELAYS,
    get_max_attempts_for_category,
    should_retry,
)


def test_network_error_classified_correctly():
    """DNS/connection errors should be classified as 'network'."""
    assert classify_sat_error("Could not resolve host sat.gob.mx") == "network"
    assert classify_sat_error("connection refused") == "network"
    assert classify_sat_error("Operation timed out after 30 seconds") == "network"


def test_empty_response_classified_correctly():
    """'Sin información' responses should be classified as 'empty'."""
    assert classify_sat_error("Sin información para el periodo") == "empty"
    assert classify_sat_error("no_records found") == "empty"


def test_rate_limit_classified_correctly():
    """Rate limit errors should be classified as 'rate_limit'."""
    assert classify_sat_error("Too many requests (429)") == "rate_limit"
    assert classify_sat_error("Rate limit exceeded") == "rate_limit"


def test_auth_error_classified_correctly():
    """Auth/FIEL errors should be classified as 'auth'."""
    assert classify_sat_error("Unauthorized (401)") == "auth"
    assert classify_sat_error("FIEL invalid certificate") == "auth"


def test_sat_5xx_classified_correctly():
    """SAT server errors should be classified as 'sat_5xx'."""
    assert classify_sat_error("Internal Server Error 500") == "sat_5xx"
    assert classify_sat_error("502 Bad Gateway") == "sat_5xx"


def test_unknown_error_classified_correctly():
    """Unrecognized errors should be classified as 'unknown'."""
    assert classify_sat_error("Something weird happened") == "unknown"
    assert classify_sat_error("") == "unknown"
    assert classify_sat_error(None) == "unknown"


def test_network_error_schedules_retry():
    """Network errors should allow retries with increasing delays."""
    assert should_retry("network", 0) is True
    assert should_retry("network", 3) is True
    assert should_retry("network", 4) is False  # exhausted


def test_empty_response_schedules_retry():
    """Empty responses should allow up to 3 retries."""
    assert should_retry("empty", 0) is True
    assert should_retry("empty", 2) is True
    assert should_retry("empty", 3) is False


def test_rate_limit_schedules_retry():
    """Rate limit errors should retry with long delays."""
    assert should_retry("rate_limit", 0) is True
    delays = RETRY_DELAYS["rate_limit"]
    assert delays[0] == 3600  # 1 hour minimum


def test_auth_error_no_retry():
    """Auth errors should never retry — requires manual intervention."""
    assert should_retry("auth", 0) is False
    assert get_max_attempts_for_category("auth") == 1


def test_retry_delays_are_increasing():
    """Within each category, delays should increase monotonically."""
    for category, delays in RETRY_DELAYS.items():
        for i in range(1, len(delays)):
            assert delays[i] >= delays[i - 1], (
                f"{category}: delay[{i}]={delays[i]} < delay[{i-1}]={delays[i-1]}"
            )
