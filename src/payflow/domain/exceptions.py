class DomainError(Exception):
    code = "domain_error"
    default_message = "the request could not be processed"

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.default_message
        super().__init__(self.message)


class BadRequestError(DomainError):
    code = "bad_request"


class NotFoundError(DomainError):
    code = "not_found"
    default_message = "resource not found"


class ConflictError(DomainError):
    code = "conflict"
    default_message = "the request conflicts with the current state"


class BusinessRuleError(DomainError):
    code = "business_rule_violation"


class AuthenticationError(DomainError):
    code = "authentication_failed"
    default_message = "authentication failed"


class PermissionDeniedError(DomainError):
    code = "permission_denied"
    default_message = "you are not allowed to perform this action"


class ServiceUnavailableError(DomainError):
    code = "service_unavailable"
    default_message = "a dependency is temporarily unavailable"


class PhoneAlreadyRegisteredError(ConflictError):
    code = "phone_already_registered"
    default_message = "this phone number is already registered"


class InvalidCredentialsError(AuthenticationError):
    code = "invalid_credentials"
    default_message = "phone or password is incorrect"


class InvalidTokenError(AuthenticationError):
    code = "invalid_token"
    default_message = "token is invalid, expired or revoked"


class InactiveUserError(PermissionDeniedError):
    code = "user_inactive"
    default_message = "this account is deactivated"


class AccountNotFoundError(NotFoundError):
    code = "account_not_found"
    default_message = "account not found"


class TransactionNotFoundError(NotFoundError):
    code = "transaction_not_found"
    default_message = "transaction not found"


class InsufficientFundsError(ConflictError):
    code = "insufficient_funds"
    default_message = "insufficient funds"


class RecipientNotFoundError(NotFoundError):
    code = "recipient_not_found"
    default_message = "no active user with this phone number"


class SelfTransferError(BusinessRuleError):
    code = "self_transfer"
    default_message = "cannot transfer to yourself"


class TransactionNotReviewableError(ConflictError):
    code = "not_reviewable"
    default_message = "only transfers waiting for review can be approved or rejected"


class AdminRequiredError(PermissionDeniedError):
    code = "admin_required"
    default_message = "this action requires an administrator"


class RateLimitExceededError(DomainError):
    code = "rate_limited"
    default_message = "too many requests, retry later"

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__()
        self.retry_after_seconds = retry_after_seconds


class IdempotencyKeyRequiredError(BadRequestError):
    code = "idempotency_key_required"
    default_message = "this endpoint requires an Idempotency-Key header"


class IdempotencyKeyReusedError(BusinessRuleError):
    code = "idempotency_key_reused"
    default_message = "this Idempotency-Key was already used with a different request"


class IdempotencyKeyInProgressError(ConflictError):
    code = "idempotency_key_in_progress"
    default_message = "a request with this Idempotency-Key is still being processed"


class InvalidWebhookSignatureError(BadRequestError):
    code = "invalid_signature"
    default_message = "webhook signature is missing or invalid"


class InvalidWebhookPayloadError(BadRequestError):
    code = "invalid_payload"
    default_message = "webhook payload is malformed"


class UnknownPaymentError(NotFoundError):
    code = "unknown_payment"
    default_message = "no deposit matches this payment"


class PaymentProviderUnavailableError(ServiceUnavailableError):
    code = "payment_provider_unavailable"
    default_message = "the payment provider is unavailable, retry later"


class RatesUnavailableError(ServiceUnavailableError):
    code = "rates_unavailable"
    default_message = "exchange rates are unavailable, retry later"


class SameCurrencyExchangeError(BusinessRuleError):
    code = "same_currency"
    default_message = "source and target currency must differ"


class ExchangeAmountTooSmallError(BusinessRuleError):
    code = "amount_too_small"
    default_message = "amount is too small to convert"
