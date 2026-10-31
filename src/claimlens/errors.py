class ClaimLensError(Exception):
    """Base class. ``public`` messages are safe to show to API callers."""

    status = 400

    def __init__(self, public: str = "request failed") -> None:
        super().__init__(public)
        self.public = public


class NotFound(ClaimLensError):
    status = 404


class Forbidden(ClaimLensError):
    status = 403


class Conflict(ClaimLensError):
    status = 409


class BadRequest(ClaimLensError):
    status = 400


class PayloadTooLarge(ClaimLensError):
    status = 413
