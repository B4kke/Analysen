import re


class InvalidOrganizationNumber(ValueError):
    """Raised when a Norwegian organisation number is syntactically invalid."""


def normalize_orgnr(value: str) -> str:
    compact = re.sub(r"\s+", "", value)
    if len(compact) != 9 or not compact.isdigit():
        raise InvalidOrganizationNumber("Organisation number must contain exactly 9 digits")
    if not is_valid_orgnr(compact):
        raise InvalidOrganizationNumber("Organisation number has an invalid check digit")
    return compact


def is_valid_orgnr(value: str) -> bool:
    if len(value) != 9 or not value.isdigit():
        return False
    digits = [int(character) for character in value]
    weights = (3, 2, 7, 6, 5, 4, 3, 2)
    remainder = sum(digit * weight for digit, weight in zip(digits[:8], weights, strict=True)) % 11
    expected = 11 - remainder
    if expected == 11:
        expected = 0
    if expected == 10:
        return False
    return digits[8] == expected
