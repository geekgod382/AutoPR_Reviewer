import time
import jwt
import httpx
from app.config import get_settings

_token_cache: dict[int, tuple[str, float]] = {}


def _get_private_key() -> str:
    settings = get_settings()
    return settings.github_private_key

def generate_jwt() -> str:
    settings = get_settings()
    now = int(time.time())
    payload = {
        "iat": now - 60,
        "exp": now + (10 * 60),
        "iss": settings.github_app_id,
    }
    private_key = _get_private_key()
    return jwt.encode(payload, private_key, algorithm="RS256")


async def get_installation_token(installation_id: int) -> str:
    now = time.time()

    if installation_id in _token_cache:
        token, expires_at = _token_cache[installation_id]
        if now < expires_at - 60:
            return token

    app_jwt = generate_jwt()
    url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {app_jwt}",
                "Accept": "application/vnd.github+json",
            },
        )
        resp.raise_for_status()
        data = resp.json()

    token = data["token"]
    expires_at = time.time() + 3500
    _token_cache[installation_id] = (token, expires_at)
    return token
