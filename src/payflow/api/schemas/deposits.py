from pydantic import BaseModel

from payflow.api.schemas.common import Amount
from payflow.domain.enums import Currency


class DepositRequest(BaseModel):
    currency: Currency
    amount: Amount
