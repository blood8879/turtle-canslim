#!/usr/bin/env python3
"""Run Turtle-CANSLIM Terminal User Interface."""

from __future__ import annotations

import sys


def main() -> None:
    try:
        from src.tui.app import run_tui
        run_tui()
    except ImportError as e:
        print(f"Error: Missing dependency - {e}", file=sys.stderr)
        print("\nPlease install TUI dependencies:")
        print("  pip install textual rich")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nGoodbye!")
        sys.exit(0)


if __name__ == "__main__":
    main()
