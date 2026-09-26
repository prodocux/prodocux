"""Stable intake errors shared by continuable projection producers."""


class SourceTooLargeError(ValueError):
    """The source exceeds the advertised inline admission ceiling."""

