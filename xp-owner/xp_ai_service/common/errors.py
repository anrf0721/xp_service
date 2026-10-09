"""Domain errors without secrets."""


class ConflictError(LookupError):
    """Same request id was already stored with different input."""
