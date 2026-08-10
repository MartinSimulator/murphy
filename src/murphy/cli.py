"""Command-line entry point for Murphy."""

# Use newer behavior for type annotations
from __future__ import annotations

# Python's standard library for command-line parsing
import argparse
from pathlib import Path
# Import the version from the package to display in the help message
from murphy import __version__
from murphy.execution.run_ask import run_ask

# argv is the list of arguments passed to the script (None indicates we don't have to pass any arguments)
# return value is an integer indicating success (0) or failure (non-zero)
def main(argv: list[str] | None = None) -> int:
    # Create an argument parser for the script
    parser = argparse.ArgumentParser(
        prog="murphy",
        description="Voice-controlled orchestration for developer workflows",
    )
    # Add an argument to display the version
    parser.add_argument(
        "--version",
        action="version",
        version=f"murphy {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command")

    ask_parser = subparsers.add_parser("ask", help="Ask Murphy a question")
    ask_parser.add_argument("text", help="What you want Murphy to do")
    ask_parser.add_argument("--project-root", type=Path, required=True, help="Project directory for tool calls")
    ask_parser.add_argument("--confirm-phrase", default=None, help="Phrase to approve confirm_required actions")

    # Parse the arguments and store them in args
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "ask":
        return run_ask(args)

    parser.print_help()
    return 0

# If the script is run directly, raise a SystemExit with the result of main()
if __name__ == "__main__":
    raise SystemExit(main())
