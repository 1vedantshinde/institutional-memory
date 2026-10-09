#!/usr/bin/env python3
"""Alias script for ingest_all.py."""
import sys
from pathlib import Path

# Forward execution to ingest_all
import ingest_all

if __name__ == "__main__":
    ingest_all.main()
