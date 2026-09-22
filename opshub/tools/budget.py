import json
from pathlib import Path
from typing import Tuple, Optional

from opshub.models import ContextSource

DATA_FILE = Path(__file__).parent.parent.parent / "data" / "budgets.json"


def load_budgets(data_path: Optional[Path] = None) -> dict:
    path = data_path or DATA_FILE
    if not path.exists():
        return {"available": 10000.0, "allocated": 0.0}
    with open(path) as f:
        return json.load(f)


def check_budget(
    amount: float,
    available: Optional[float] = None,
    data_path: Optional[Path] = None,
) -> Tuple[bool, str, ContextSource]:
    """
    Check budget with explicit value or data source.
    Returns (is_sufficient, message, source).
    """
    if available is not None:
        # Explicit value takes precedence
        if amount <= available:
            return True, f"Budget sufficient ({available:,.0f})", ContextSource.HUMAN
        return (
            False,
            f"Insufficient budget. Available: {available:,.0f}, Required: {amount:,.0f}",
            ContextSource.HUMAN,
        )

    # Fall back to file data
    budget = load_budgets(data_path)
    available = budget.get("available", 0) - budget.get("allocated", 0)
    if amount <= available:
        return True, f"Budget sufficient ({available:,.0f})", ContextSource.RUNTIME_FILE
    return (
        False,
        f"Insufficient budget. Available: {available:,.0f}, Required: {amount:,.0f}",
        ContextSource.RUNTIME_FILE,
    )


def allocate_budget(amount: float) -> Tuple[bool, str]:
    if not Path.exists(DATA_FILE):
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    budget = load_budgets()
    available = budget.get("available", 0) - budget.get("allocated", 0)
    if amount > available:
        return False, "Insufficient budget"
    budget["allocated"] = budget.get("allocated", 0) + amount
    with open(DATA_FILE, "w") as f:
        json.dump(budget, f, indent=2)
    return True, "Budget allocated"
