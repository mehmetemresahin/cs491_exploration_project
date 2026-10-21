"""Language models that turn a question into SQL, behind one small interface.

Two providers, picked by MOCK491_LLM (config.py):
  - ollama:    a local model over Ollama's HTTP API. Data and questions never leave the machine,
               matching the report's on-prem / KVKK stance. Detected automatically when running.
  - anthropic: Claude through the official SDK (`pip install -e ".[llm]"`). Sends the question
               and the table descriptions (not the data) to the API. Opt-in only.
Both return the same Draft, so the rest of genbi does not care which one answered.
"""

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, ValidationError

from mock491 import config


class Draft(BaseModel):
    sql: str  # empty when the question can't be answered from the tables
    explanation: str


DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "sql": {"type": "string", "description": "one DuckDB SELECT, or '' if unanswerable"},
        "explanation": {"type": "string", "description": "one or two sentences for the user"},
    },
    "required": ["sql", "explanation"],
    "additionalProperties": False,
}


class ModelError(RuntimeError):
    """The model could not be reached or gave no usable answer."""


class SqlModel(Protocol):
    name: str

    def draft(self, system: str, turns: list[dict]) -> Draft:
        """`turns` alternate user/assistant, starting and ending with a user turn."""
        ...


def _parse(text: str) -> Draft:
    try:
        return Draft.model_validate_json(text)
    except ValidationError as e:
        raise ModelError(f"The model's answer was not in the expected format: {text[:200]}") from e


class OllamaModel:
    def __init__(self, model: str = config.OLLAMA_MODEL, host: str = config.OLLAMA_HOST):
        self.model, self.host = model, host.rstrip("/")
        self.name = f"Ollama · {model} (local)"

    def draft(self, system: str, turns: list[dict]) -> Draft:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, *turns],
            "format": DRAFT_SCHEMA,
            "stream": False,
            "options": {"temperature": 0},
        }
        req = urllib.request.Request(
            f"{self.host}/api/chat",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                reply = json.load(resp)
        except urllib.error.HTTPError as e:
            raise ModelError(
                f"Ollama returned {e.code}: {e.read().decode(errors='replace')}"
            ) from e
        except (urllib.error.URLError, TimeoutError) as e:
            raise ModelError(f"Ollama is not reachable at {self.host}: {e}") from e
        return _parse(reply["message"]["content"])


class ClaudeModel:
    def __init__(self, model: str = config.ANTHROPIC_MODEL):
        try:
            import anthropic
        except ImportError as e:
            raise ModelError('The Anthropic SDK is not installed: pip install -e ".[llm]"') from e
        self._anthropic = anthropic
        self.client = anthropic.Anthropic()  # ANTHROPIC_API_KEY or an `ant auth login` profile
        self.model = model
        self.name = f"Claude · {model} (Anthropic API)"

    def draft(self, system: str, turns: list[dict]) -> Draft:
        anthropic = self._anthropic
        try:
            response = self.client.beta.messages.create(
                model=self.model,
                max_tokens=16000,
                # The schema prompt is identical across questions in one scope: cache it.
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=turns,
                output_config={
                    "effort": "medium",
                    "format": {"type": "json_schema", "schema": DRAFT_SCHEMA},
                },
                # If a safety classifier declines, re-run on Anthropic's recommended fallback.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.AuthenticationError as e:
            raise ModelError(
                "No Anthropic credentials: set ANTHROPIC_API_KEY or run `ant auth login`."
            ) from e
        except anthropic.RateLimitError as e:
            raise ModelError("Anthropic rate limit reached; try again shortly.") from e
        except anthropic.APIStatusError as e:
            raise ModelError(f"Anthropic API error {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise ModelError("Could not reach the Anthropic API.") from e
        if response.stop_reason == "refusal":
            raise ModelError("The model declined to answer this question.")
        text = next((b.text for b in response.content if b.type == "text"), "")
        return _parse(text)


@dataclass
class Status:
    model: SqlModel | None
    detail: str  # what is configured, or how to set one up


def _ollama_models(host: str) -> list[str] | None:
    try:
        with urllib.request.urlopen(f"{host.rstrip('/')}/api/tags", timeout=0.5) as resp:
            return [m["name"] for m in json.load(resp).get("models", [])]
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None


def configured() -> Status:
    """Pick the model from MOCK491_LLM. 'auto' never chooses a paid API."""
    provider = config.LLM_PROVIDER.lower()
    if provider == "none":
        return Status(None, "Text-to-SQL is switched off (MOCK491_LLM=none).")
    if provider == "anthropic":
        try:
            model = ClaudeModel()
        except ModelError as e:
            return Status(None, str(e))
        return Status(model, f"Using {model.name}.")
    if provider not in ("auto", "ollama"):
        return Status(
            None,
            f"Unknown MOCK491_LLM={config.LLM_PROVIDER!r}: use auto, ollama, anthropic or none.",
        )

    available = _ollama_models(config.OLLAMA_HOST)
    if available is None:
        return Status(None, f"No Ollama server at {config.OLLAMA_HOST}.")
    wanted = config.OLLAMA_MODEL
    if not any(m == wanted or m == f"{wanted}:latest" for m in available):
        return Status(
            None, f"Ollama is running but `{wanted}` is not pulled: `ollama pull {wanted}`."
        )
    model = OllamaModel()
    return Status(model, f"Using {model.name}.")
