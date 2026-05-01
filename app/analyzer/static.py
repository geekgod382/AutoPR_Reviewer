import asyncio
import tempfile
import os
import logging
import re
from app.github_client import get_file_content


logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".py", ".js", ".ts", ".jsx", ".tsx"}


async def run_static_analysis(
    files: list[dict],
    installation_id: int,
    owner: str,
    repo: str,
    ref: str,
) -> list[dict]:
    findings = []

    python_files = [
        f
        for f in files
        if os.path.splitext(f.get("filename", ""))[-1] in {".py"} and f.get("patch")
    ]

    jsts_files = [
        f
        for f in files
        if os.path.splitext(f.get("filename", ""))[-1]
        in (SUPPORTED_EXTENSIONS - {".py"})
        and f.get("patch")
    ]

    if not python_files and not jsts_files:
        return findings

    with tempfile.TemporaryDirectory() as tmpdir:
        for f in python_files:
            filename = f["filename"]
            patch = f.get("patch", "")

            full_content = await get_file_content(
                installation_id, owner, repo, filename, ref
            )
            if full_content is None:
                logger.warning(
                    "Could not fetch full content for %s, skipping", filename
                )
                continue

            safe_name = filename.replace("/", "_")
            filepath = os.path.join(tmpdir, safe_name)
            with open(filepath, "w", encoding="utf-8") as fh:
                fh.write(full_content)

            changed_lines = _get_diff_line_numbers(patch)
            ruff_results = await _run_ruff([filepath])

            for finding in ruff_results:
                if finding.get("line") in changed_lines:
                    finding["filename"] = filename
                    findings.append(finding)

        for f in jsts_files:
            filename = f["filename"]
            patch = f.get("patch", "")

            full_content = await get_file_content(
                installation_id, owner, repo, filename, ref
            )
            if full_content is None:
                logger.warning(
                    "Could not fetch full content for %s, skipping", filename
                )
                continue

            safe_name = filename.replace("/", "_")
            filepath = os.path.join(tmpdir, safe_name)
            with open(filepath, "w", encoding="utf-8") as fh:
                fh.write(full_content)

            changed_lines = _get_diff_line_numbers(patch)
            eslint_results = await _run_eslint([filepath])

            for finding in eslint_results:
                if finding.get("line") in changed_lines:
                    finding["filename"] = filename
                    findings.append(finding)

    return findings


def _get_diff_line_numbers(patch: str) -> set[int]:
    """Extract the actual file line numbers that were added/changed in the diff."""
    changed_lines = set()
    current_line = 0

    for line in patch.split("\n"):
        if line.startswith("@@"):
            import re

            match = re.search(r"\+(\d+)", line)
            if match:
                current_line = int(match.group(1)) - 1
        elif line.startswith("+") and not line.startswith("+++"):
            current_line += 1
            changed_lines.add(current_line)
        elif not line.startswith("-"):
            current_line += 1

    return changed_lines


def _extract_added_lines(patch: str) -> str:
    lines = []
    for line in patch.split("\n"):
        if line.startswith("+") and not line.startswith("+++"):
            lines.append(line[1:])
        elif not line.startswith("-") and not line.startswith("@@"):
            lines.append(line)
    return "\n".join(lines)


async def _run_ruff(file_paths: list[str]) -> list[dict]:
    findings = []
    try:
        proc = await asyncio.create_subprocess_exec(
            "ruff",
            "check",
            "--output-format=concise",
            "--line-length=120",
            *file_paths,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        output = stdout.decode("utf-8", errors="replace")

        for line in output.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split(":")
            if len(parts) >= 4:
                try:
                    line_num = int(parts[1])
                except ValueError:
                    line_num = None
                findings.append(
                    {
                        "tool": "ruff",
                        "line": line_num,
                        "message": line.strip(),
                        "severity": "style",
                    }
                )

    except FileNotFoundError:
        logger.warning("ruff not found, skipping static analysis")
    except Exception as e:
        logger.error("ruff error: %s", e)

    return findings


async def _run_eslint(file_paths: list[str]) -> list[dict]:
    findings = []
    try:
        proc = await asyncio.create_subprocess_exec(
            "eslint",
            "--format=compact",
            "--no-eslintrc",
            "--env=browser,node,es2021",
            *file_paths,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        output = stdout.decode("utf-8", errors="replace")

        for line in output.strip().split("\n"):
            if not line.strip():
                continue
            match = re.search(r":(\d+):\d+:", line)
            findings.append(
                {
                    "tool": "eslint",
                    "line": int(match.group(1)) if match else None,
                    "message": line.strip(),
                    "severity": "style",
                }
            )

    except FileNotFoundError:
        logger.warning("eslint not found, skipping static analysis")
    except Exception as e:
        logger.error("eslint error: %s", e)

    return findings
