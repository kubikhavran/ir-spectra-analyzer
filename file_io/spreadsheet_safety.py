"""Safety helpers for values opened by spreadsheet applications."""

_FORMULA_PREFIXES = frozenset("=+-@")


def neutralize_spreadsheet_formula(value: str) -> str:
    """Force formula-looking user text to remain literal spreadsheet text."""
    first_non_whitespace = next((char for char in value if not char.isspace()), "")
    if first_non_whitespace in _FORMULA_PREFIXES:
        return f"'{value}"
    return value
