import json
import re
import logging
import httpx
from google import genai
from app.config import get_settings
import asyncio

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert code reviewer. Analyze the following PR diff and provide a structured review.

Return your response as valid JSON with this exact structure:
{
    "summary": "Brief summary of what this PR does",
    "bugs": [
        {"description": "Bug description", "file": "filename", "line": 42, "severity": "high/medium/low"}
    ],
    "style_issues": [
        {"description": "Style issue description", "file": "filename", "line": 10}
    ],
    "performance": [
        {"description": "Performance suggestion", "file": "filename", "line": 55}
    ],
    "security": [
        {"description": "Security concern", "file": "filename", "line": 30, "severity": "high/medium/low"}
    ]
}

Rules:
- Only report real issues, not nitpicks
- If there are no issues in a category, return an empty array
- Be specific about file names and what the issue is
- Keep descriptions concise but actionable
- The "line" field must be the line number in the NEW version of the file where the issue exists
- If you cannot determine a specific line, use null for the line field
- Provide proper suggestions for any issues you find
- Focus on the most important problems in the code"""


async def run_ai_analysis(diff: str, files: list[dict]) -> dict:
    file_list = ", ".join(f.get("filename", "") for f in files[:20])
    compressed_diff = compress_diff(diff)
    prompt = f"## Files changed\n{file_list}\n\n## Diff\n```\n{compressed_diff}\n```"

    tasks = [_try_gemini(prompt), _try_groq(prompt)]
    for task in tasks:
        result = await task
        if result is not None:
            return result

    return _empty_result()


async def _try_gemini(prompt: str) -> dict | None:
    settings = get_settings()
    try:
        client = genai.Client(api_key=settings.gemini_api_key)
        response = await asyncio.to_thread(
            client.models.generate_content,
            model="gemini-2.0-flash",
            contents=prompt,
            config=genai.types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=0.2,
                response_mime_type="application/json",
            ),
        )
        return json.loads(response.text)
    except json.JSONDecodeError:
        logger.error("Failed to parse Gemini response as JSON")
        return None
    except Exception as e:
        logger.error("Gemini API error: %s", e)
        return None


async def _try_groq(prompt: str) -> dict | None:
    settings = get_settings()
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.groq_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "gpt-oss-120b",
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.2,
                },
                timeout=60.0,
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                start = content.find("{")
                end = content.rfind("}") + 1
                return json.loads(content[start:end])
    except Exception as e:
        logger.error("Groq API error: %s", e)
        return None


def compress_diff(diff: str, max_chars: int = 8000) -> str:
    lines = diff.splitlines()
    important = [
        line for line in lines if line.startswith(("+", "-", "@@", "---", "+++"))
    ]
    compressed = "\n".join(important)
    if len(compressed) > max_chars:
        compressed = compressed[:max_chars] + "\n...[truncated]..."
    return compressed


def build_line_index(files: list[dict]) -> dict[tuple[str, int], bool]:
    """
    Build a set of (filename, line_number) pairs that are valid inline
    comment positions — i.e. lines that appear in the diff as additions.

    GitHub only allows inline comments on lines that exist in the diff.
    This index lets us validate AI-returned line numbers before submitting.

    Each file dict from the GitHub API has a `patch` field like:
        @@ -10,4 +10,6 @@
         context line
        +added line        ← line 11 in new file
        +added line        ← line 12 in new file
         context line
    """
    index: dict[tuple[str, int], bool] = {}

    for f in files:
        filename = f.get("filename", "")
        patch = f.get("patch", "")
        if not patch:
            continue

        new_line = 0
        for raw_line in patch.splitlines():
            # @@ -old_start,old_count +new_start,new_count @@
            hunk_match = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", raw_line)
            if hunk_match:
                new_line = int(hunk_match.group(1)) - 1
                continue

            if raw_line.startswith("-"):
                # Deleted line — not present in new file, no line number advance
                continue
            elif raw_line.startswith("+"):
                new_line += 1
                # Only additions are valid inline comment targets on RIGHT side
                index[(filename, new_line)] = True
            else:
                # Context line — exists in new file but not a valid comment target
                new_line += 1

    return index


def _empty_result() -> dict:
    return {
        "summary": "AI analysis unavailable",
        "bugs": [],
        "style_issues": [],
        "performance": [],
        "security": [],
    }
