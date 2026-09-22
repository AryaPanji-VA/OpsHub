import sys
from pathlib import Path
from unittest.mock import Mock, patch
import os
sys.path.insert(0, str(Path(__file__).parent.parent))

from opshub.llm.exceptions import ConfigurationError, RecoverableLLMError
from opshub.cli import format_llm_error


def test_format_rate_limit_error_nex():
    e = RecoverableLLMError(
        "rate limit",
        provider="nex",
        category="rate_limit",
    )
    msg = format_llm_error(e)
    assert "temporarily unavailable" in msg.lower()
    assert "rate-limited" in msg.lower()


def test_format_rate_limit_error_qwen():
    e = RecoverableLLMError(
        "rate limit",
        provider="qwen",
        category="rate_limit",
    )
    msg = format_llm_error(e)
    assert "temporarily unavailable" in msg.lower()
    assert "rate-limited" in msg.lower()


def test_format_timeout_error():
    e = RecoverableLLMError(
        "timeout",
        provider="nex",
        category="timeout",
    )
    msg = format_llm_error(e)
    assert "timed out" in msg.lower()


def test_format_network_error():
    e = RecoverableLLMError(
        "network",
        provider="nex",
        category="network",
    )
    msg = format_llm_error(e)
    assert "cannot connect" in msg.lower()


def test_format_server_error():
    e = RecoverableLLMError(
        "server error",
        provider="nex",
        category="server_error",
    )
    msg = format_llm_error(e)
    assert "server error" in msg.lower()


def test_format_all_failed_error():
    e = RecoverableLLMError(
        "all failed",
        provider="fallback",
        category="all_failed",
    )
    msg = format_llm_error(e)
    assert "all configured ai providers" in msg.lower()


def test_format_configuration_error():
    e = ConfigurationError(
        "missing key",
        provider="nex",
        category="config",
    )
    msg = format_llm_error(e)
    assert "configuration error" in msg.lower()
    assert "provider" in msg.lower()
