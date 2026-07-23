"""CLI entrypoint.

    python -m src.main run <scenario>     # one session
    python -m src.main demo               # happy -> retry_storm -> bad_rag -> tool_loop
    python -m src.main list               # list scenarios

Give the exporters a moment to flush at the end (BatchSpanProcessor is async).
"""
from __future__ import annotations

import sys
import time

from .scenarios import ALL
from .telemetry import init_telemetry


def _flush_pause() -> None:
    # Let the batch processors ship the last spans/metrics/logs before exit.
    time.sleep(7)


def cmd_list() -> None:
    print("Available scenarios:")
    for key, s in ALL.items():
        print(f"  {key:12s} {s.title}\n               {s.notes}")


def cmd_run(key: str) -> None:
    if key not in ALL:
        print(f"unknown scenario '{key}'. Try: {', '.join(ALL)}")
        sys.exit(1)
    init_telemetry()
    from .agent import run_session  # import after telemetry is live

    result = run_session(ALL[key])
    print("\n--- outcome ---")
    print("decision:", result.get("decision"))
    print("failure_mode:", result.get("failure_mode") or "none")
    print("response:", (result.get("response") or "").strip())
    _flush_pause()


def cmd_demo() -> None:
    init_telemetry()
    from .agent import run_session

    for key in ["happy", "retry_storm", "bad_rag", "tool_loop"]:
        print(f"\n######## scenario: {key} ########")
        run_session(ALL[key])
        time.sleep(1)
    _flush_pause()


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] == "list":
        cmd_list()
    elif args[0] == "run" and len(args) > 1:
        cmd_run(args[1])
    elif args[0] == "demo":
        cmd_demo()
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
