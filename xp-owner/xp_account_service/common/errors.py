"""Domain errors that never include secret material."""


class InvalidCredentialError(Exception):
    """The presented secret does not match a stored credential."""


class ConfigurationError(Exception):
    """Required process configuration is missing or unsafe."""
