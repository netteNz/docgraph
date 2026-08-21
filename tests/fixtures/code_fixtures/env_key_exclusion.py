"""Fixture 8: os.getenv/os.environ-sourced module-level assignments must
not be treated as connective constants, while a real constant still is."""
import os

API_KEY = os.getenv("API_KEY")
ANOTHER_SECRET = os.environ["ANOTHER_SECRET"]
REAL_CONST = 42


def uses_both(x):
    if API_KEY and ANOTHER_SECRET:
        return x + REAL_CONST
    return x
