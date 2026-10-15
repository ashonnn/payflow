from typing import Annotated

from pydantic import BaseModel, StringConstraints

from payflow.api.schemas.common import Amount, PhoneNumber
from payflow.domain.enums import Currency

Comment = Annotated[str, StringConstraints(strip_whitespace=True, max_length=140)]


class TransferRequest(BaseModel):
    to_phone: PhoneNumber
    amount: Amount
    currency: Currency
    comment: Comment | None = None
