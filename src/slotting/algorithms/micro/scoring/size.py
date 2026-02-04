from __future__ import annotations


def size_penalty(size: int, gamma: float, p: int) -> float:
    return gamma * max(size - 2, 0) ** p


def size_penalty_delta(size: int, gamma: float, p: int) -> float:
    current = size_penalty(size, gamma, p)
    future = size_penalty(size + 1, gamma, p)
    return future - current
