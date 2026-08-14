def score_items(values: list[int]) -> int:
    return sum(value > 0 for value in values)
