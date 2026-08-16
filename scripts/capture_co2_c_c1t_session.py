#!/usr/bin/env python3
"""Compatibility entrypoint for the frozen C-C1T script identity."""

from pathlib import Path
import runpy


if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).resolve().parents[1] / "capture" / "capture_co2_session.py"), run_name="__main__")
