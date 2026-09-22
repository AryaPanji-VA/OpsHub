from enum import Enum
from typing import Optional, List, Literal

from pydantic import BaseModel, ConfigDict


class TaskStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class NextAction(Enum):
    RUN_TOOLS = "run_tools"
    WAIT_FOR_HUMAN = "wait_for_human"
    READY_TO_CREATE_TICKET = "ready_to_create_ticket"
    COMPLETED = "completed"
    FAILED = "failed"


class RiskFlag(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str
    severity: str


class ContextSource(Enum):
    HUMAN = "human"
    RUNTIME_FILE = "runtime_file"
    NONE = "none"


class RuntimeContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available_budget: Optional[float] = None
    schedule_entries: Optional[list] = None
    budget_source: Optional[ContextSource] = None
    schedule_source: Optional[ContextSource] = None


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: str
    task_id: str
    success: bool
    status: str
    message: str
    details: dict = {}
    source: ContextSource = ContextSource.RUNTIME_FILE


class ApprovalStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class Approval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str
    task_id: str
    reason: Optional[str]
    status: ApprovalStatus


class Task(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    division: Optional[str]
    pic: Optional[str]
    deadline: Optional[str]
    budget_required: Optional[float]
    priority: Optional[str]
    status: Optional[TaskStatus]


class OperationalPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    program: str
    summary: str
    tasks: List[Task]
    checks_required: List[str]
    risk_flags: List[RiskFlag]
    next_action: NextAction


class AgentAction(Enum):
    CHECK_BUDGET = "check_budget"
    CHECK_SCHEDULE = "check_schedule"
    REQUEST_HUMAN_REVIEW = "request_human_review"
    PROPOSE_TICKET_CREATION = "propose_ticket_creation"
    FINISH = "finish"


class AgentActionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: AgentAction
    task_id: Optional[str]
    reason: str


class AgentObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str
    task_id: Optional[str] = None
    status: str
    message: str
    details: dict = {}
