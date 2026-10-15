from fastapi import APIRouter

from payflow.api.deps import AccountServiceDep, CurrentUser
from payflow.api.schemas.accounts import AccountResponse

router = APIRouter(tags=["accounts"])


@router.get("/accounts")
async def list_accounts(
    user: CurrentUser, accounts: AccountServiceDep
) -> list[AccountResponse]:
    wallets = await accounts.list_wallets(user.id)
    return [AccountResponse.model_validate(wallet) for wallet in wallets]
