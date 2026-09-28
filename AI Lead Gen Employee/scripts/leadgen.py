#!/usr/bin/env python3
"""Entry point. Usage: python3 scripts/leadgen.py <command> [options]. Standard library only."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from leadgen.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
