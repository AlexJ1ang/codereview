"""Optional LLM-based semantic review.

Requires environment variables:
  CODEREVIEW_API_KEY, CODEREVIEW_BASE_URL (optional), CODEREVIEW_MODEL (optional)
All calls go through a single httpx-based LLMClient; no provider abstraction.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

import httpx

DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_BASE_URL = "https://api.openai.com/v1"
_ENV_VARS = {
    "api_key": "CODEREVIEW_API_KEY",
    "base_url": "CODEREVIEW_BASE_URL",
    "model": "CODEREVIEW_MODEL",
}


@dataclass
class LLMConfig:
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None
    client: httpx.Client | None = field(default=None, repr=False)

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    @classmethod
    def from_env(cls) -> "LLMConfig":
        return cls(
            api_key=os.environ.get(_ENV_VARS["api_key"]),
            base_url=os.environ.get(_ENV_VARS["base_url"]) or DEFAULT_BASE_URL,
            model=os.environ.get(_ENV_VARS["model"]) or DEFAULT_MODEL,
        )


@dataclass
class ScopeDriftResult:
    possibly_unrelated: list[str] = field(default_factory=list)
    reasons: dict[str, str] = field(default_factory=dict)
    # Explainability: per-file similarity score and matched keywords.
    similarity: dict[str, float] = field(default_factory=dict)
    matched_keywords: dict[str, list[str]] = field(default_factory=dict)


class LLMClient:
    """Minimal OpenAI-compatible chat completions client."""

    def __init__(self, cfg: LLMConfig) -> None:
        self.cfg = cfg
        self._client = httpx.Client(
            base_url=cfg.base_url,
            headers={
                "Authorization": f"Bearer {cfg.api_key}",
                "Content-Type": "application/json",
            },
            timeout=60.0,
        )

    def chat(
        self,
        system: str,
        user: str,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> str:
        payload = {
            "model": self.cfg.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        resp = self._client.post("/chat/completions", json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    def close(self) -> None:
        self._client.close()


def _parse_json_safely(text: str) -> dict | None:
    """Best-effort parse of an LLM JSON response."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def review_scope(
    cfg: LLMConfig,
    task: str,
    files_info: list[dict],
) -> ScopeDriftResult:
    """Ask the LLM which changed files are possibly unrelated to the task."""
    result = ScopeDriftResult()
    if not cfg.enabled or not files_info:
        return result

    client = LLMClient(cfg)
    try:
        lines = "\n".join(
            f"- {f['file']} (status={f['status']}, "
            f"+{f['added']}/-{f['deleted']})"
            for f in files_info
        )
        system = (
            "You detect 'scope drift': changed files unrelated to the stated task. "
            "For EACH changed file, judge its relevance to the task. "
            "Return ONLY a JSON object with a single key 'files', a list of objects, "
            "one per changed file, each with: "
            "'file' (path), 'similarity' (0.0-1.0 relevance to task), "
            "'keywords' (task keywords that appear relevant to this file, list), "
            "'reason' (one short sentence why related or not). "
            "A file counts as unrelated if similarity < 0.4."
        )
        user = f"Task: {task}\nChanged files:\n{lines}"
        raw = client.chat(system, user, temperature=0.0, max_tokens=1024)
    except Exception:
        return result
    finally:
        client.close()

    data = _parse_json_safely(raw)
    if not data:
        return result
    files = data.get("files", [])
    if not isinstance(files, list):
        return result
    for entry in files:
        if not isinstance(entry, dict):
            continue
        path = entry.get("file")
        if not path:
            continue
        try:
            sim = float(entry.get("similarity", 1.0))
        except (TypeError, ValueError):
            sim = 1.0
        keywords = entry.get("keywords") or []
        reason = entry.get("reason", "")
        result.similarity[path] = sim
        result.matched_keywords[path] = [str(k) for k in keywords]
        if sim < 0.4:
            result.possibly_unrelated.append(path)
            result.reasons[path] = reason or "low relevance to task"
    return result


def simplification_advice(
    cfg: LLMConfig,
    findings_summary: dict,
) -> list[str]:
    """Ask the LLM for concrete simplification suggestions, if any."""
    if not cfg.enabled:
        return []

    client = LLMClient(cfg)
    try:
        system = (
            "You keep code simple. Given review findings, produce a concise "
            "list (2-4 items) of concrete ways to reduce implementation "
            "overhead. Return ONLY a JSON array of strings."
        )
        user = json.dumps(findings_summary, ensure_ascii=False)
        raw = client.chat(system, user, temperature=0.2, max_tokens=512)
    except Exception:
        return []
    finally:
        client.close()

    start = raw.find("[")
    end = raw.rfind("]")
    if start == -1 or end == -1:
        return []
    try:
        items = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(items, list):
        return []
    return [str(x) for x in items if isinstance(x, str)]