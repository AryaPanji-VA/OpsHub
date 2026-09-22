import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import os
sys.path.insert(0, str(Path(__file__).parent.parent))

from opshub.llm.mock import MockLLMProvider
from opshub.llm import get_llm_provider, get_direct_llm_provider
from opshub.models import OperationalPlan
from opshub.llm.exceptions import ConfigurationError


def test_get_provider_mock():
    with patch.dict(os.environ, {"LLM_PROVIDER": "mock"}):
        provider = get_llm_provider()
        assert isinstance(provider, MockLLMProvider)


def test_get_provider_qwen_missing_key():
    with patch.dict(os.environ, {"LLM_PROVIDER": "qwen"}, clear=True):
        os.environ["LLM_PROVIDER"] = "qwen"
        try:
            provider = get_direct_llm_provider()
            assert False, "Should raise"
        except (ValueError, ConfigurationError):
            pass


def test_get_provider_nex_missing_key():
    with patch.dict(os.environ, {"LLM_PROVIDER": "nex"}, clear=True):
        os.environ["LLM_PROVIDER"] = "nex"
        try:
            provider = get_direct_llm_provider()
            assert False, "Should raise ConfigurationError"
        except ConfigurationError:
            pass


def test_get_provider_fallback():
    with patch.dict(os.environ, {"LLM_PROVIDER": "fallback"}, clear=True):
        os.environ["LLM_PROVIDER"] = "fallback"
        try:
            provider = get_direct_llm_provider()
            assert False, "Should raise (Qwen needs API key)"
        except (ValueError, ConfigurationError):
            pass


def test_get_provider_unknown():
    with patch.dict(os.environ, {"LLM_PROVIDER": "unknown"}):
        try:
            get_direct_llm_provider()
            assert False, "Should raise ValueError"
        except ValueError as e:
            assert "Unknown LLM_PROVIDER" in str(e)
