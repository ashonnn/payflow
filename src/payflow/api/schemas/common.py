from decimal import Decimal
from typing import Annotated

from pydantic import AfterValidator, Field

from payflow.domain.money import to_cents
from payflow.domain.phone import normalize_phone

PhoneNumber = Annotated[
    str,
    Field(max_length=32, examples=["+77011234567"]),
    AfterValidator(normalize_phone),
]

Amount = Annotated[
    Decimal,
    Field(gt=0, max_digits=18, decimal_places=2, examples=["1500.00"]),
    AfterValidator(to_cents),
]
