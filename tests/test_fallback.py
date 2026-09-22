import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import os
sys.path.insert(0, str(Path(__file__).parent.parent))

from opshub.llm.exceptions import RecoverableLLMError, ConfigurationError
from opshub.models import OperationalPlan, Task, NextAction


class MockPrimary:
    def __init__(self, fail=False, error=None):
        self.fail = fail
        self.error = error
        self.call_count = 0

    def generate_plan(self, notes):
        self.call_count += 1
        if self.fail:
            raise self.error
        return OperationalPlan(
            program="Primary Plan",
            summary="From primary",
            tasks=[],
            checks_required=[],
            risk_flags=[],
            next_action=NextAction.WAIT_FOR_HUMAN,
        )


class MockFallback:
    def __init__(self, fail=False, error=None):
        self.fail = fail
        self.error = error
        self.call_count = 0

    def generate_plan(self, notes):
        self.call_count += 1
        if self.fail:
            raise self.error
        return OperationalPlan(
            program="Fallback Plan",
            summary="From fallback",
            tasks=[],
            checks_required=[],
            risk_flags=[],
            next_action=NextAction.WAIT_FOR_HUMAN,
        )


def test_primary_succeeds():
    primary = MockPrimary()
    fallback = MockFallback()

    from opshub.llm.fallback import FallbackLLMProvider

    provider = FallbackLLMProvider(primary=primary, fallback=fallback)
    result = provider.generate_plan("test")

    assert primary.call_count == 1
    assert fallback.call_count == 0
    assert result.program == "Primary Plan"


def test_primary_rate_limited_fallback_used():
    primary = MockPrimary(
        fail=True,
        error=RecoverableLLMError("rate limit", provider="primary", category="rate_limit"),
    )
    fallback = MockFallback()

    from opshub.llm.fallback import FallbackLLMProvider

    provider = FallbackLLMProvider(primary=primary, fallback=fallback)
    result = provider.generate_plan("test")

    assert primary.call_count == 1
    assert fallback.call_count == 1
    assert result.program == "Fallback Plan"


def test_primary_timeout_fallback_used():
    primary = MockPrimary(
        fail=True,
        error=RecoverableLLMError("timeout", provider="primary", category="timeout"),
    )
    fallback = MockFallback()

    from opshub.llm.fallback import FallbackLLMProvider

    provider = FallbackLLMProvider(primary=primary, fallback=fallback)
    result = provider.generate_plan("test")

    assert primary.call_count == 1
    assert fallback.call_count == 1


def test_primary_network_error_fallback_used():
    primary = MockPrimary(
        fail=True,
        error=RecoverableLLMError("network", provider="primary", category="network"),
    )
    fallback = MockFallback()

    from opshub.llm.fallback import FallbackLLMProvider

    provider = FallbackLLMProvider(primary=primary, fallback=fallback)
    result = provider.generate_plan("test")

    assert primary.call_count == 1
    assert fallback.call_count == 1


def test_primary_validation_error_fallback_used():
    primary = MockPrimary(
        fail=True,
        error=RecoverableLLMError("validation", provider="primary", category="validation"),
    )
    fallback = MockFallback()

    from opshub.llm.fallback import FallbackLLMProvider

    provider = FallbackLLMProvider(primary=primary, fallback=fallback)
    result = provider.generate_plan("test")

    assert primary.call_count == 1
    assert fallback.call_count == 1


def test_primary_configuration_error_no_fallback():
    primary = MockPrimary(
        fail=True,
        error=ConfigurationError("missing key", provider="primary", category="config"),
    )
    fallback = MockFallback()

    from opshub.llm.fallback import FallbackLLMProvider

    provider = FallbackLLMProvider(primary=primary, fallback=fallback)

    try:
        provider.generate_plan("test")
        assert False, "Should raise"
    except ConfigurationError:
        pass

    assert fallback.call_count == 0


def test_both_fail_raises():
    primary = MockPrimary(
        fail=True,
        error=RecoverableLLMError("primary error", provider="primary", category="rate_limit"),
    )
    fallback = MockFallback(
        fail=True,
        error=RecoverableLLMError("fallback error", provider="fallback", category="rate_limit"),
    )

    from opshub.llm.fallback import FallbackLLMProvider

    provider = FallbackLLMProvider(primary=primary, fallback=fallback)

    try:
        provider.generate_plan("test")
        assert False, "Should raise"
    except RecoverableLLMError as e:
        assert "all" in e.category.lower() or "failed" in str(e).lower()


def test_fallback_success_validates_plan():
    primary = MockPrimary(
        fail=True,
        error=RecoverableLLMError("error", provider="primary", category="rate_limit"),
    )
    fallback = MockFallback()

    from opshub.llm.fallback import FallbackLLMProvider

    provider = FallbackLLMProvider(primary=primary, fallback=fallback)
    result = provider.generate_plan("test")

    assert isinstance(result, OperationalPlan)
    assert result.program is not None
