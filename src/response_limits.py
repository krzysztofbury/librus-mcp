"""Shared safety limits for non-attachment upstream response bodies."""

MAX_RESPONSE_BODY_BYTES = 4 * 1024 * 1024
RESPONSE_READ_CHUNK_BYTES = 64 * 1024


class ResponseTooLargeError(RuntimeError):
    """An upstream response exceeded the bounded in-memory body limit."""
