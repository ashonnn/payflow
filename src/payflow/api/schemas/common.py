from typing import Annotated

from pydantic import AfterValidator, Field

from payflow.domain.phone import normalize_phone

PhoneNumber = Annotated[
    str,
    Field(max_length=32, examples=["+77011234567"]),
    AfterValidator(normalize_phone),
]
