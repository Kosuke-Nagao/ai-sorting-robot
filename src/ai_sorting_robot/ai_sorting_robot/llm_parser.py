"""Convert a natural-language sorting instruction into a validated command."""

import json
import os
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen

from .command_schema import SortCommand


DEFAULT_BASE_URL = "http://host.docker.internal:11434"
DEFAULT_MODEL = "qwen2.5:3b"


def _prompt(instruction: str) -> str:
    return f"""You are a robot sorting command parser.
Read the user's Japanese or English instruction and return JSON only.

Allowed colors: red, blue, yellow
Allowed destinations: left, right

Required JSON schema:
{{"color":"red|blue|yellow","destination":"left|right"}}

If the instruction is ambiguous or does not specify one allowed color and one
allowed destination, return {{"error":"ambiguous"}}.
Do not return coordinates, explanations, or Markdown.

User instruction:
{instruction}
"""


def parse_instruction(instruction: str) -> SortCommand:
    """Ask the local LLM for a command and validate its constrained output."""
    instruction = instruction.strip()
    if not instruction:
        raise ValueError("The instruction is empty")

    base_url = os.environ.get("OLLAMA_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    model = os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL)
    payload = {
        "model": model,
        "prompt": _prompt(instruction),
        "format": "json",
        "stream": False,
        "options": {"temperature": 0},
    }
    request = Request(
        f"{base_url}/api/generate",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=90) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(
            f"Could not connect to Ollama at {base_url}. "
            "Start Ollama and confirm OLLAMA_MODEL is available."
        ) from exc

    raw_result = response_data.get("response", "")
    try:
        result = json.loads(raw_result)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM returned non-JSON output: {raw_result}") from exc

    if "error" in result:
        raise ValueError("The instruction is ambiguous; no robot motion was started")

    try:
        command = SortCommand(
            color=str(result["color"]).lower(),
            destination=str(result["destination"]).lower(),
        )
    except (KeyError, TypeError) as exc:
        raise ValueError(f"LLM output does not match the command schema: {result}") from exc

    command.validate()
    return command
