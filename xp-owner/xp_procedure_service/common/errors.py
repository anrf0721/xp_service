"""Domain errors. This service has no secret material to leak."""


class ConfigurationError(Exception):
    """Required process configuration is missing or unsafe."""
