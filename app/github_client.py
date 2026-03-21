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


async def get_pr_head_sha(
    installation_id: int, owner: str, repo: str, pr_number: int
) -> str:
    """Return the latest commit SHA on the PR head — required for inline review comments."""
    headers = await _headers(installation_id)
    url = f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{pr_number}"

    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.json()["head"]["sha"]


async def post_comment(
    installation_id: int, owner: str, repo: str, pr_number: int, body: str
) -> dict:
    """Post a top-level issue comment on the PR conversation tab."""
    headers = await _headers(installation_id)
    url = f"{GITHUB_API}/repos/{owner}/{repo}/issues/{pr_number}/comments"

    async with httpx.AsyncClient() as client:
        resp = await client.post(url, headers=headers, json={"body": body})
        resp.raise_for_status()
        return resp.json()


async def post_review(
    installation_id: int,
    owner: str,
    repo: str,
    pr_number: int,
    commit_sha: str,
    summary_body: str,
    inline_comments: list[dict],
) -> dict:
    """
    Post a GitHub Pull Request Review with optional inline comments.

    Each item in inline_comments must have:
        path  : str   — file path relative to repo root (e.g. "app/payments.py")
        line  : int   — line number in the NEW version of the file
        body  : str   — the comment text

    The summary_body always appears on the conversation tab.
    If inline_comments is empty, this behaves like a plain review comment.
    """
    headers = await _headers(installation_id)
    url = f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{pr_number}/reviews"

    payload = {
        "commit_id": commit_sha,
        "body": summary_body,
        "event": "COMMENT",
        "comments": [
            {
                "path": c["path"],
                "line": c["line"],
                "body": c["body"],
                "side": "RIGHT",   # RIGHT = new version of the file
            }
            for c in inline_comments
        ],
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(url, headers=headers, json=payload)
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
