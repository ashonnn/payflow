from payflow.domain.services.notifications import format_money, mask_phone


def test_money_is_grouped_with_two_decimals() -> None:
    assert format_money("1500000", "KZT") == "1,500,000.00 KZT"
    assert format_money("0.5", "USD") == "0.50 USD"


def test_phone_keeps_country_prefix_and_last_digits() -> None:
    assert mask_phone("+77011234567") == "+7701***4567"
