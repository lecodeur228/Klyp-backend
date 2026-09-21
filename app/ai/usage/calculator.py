"""Cost calculator stub (V1)."""


def estimate_cost_usd(*, prompt_tokens: int, completion_tokens: int) -> float:
    # Placeholder rates — replace with provider pricing in production.
    return round((prompt_tokens * 0.00000015) + (completion_tokens * 0.0000006), 8)
