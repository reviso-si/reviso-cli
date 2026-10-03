"""Client-side error types."""
from __future__ import annotations


class ValidationError(ValueError):
    """Raised when a request payload is invalid before it is sent."""
