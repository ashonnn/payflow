from typing import ClassVar
from uuid import UUID

from fastapi import FastAPI
from sqladmin import Admin, Flash, ModelView, action
from sqladmin.authentication import AuthenticationBackend, get_current_user_id
from sqladmin.filters import StaticValuesFilter
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from payflow.core.clock import utc_now
from payflow.core.security import PasswordHasher
from payflow.db.models import (
    Account,
    LedgerEntry,
    Notification,
    OutboxEvent,
    ReconciliationReport,
    Transaction,
    User,
    WebhookEvent,
)
from payflow.db.repositories.users import UserRepository
from payflow.domain.enums import TransactionStatus
from payflow.domain.exceptions import DomainError
from payflow.domain.phone import normalize_phone
from payflow.domain.services.reviews import ReviewService


class AdminAuth(AuthenticationBackend):
    """Session login for users flagged as administrators."""

    def __init__(
        self,
        secret_key: str,
        session_factory: async_sessionmaker[AsyncSession],
        hasher: PasswordHasher,
    ) -> None:
        super().__init__(secret_key=secret_key)
        self._session_factory = session_factory
        self._hasher = hasher

    async def login(self, request: Request) -> bool:
        form = await request.form()
        password = str(form.get("password", ""))
        try:
            phone = normalize_phone(str(form.get("username", "")))
        except ValueError:
            return False
        async with self._session_factory() as session:
            user = await UserRepository(session).get_by_phone(phone)
        if user is None or not (user.is_admin and user.is_active):
            await self._hasher.verify_against_dummy(password)
            return False
        if not await self._hasher.verify(user.password_hash, password):
            return False
        request.session["user_id"] = str(user.id)
        return True

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        user_id = request.session.get("user_id")
        if user_id is None:
            return False
        async with self._session_factory() as session:
            user = await UserRepository(session).get(UUID(user_id))
        return user is not None and user.is_admin and user.is_active


class ReadOnlyView(ModelView):
    can_create = False
    can_edit = False
    can_delete = False


class UserAdmin(ModelView, model=User):
    icon = "fa-solid fa-user"
    can_create = False
    can_delete = False
    column_list: ClassVar = [
        User.phone,
        User.full_name,
        User.is_active,
        User.is_admin,
        User.created_at,
    ]
    column_searchable_list: ClassVar = [User.phone, User.full_name]
    column_default_sort: ClassVar = [(User.created_at, True)]
    column_details_exclude_list: ClassVar = [User.password_hash]
    form_columns: ClassVar = [User.full_name, User.is_active, User.is_admin]


class AccountAdmin(ReadOnlyView, model=Account):
    icon = "fa-solid fa-wallet"
    column_list: ClassVar = [
        Account.id,
        Account.user,
        Account.system_code,
        Account.currency,
        Account.balance,
    ]
    column_sortable_list: ClassVar = [Account.balance]


class TransactionAdmin(ReadOnlyView, model=Transaction):
    icon = "fa-solid fa-right-left"
    column_list: ClassVar = [
        Transaction.created_at,
        Transaction.type,
        Transaction.status,
        Transaction.amount,
        Transaction.currency,
        Transaction.initiator,
        Transaction.counterparty,
        Transaction.review_reasons,
    ]
    column_default_sort: ClassVar = [(Transaction.created_at, True)]
    column_searchable_list: ClassVar = [Transaction.external_id]
    column_filters: ClassVar = [
        StaticValuesFilter(
            Transaction.status,
            [(status.value, status.value) for status in TransactionStatus],
        )
    ]

    @action(
        name="approve",
        label="Approve",
        confirmation_message="Release the held funds to the recipient?",
    )
    async def approve(self, request: Request) -> Response:
        return await self._review(request, approve=True)

    @action(
        name="reject",
        label="Reject",
        confirmation_message="Return the held funds to the sender?",
    )
    async def reject(self, request: Request) -> Response:
        return await self._review(request, approve=False)

    async def _review(self, request: Request, *, approve: bool) -> Response:
        reviewer_id = UUID(str(get_current_user_id(request)))
        ids = [UUID(pk) for pk in request.query_params.get("pks", "").split(",") if pk]
        resolved = 0
        for transaction_id in ids:
            async with self.session_maker() as session:
                reviews = ReviewService(session, utc_now)
                try:
                    if approve:
                        await reviews.approve(transaction_id, reviewer_id)
                    else:
                        await reviews.reject(
                            transaction_id, reviewer_id, "rejected by an administrator"
                        )
                except DomainError as exc:
                    Flash.error(request, f"{transaction_id}: {exc.message}")
                    continue
                await session.commit()
                resolved += 1
        if resolved:
            verb = "approved" if approve else "rejected"
            Flash.success(request, f"{resolved} transfer(s) {verb}")
        list_url = request.url_for("admin:list", identity=self.identity)
        return RedirectResponse(request.headers.get("referer") or list_url, 302)


class LedgerEntryAdmin(ReadOnlyView, model=LedgerEntry):
    icon = "fa-solid fa-book"
    name_plural = "Ledger entries"
    column_list: ClassVar = [
        LedgerEntry.id,
        LedgerEntry.transaction_id,
        LedgerEntry.account_id,
        LedgerEntry.currency,
        LedgerEntry.amount,
        LedgerEntry.created_at,
    ]
    column_default_sort: ClassVar = [(LedgerEntry.id, True)]


class OutboxEventAdmin(ReadOnlyView, model=OutboxEvent):
    icon = "fa-solid fa-paper-plane"
    column_list: ClassVar = [
        OutboxEvent.id,
        OutboxEvent.event_type,
        OutboxEvent.status,
        OutboxEvent.attempts,
        OutboxEvent.last_error,
        OutboxEvent.created_at,
        OutboxEvent.processed_at,
    ]
    column_default_sort: ClassVar = [(OutboxEvent.id, True)]


class NotificationAdmin(ReadOnlyView, model=Notification):
    icon = "fa-solid fa-bell"
    column_list: ClassVar = [
        Notification.id,
        Notification.user_id,
        Notification.message,
        Notification.created_at,
    ]
    column_default_sort: ClassVar = [(Notification.id, True)]


class WebhookEventAdmin(ReadOnlyView, model=WebhookEvent):
    icon = "fa-solid fa-plug"
    column_list: ClassVar = [
        WebhookEvent.id,
        WebhookEvent.event_type,
        WebhookEvent.received_at,
    ]
    column_default_sort: ClassVar = [(WebhookEvent.received_at, True)]


class ReconciliationReportAdmin(ReadOnlyView, model=ReconciliationReport):
    icon = "fa-solid fa-scale-balanced"
    column_list: ClassVar = [
        ReconciliationReport.id,
        ReconciliationReport.status,
        ReconciliationReport.accounts_checked,
        ReconciliationReport.started_at,
        ReconciliationReport.finished_at,
    ]
    column_default_sort: ClassVar = [(ReconciliationReport.id, True)]


VIEWS: tuple[type[ModelView], ...] = (
    TransactionAdmin,
    AccountAdmin,
    UserAdmin,
    LedgerEntryAdmin,
    OutboxEventAdmin,
    NotificationAdmin,
    WebhookEventAdmin,
    ReconciliationReportAdmin,
)


def mount_admin(
    app: FastAPI,
    session_factory: async_sessionmaker[AsyncSession],
    hasher: PasswordHasher,
    secret_key: str,
) -> Admin:
    admin = Admin(
        app,
        session_maker=session_factory,
        authentication_backend=AdminAuth(secret_key, session_factory, hasher),
        title="PayFlow admin",
    )
    for view in VIEWS:
        admin.add_view(view)
    return admin
