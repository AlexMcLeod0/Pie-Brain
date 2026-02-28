"""Tests for guardian.validator — message integrity middleware."""
import pytest

from guardian.validator import validate_message, MAX_MESSAGE_LEN


def test_valid_message_passes():
    ok, reason = validate_message("Search arxiv for LLM papers")
    assert ok is True
    assert reason == ""


def test_empty_string_blocked():
    ok, reason = validate_message("")
    assert ok is False
    assert "Empty" in reason


def test_exactly_at_limit_passes():
    text = "a" * MAX_MESSAGE_LEN
    ok, reason = validate_message(text)
    assert ok is True


def test_one_over_limit_blocked():
    text = "a" * (MAX_MESSAGE_LEN + 1)
    ok, reason = validate_message(text)
    assert ok is False
    assert "too long" in reason
    assert str(MAX_MESSAGE_LEN + 1) in reason


def test_over_limit_reason_includes_limit():
    text = "x" * (MAX_MESSAGE_LEN + 500)
    ok, reason = validate_message(text)
    assert ok is False
    assert str(MAX_MESSAGE_LEN) in reason


def test_normal_utf8_passes():
    ok, reason = validate_message("Hello, 世界! Привет!")
    assert ok is True


def test_whitespace_only_is_valid():
    # whitespace is not empty — it passes validation (router handles it)
    ok, reason = validate_message("   ")
    assert ok is True


def test_newlines_and_tabs_pass():
    ok, reason = validate_message("line1\nline2\ttabbed")
    assert ok is True
