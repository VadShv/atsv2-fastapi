"""Entry point для запуска сида: python -m ats.infra.seeds."""

from __future__ import annotations

import sys

from ats.infra.seeds.cli import main

if __name__ == "__main__":
    sys.exit(main())
