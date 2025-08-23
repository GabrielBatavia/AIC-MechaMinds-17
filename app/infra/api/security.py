# app/infra/api/security.py
from fastapi import Depends, HTTPException, status
from fastapi.security.api_key import APIKeyHeader
import os, logging
log = logging.getLogger("api")

API_KEY_NAME = "X-Api-Key"
_api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

REQUIRE_API_KEY = os.getenv("REQUIRE_API_KEY", "1") == "1"
SERVICE_API_KEY = os.getenv("SERVICE_API_KEY", "")

async def require_api_key(api_key: str = Depends(_api_key_header)):
    if not REQUIRE_API_KEY:
        return
    if not SERVICE_API_KEY:
        log.warning("Auth fail: missing X-Api-Key")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service key not configured")
    if not api_key or api_key != SERVICE_API_KEY:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

