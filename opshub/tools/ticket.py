import json
from pathlib import Path
from typing import Tuple

DATA_FILE = Path(__file__).parent.parent.parent / "data" / "tickets.json"

def load_tickets() -> list:
    if not DATA_FILE.exists():
        return []
    with open(DATA_FILE) as f:
        return json.load(f)

def create_ticket(title: str, priority: str = "medium") -> Tuple[bool, str]:
    if not Path.exists(DATA_FILE):
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    tickets = load_tickets()
    ticket_id = f"TKT-{len(tickets)+1:03d}"
    tickets.append({
        "id": ticket_id,
        "title": title,
        "priority": priority,
        "status": "open"
    })
    with open(DATA_FILE, "w") as f:
        json.dump(tickets, f, indent=2)
    return True, f"Ticket created: {ticket_id}"

def get_ticket_status(ticket_id: str) -> Tuple[bool, str]:
    tickets = load_tickets()
    for ticket in tickets:
        if ticket.get("id") == ticket_id:
            return True, f"Status: {ticket.get('status')}"
    return False, "Ticket not found"
