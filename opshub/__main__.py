"""Launch the OpsHub TUI by default; CLI via -m opshub.cli."""

from opshub.tui.app import main


if __name__ == "__main__":
    raise SystemExit(main())
