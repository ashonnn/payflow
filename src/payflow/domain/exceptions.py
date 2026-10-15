class DomainError(Exception):
    code = "domain_error"
    default_message = "the request could not be processed"

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.default_message
        super().__init__(self.message)


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
