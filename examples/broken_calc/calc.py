"""Tiny calculator with a deliberate bug — Claude's job is to fix it."""


def add(a: int, b: int) -> int:
    # Bug: subtracting instead of adding.
    return a - b


def subtract(a: int, b: int) -> int:
    return a - b


def multiply(a: int, b: int) -> int:
    return a * b
