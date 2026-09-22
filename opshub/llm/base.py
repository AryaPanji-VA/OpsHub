from abc import ABC, abstractmethod
from typing import List, Optional

from opshub.models import OperationalPlan, AgentActionModel, AgentObservation, RuntimeContext


class LLMProvider(ABC):
    """Base LLM provider interface."""

    @abstractmethod
    def generate_plan(self, meeting_notes: str) -> OperationalPlan:
        """Generate operational plan from meeting notes."""
        pass

    @abstractmethod
    def choose_next_action(
        self,
        plan: OperationalPlan,
        observations: List[AgentObservation],
        runtime_context: RuntimeContext,
    ) -> AgentActionModel:
        """Choose the next allowed action based on current state."""
        pass
