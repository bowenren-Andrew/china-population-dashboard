"""Number formatting helpers for the dashboard."""
from __future__ import annotations


def format_number(value: int | float) -> str:
    """Format a person count using Chinese 万/亿 units."""
    number = float(value)
    absolute = abs(number)
    if absolute >= 100_000_000:
        text = f"{absolute / 100_000_000:.2f} 亿"
    elif absolute >= 10_000:
        text = f"{absolute / 10_000:,.0f} 万"
    else:
        text = f"{absolute:,.0f} 人"
    if number < 0:
        return f"-{text}"
    return text
