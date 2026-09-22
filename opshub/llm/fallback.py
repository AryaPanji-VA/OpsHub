from typing import List, Optional

from opshub.models import OperationalPlan, AgentActionModel, AgentObservation, RuntimeContext
from opshub.llm.base import LLMProvider
from opshub.llm.exceptions import ConfigurationError, RecoverableLLMError


class FallbackLLMProvider(LLMProvider):
    """LLM provider with automatic fallback."""

    def __init__(
        self,
        primary: LLMProvider,
        fallback: LLMProvider,
    ):
        self.primary = primary
        self.fallback = fallback
        self.primary_name = type(primary).__name__
        self.fallback_name = type(fallback).__name__

    def generate_plan(self, meeting_notes: str) -> OperationalPlan:
        """Generate plan with automatic fallback on recoverable failures."""
        last_error: Optional[Exception] = None

        try:
            return self.primary.generate_plan(meeting_notes)
        except ConfigurationError:
            raise
        except Exception as e:
            last_error = e

        try:
            return self.fallback.generate_plan(meeting_notes)
        except ConfigurationError:
            if last_error:
                raise RecoverableLLMError(
                    f"Primary ({self.primary_name}) failed: {last_error}. Fallback not configured.",
                    provider="fallback",
                    category="all_failed",
                )
            raise
        except Exception as e:
            raise RecoverableLLMError(
                f"All providers failed. {self.primary_name}: {last_error}. {self.fallback_name}: {e}.",
                provider="fallback",
                category="all_failed",
            )

    def choose_next_action(
        self,
        plan: OperationalPlan,
        observations: List[AgentObservation],
        runtime_context: RuntimeContext,
    ) -> AgentActionModel:
        """Choose next action with automatic fallback on recoverable failures."""
        last_error: Optional[Exception] = None

        try:
            return self.primary.choose_next_action(plan, observations, runtime_context)
        except ConfigurationError:
            raise
        except Exception as e:
            last_error = e

        try:
            return self.fallback.choose_next_action(plan, observations, runtime_context)
        except ConfigurationError:
            if last_error:
                raise RecoverableLLMError(
                    f"Primary ({self.primary_name}) action selection failed: {last_error}. Fallback not configured.",
                    provider="fallback",
                    category="all_failed",
                )
            raise
        except Exception as e:
            raise RecoverableLLMError(
                f"All providers failed action selection. {self.primary_name}: {last_error}. {self.fallback_name}: {e}.",
                provider="fallback",
                category="all_failed",
            )
