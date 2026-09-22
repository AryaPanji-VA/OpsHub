import sys
from pathlib import Path
from unittest.mock import Mock, patch
import os
sys.path.insert(0, str(Path(__file__).parent.parent))

from opshub.llm.exceptions import ConfigurationError, RecoverableLLMError
from opshub.models import OperationalPlan, NextAction


def test_cli_handles_nex_rate_limit(capsys):
    """CLI shows graceful message when Nex rate limited."""
    with patch("opshub.cli.get_llm_provider") as mock_get:
        mock_get.side_effect = RecoverableLLMError(
            "rate limit",
            provider="nex",
            category="rate_limit",
        )
        from opshub.cli import main

        try:
            main()
        except SystemExit:
            pass

        output = capsys.readouterr().out
        assert "unavailable" in output.lower()
        assert "rate-limited" in output.lower()


def test_cli_handles_configuration_error(capsys):
    """CLI shows graceful message for configuration error."""
    with patch("opshub.cli.get_llm_provider") as mock_get:
        mock_get.side_effect = ConfigurationError(
            "missing key",
            provider="nex",
            category="config",
        )
        from opshub.cli import main

        try:
            main()
        except SystemExit:
            pass

        output = capsys.readouterr().out
        assert "configuration error" in output.lower()


def test_cli_handles_fallback_all_failed(capsys):
    """CLI shows graceful message when all providers fail."""
    with patch("opshub.cli.get_llm_provider") as mock_get:
        mock_get.side_effect = RecoverableLLMError(
            "all failed",
            provider="fallback",
            category="all_failed",
        )
        from opshub.cli import main

        try:
            main()
        except SystemExit:
            pass

        output = capsys.readouterr().out
        assert "all configured ai providers" in output.lower()
