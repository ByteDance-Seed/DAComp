import hmac
import os

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader

_SESSION_API_KEY = os.getenv('SESSION_API_KEY')
_SESSION_API_KEY_HEADER = APIKeyHeader(name='X-Session-API-Key', auto_error=False)


def check_session_api_key(
    session_api_key: str | None = Depends(_SESSION_API_KEY_HEADER),
):
    """Check the session API key and throw an exception if incorrect. Having this as a dependency
    means it appears in OpenAPI Docs
    """
    # Constant-time comparison to avoid leaking the key via timing. This
    # dependency is only registered when _SESSION_API_KEY is set (see
    # get_dependencies), so a missing/empty header must fail closed.
    if not session_api_key or not hmac.compare_digest(
        session_api_key, _SESSION_API_KEY or ''
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)


def get_dependencies() -> list[Depends]:
    result = []
    if _SESSION_API_KEY:
        result.append(Depends(check_session_api_key))
    return result
