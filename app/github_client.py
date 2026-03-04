import httpx
from app.auth import get_installation_token, generate_jwt

GITHUB_API = "https://api.github.com"


async def _headers(installation_id: int) -> dict:
    token = await get_installation_token(installation_id)
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
    }


async def get_pr_files(
    installation_id: int, owner: str, repo: str, pr_number: int
) -> list[dict]:
    headers = await _headers(installation_id)
    url = f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{pr_number}/files"

    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.json()


async def get_pr_diff(
    installation_id: int, owner: str, repo: str, pr_number: int
) -> str:
    token = await get_installation_token(installation_id)
    url = f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{pr_number}"

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            url,
            headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github.v3.diff",
            },
        )
        resp.raise_for_status()
        return resp.text


async def post_comment(
    installation_id: int, owner: str, repo: str, pr_number: int, body: str
) -> dict:
    headers = await _headers(installation_id)
    url = f"{GITHUB_API}/repos/{owner}/{repo}/issues/{pr_number}/comments"

    async with httpx.AsyncClient() as client:
        resp = await client.post(url, headers=headers, json={"body": body})
        resp.raise_for_status()
        return resp.json()


async def get_installation(installation_id: int) -> dict:
    """Fetch installation details from GitHub using the App JWT."""
    app_jwt = generate_jwt()
    url = f"{GITHUB_API}/app/installations/{installation_id}"

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            url,
            headers={
                "Authorization": f"Bearer {app_jwt}",
                "Accept": "application/vnd.github+json",
            },
        )
        resp.raise_for_status()
        return resp.json()
