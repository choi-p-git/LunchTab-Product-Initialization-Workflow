from __future__ import annotations

import re
import unicodedata
from collections import Counter

from lunchtab_product_init.models import PosNameResult

MAX_POS_NAME_LENGTH = 15

ABBREVIATIONS = {
    "assorted": "Asst",
    "breakfast": "Brkfst",
    "cheese": "Chz",
    "chicken": "Chk",
    "chocolate": "Choc",
    "cinnamon": "Cin",
    "classic": "Clsc",
    "deluxe": "Dlx",
    "drink": "Drnk",
    "drinks": "Drnks",
    "fruit": "Frt",
    "grilled": "Grld",
    "hamburger": "Burger",
    "jalapeno": "Jal",
    "macaroni": "Mac",
    "mozzarella": "Mozz",
    "pepperoni": "Pep",
    "sandwich": "Sand",
    "sausage": "Ssg",
    "strawberry": "Straw",
    "vegetable": "Veg",
    "vegetarian": "Veg",
    "yogurt": "Ygrt",
}

STOP_WORDS = {
    "a",
    "an",
    "and",
    "of",
    "the",
    "with",
}


def normalize_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.strip())
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", without_marks.casefold()))


def title_token(token: str) -> str:
    if not token:
        return ""
    return token.upper() if token.isdigit() else token[:1].upper() + token[1:]


def generate_pos_name(item_name: str, existing_names: set[str] | None = None) -> PosNameResult:
    existing_names = existing_names or set()
    normalized = normalize_text(item_name)
    if not normalized:
        return PosNameResult("", "review", "missing item name", "", ())

    tokens = normalized.split()
    steps: list[str] = [f"normalized={normalized}"]
    abbreviated = [ABBREVIATIONS.get(token, token) for token in tokens if token not in STOP_WORDS]
    steps.append("abbr=" + " ".join(abbreviated))
    candidate = " ".join(title_token(token) for token in abbreviated)
    if len(candidate) <= MAX_POS_NAME_LENGTH and candidate in existing_names:
        return PosNameResult(candidate, "review", "duplicate generated POS name", normalized, tuple(steps))
    if len(candidate) <= MAX_POS_NAME_LENGTH:
        return PosNameResult(candidate, "ok", "", normalized, tuple(steps))

    compact = "".join(title_token(token) for token in abbreviated)
    steps.append(f"compact={compact}")
    if len(compact) <= MAX_POS_NAME_LENGTH and compact in existing_names:
        return PosNameResult(compact, "review", "duplicate generated POS name", normalized, tuple(steps))
    if len(compact) <= MAX_POS_NAME_LENGTH:
        return PosNameResult(compact, "ok", "", normalized, tuple(steps))

    consonants = []
    for token in abbreviated:
        if len(token) <= 4:
            consonants.append(token)
        else:
            consonants.append(token[0] + re.sub(r"[aeiou]", "", token[1:]))
    shortened = "".join(title_token(token[:6]) for token in consonants)
    steps.append(f"consonants={shortened}")
    if len(shortened) <= MAX_POS_NAME_LENGTH and shortened in existing_names:
        return PosNameResult(shortened, "review", "duplicate generated POS name", normalized, tuple(steps))
    if len(shortened) <= MAX_POS_NAME_LENGTH:
        return PosNameResult(shortened, "ok", "", normalized, tuple(steps))

    clipped = shortened[:MAX_POS_NAME_LENGTH]
    reason = "duplicate generated POS name" if clipped in existing_names else "needs manual POS name"
    return PosNameResult(clipped, "review", reason, normalized, tuple(steps))


def duplicate_values(values: list[str]) -> set[str]:
    counts = Counter(value for value in values if value)
    return {value for value, count in counts.items() if count > 1}
