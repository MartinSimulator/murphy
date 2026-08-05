"""Command-line entry point for Murphy."""

from __future__ import annotations

import argparse

from murphy import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="murphy",
        description="Voice-controlled orchestration for developer workflows",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"murphy {__version__}",
    )
    parser.parse_args(argv)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
