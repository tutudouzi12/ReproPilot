def score_items(values: list[int]) -> int:
    # Deliberately flawed baseline: zero is not a positive value.
    return sum(value >= 0 for value in values)
