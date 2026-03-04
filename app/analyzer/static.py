import asyncio
import tempfile
import os
import logging

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".py"}


async def run_static_analysis(files: list[dict]) -> list[dict]:
    findings = []

    python_files = [
        f for f in files
        if os.path.splitext(f.get("filename", ""))[-1] in SUPPORTED_EXTENSIONS
        and f.get("patch")
    ]

    if not python_files:
        return findings

    with tempfile.TemporaryDirectory() as tmpdir:
        file_paths = []
        for f in python_files:
            filepath = os.path.join(tmpdir, os.path.basename(f["filename"]))
            patch_content = _extract_added_lines(f.get("patch", ""))
            with open(filepath, "w", encoding="utf-8") as fh:
                fh.write(patch_content)
            file_paths.append(filepath)

        flake8_results = await _run_flake8(file_paths)
        findings.extend(flake8_results)

    return findings


def _extract_added_lines(patch: str) -> str:
    lines = []
    for line in patch.split("\n"):
        if line.startswith("+") and not line.startswith("+++"):
            lines.append(line[1:])
        elif not line.startswith("-") and not line.startswith("@@"):
            lines.append(line)
    return "\n".join(lines)


async def _run_flake8(file_paths: list[str]) -> list[dict]:
    findings = []
    try:
        proc = await asyncio.create_subprocess_exec(
            "flake8",
            "--max-line-length=120",
            "--format=%(path)s:%(row)d:%(col)d: %(code)s %(text)s",
            *file_paths,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        output = stdout.decode("utf-8", errors="replace")

        for line in output.strip().split("\n"):
            if line.strip():
                findings.append({
                    "tool": "flake8",
                    "message": line.strip(),
                    "severity": "style",
                })
    except FileNotFoundError:
        logger.warning("flake8 not found, skipping static analysis")
    except Exception as e:
        logger.error("flake8 error: %s", e)

    return findings
