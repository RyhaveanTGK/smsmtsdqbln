import re
from dataclasses import dataclass


E164_RE = re.compile(r"^\+[1-9]\d{7,14}$")


@dataclass
class ContactValidation:
    valid: list[str]
    invalid: list[dict[str, str]]
    duplicates_removed: int
    input_count: int


def normalize_phone(raw: str) -> str:
    value = str(raw or "").strip()
    value = re.sub(r"[\s().-]", "", value)
    if value.startswith("00"):
        value = "+" + value[2:]
    return value


def validate_numbers(numbers: list[str]) -> ContactValidation:
    valid: list[str] = []
    invalid: list[dict[str, str]] = []
    seen: set[str] = set()
    duplicates = 0

    for raw in numbers:
        value = normalize_phone(raw)
        if not value:
            continue
        if not E164_RE.fullmatch(value):
            invalid.append({"value": str(raw).strip(), "reason": "E.164 formatı tələb olunur (məs: +9955XXXXXXX)."})
            continue
        if value in seen:
            duplicates += 1
            continue
        seen.add(value)
        valid.append(value)

    return ContactValidation(
        valid=valid,
        invalid=invalid,
        duplicates_removed=duplicates,
        input_count=len(numbers),
    )
