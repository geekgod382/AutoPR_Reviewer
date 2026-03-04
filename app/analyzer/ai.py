import json
import logging
from google import genai
from app.config import get_settings

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
    settings = get_settings()

    file_list = ", ".join(f.get("filename", "") for f in files[:20])
    prompt = f"## Files changed\n{file_list}\n\n## Diff\n```\n{diff[:15000]}\n```"

    try:
        client = genai.Client(api_key=settings.gemini_api_key)
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
            config=genai.types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=0.2,
                response_mime_type="application/json",
            ),
        )

        result = json.loads(response.text)
        return result

    except json.JSONDecodeError:
        logger.error("Failed to parse Gemini response as JSON")
        return _empty_result()
    except Exception as e:
        logger.error("Gemini API error: %s", e)
        return _empty_result()


def _empty_result() -> dict:
    return {
        "summary": "AI analysis unavailable",
        "bugs": [],
        "style_issues": [],
        "performance": [],
        "security": [],
    }
