from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from payflow.api.schemas.common import Amount
from payflow.domain.enums import Currency


class ExchangeRequest(BaseModel):
    from_currency: Currency
    to_currency: Currency
    amount: Amount


class QuoteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source: Currency
    target: Currency
    mid_rate: Decimal
    rate: Decimal
    as_of: datetime
