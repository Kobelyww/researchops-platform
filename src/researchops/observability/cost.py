"""Token cost accounting. Prices are USD per 1M tokens (editable table)."""

from __future__ import annotations

# USD per 1M tokens: (input, output). Unknown models cost $0 (logged as such).
MODEL_PRICES: dict[str, tuple[float, float]] = {
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4.1-mini": (0.40, 1.60),
    "o3-mini": (1.10, 4.40),
    "deepseek-chat": (0.27, 1.10),
    "deepseek-reasoner": (0.55, 2.19),
    "claude-3-5-sonnet": (3.00, 15.00),
    "claude-sonnet-4": (3.00, 15.00),
    "mock-1": (0.0, 0.0),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    prices = MODEL_PRICES.get(model)
    if prices is None:
        # longest prefix wins, so "gpt-4o-mini-2024" matches gpt-4o-mini, not gpt-4o
        known = sorted(MODEL_PRICES, key=len, reverse=True)
        for prefix in known:
            if model.startswith(prefix):
                prices = MODEL_PRICES[prefix]
                break
    if prices is None:
        return 0.0
    in_price, out_price = prices
    return input_tokens / 1e6 * in_price + output_tokens / 1e6 * out_price
