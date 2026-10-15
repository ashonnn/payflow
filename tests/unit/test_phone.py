import pytest

from payflow.domain.phone import normalize_phone


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+77011234567", "+77011234567"),
        ("+7 (701) 123-45-67", "+77011234567"),
        ("8 701 123 45 67", "+77011234567"),
        ("77011234567", "+77011234567"),
        ("+14155552671", "+14155552671"),
    ],
)
def test_normalizes_to_e164(raw: str, expected: str) -> None:
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize(
    "raw", ["", "12345", "+0123456789", "+7701abc4567", "+" + "1" * 16]
)
def test_rejects_invalid_numbers(raw: str) -> None:
    with pytest.raises(ValueError, match="international number"):
        normalize_phone(raw)
