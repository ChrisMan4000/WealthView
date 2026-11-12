#!/usr/bin/env python3
"""WealthView data refresh - launcher (the code lives in the wealthview package).
Run by hand:   python refresh.py     (the dashboard's REFRESH button runs it too)"""
import sys

from wealthview.app.refresh import run_cli

if __name__ == "__main__":
    raise SystemExit(run_cli(sys.argv))
