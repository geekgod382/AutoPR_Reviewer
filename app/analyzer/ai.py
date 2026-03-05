import json
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
    {"description": "Bug description", "file": "filename", "severity": "high/medium/low"}
  ],
  "style_issues": [
    {"description": "Style issue description", "file": "filename"}
  ],
  "performance": [
    {"description": "Performance suggestion", "file": "filename"}
  ],
  "security": [
    {"description": "Security concern", "file": "filename", "severity": "high/medium/low"}
  ]
}

Rules:
- Only report real issues, not nitpicks
- If there are no issues in a category, return an empty array
- Be specific about file names and what the issue is
- Keep descriptions concise but actionable"""


async def run_ai_analysis(diff: str, files: list[dict]) -> dict:
    file_list = ", ".join(f.get("filename", "") for f in files[:20])
    compressed_diff = compress_diff(diff)
    prompt = f"## Files changed\n{file_list}\n\n## Diff\n```\n{compressed_diff}\n```"

    # Try Gemini first, fall back to Groq on failure
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
        response = await asyncio.to_thread(client.models.generate_content,
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
    
def compress_diff(diff : str, max_chars : int = 8000) -> str:
    lines = diff.splitlines()
    important = [line for line in lines if line.startswith(('+', '-', '@@', '---', '+++'))]
    compressed = "\n".join(important)
    if len(compressed) > max_chars:
        compressed = compressed[:max_chars] + "\n...[truncated]..."
    return compressed


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
                    "model": "llama-3.3-70b-versatile",
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

def _empty_result() -> dict:
    return {
        "summary": "AI analysis unavailable",
        "bugs": [],
        "style_issues": [],
        "performance": [],
        "security": [],
    }
