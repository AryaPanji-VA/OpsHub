import json
from pathlib import Path
from typing import Tuple, Optional

from opshub.models import ContextSource

DATA_FILE = Path(__file__).parent.parent.parent / "data" / "schedules.json"


def load_schedules(data_path: Optional[Path] = None) -> list:
    path = data_path or DATA_FILE
    if not path.exists():
        return []
    with open(path) as f:
        return json.load(f)


def check_schedule(
    event_name: str,
    date: str,
    data_path: Optional[Path] = None,
    entries: Optional[list] = None,
) -> Tuple[bool, str, int, ContextSource]:
    """
    Check schedule with data source.
    Returns (has_conflict, message, entry_count, source).
    """
    events = entries if entries is not None else load_schedules(data_path)
    source = ContextSource.HUMAN if entries is not None else ContextSource.RUNTIME_FILE
    entry_count = len(events)

    for event in events:
        if event.get("date") == date:
            return False, f"Schedule conflict with {event.get('name')} on {date}", entry_count, source

    if entry_count == 0:
        return True, "No schedule conflict (no known entries)", 0, ContextSource.NONE

    return True, "No schedule conflict", entry_count, source


def add_event(name: str, date: str) -> Tuple[bool, str]:
    events = load_schedules()
    for event in events:
        if event.get("date") == date:
            return False, f"Schedule conflict with {event.get('name')}"
    events.append({"name": name, "date": date})
    if not Path.exists(DATA_FILE):
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_FILE, "w") as f:
        json.dump(events, f, indent=2)
    return True, "Event added"
