"""Fixture 7: several small top-level functions, well under the token
threshold -- must never be sliced even though the def count alone would
otherwise qualify."""


def add(a, b):
    return a + b


def subtract(a, b):
    return a - b


def multiply(a, b):
    return a * b
