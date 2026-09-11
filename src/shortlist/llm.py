"""Provider-agnostic chat client: ordered fallback, bounded retries, real deadline.

Two deliberate choices:
  * A socket timeout applies per read, not to total elapsed time, so a separate
    wall-clock deadline is enforced or a stalled call can hang far past its timeout.
  * Every call records latency and token usage, because "is it fast enough and
    what does it cost" is part of the evaluation, not an afterthought.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import api_key_for

ENDPOINTS = {
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
    "groq": "https://api.groq.com/openai/v1/chat/completions",
    "nvidia": "https://integrate.api.nvidia.com/v1/chat/completions",
}


class AllProvidersFailed(RuntimeError):
    pass


class RateLimited(RuntimeError):
    """Provider asked us to wait. Carries how long, in seconds."""

    def __init__(self, wait_s: float, message: str) -> None:
        super().__init__(message)
        self.wait_s = wait_s


def _retry_after(resp: "httpx.Response") -> float:
    """Seconds to wait, read from whichever header the provider sent."""
    for h in ("retry-after", "x-ratelimit-reset-tokens", "x-ratelimit-reset-requests"):
        v = resp.headers.get(h)
        if not v:
            continue
        try:
            return float(v)
        except ValueError:
            pass
        # Groq sends durations like "7.66s" or "2m59.56s".
        m = re.fullmatch(r"(?:(\d+)m)?([\d.]+)s", v.strip())
        if m:
            return int(m.group(1) or 0) * 60 + float(m.group(2))
    return 20.0


@dataclass
class Usage:
    provider: str = ""
    model: str = ""
    latency_s: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    attempts: int = 0
    fell_back: bool = False
    errors: list[str] = field(default_factory=list)


class LLMClient:
    def __init__(self, cfg: dict[str, Any], providers: list[dict[str, Any]]) -> None:
        if not providers:
            raise AllProvidersFailed(
                "No provider has an API key. Add one to .env (see .env.example)."
            )
        self.cfg = cfg
        self.providers = providers
        m = cfg["model"]
        self.temperature = m.get("temperature", 0.0)
        self.max_tokens = m.get("max_tokens", 2000)
        self.timeout = m.get("timeout_seconds", 90)
        r = cfg.get("reliability", {})
        self.max_retries = r.get("max_retries", 3)
        self.backoff = r.get("backoff_seconds", 2.0)
        self.deadline = r.get("deadline_seconds", 300)
        self.rate_limit_floor = r.get("rate_limit_floor_seconds", 12.0)

    def complete_json(self, system: str, user: str) -> tuple[dict[str, Any], Usage]:
        """Return parsed JSON. Retries within a provider, then falls back."""
        usage = Usage()
        started = time.time()

        for pi, prov in enumerate(self.providers):
            for attempt in range(1, self.max_retries + 1):
                if time.time() - started > self.deadline:
                    usage.errors.append("deadline exceeded")
                    raise AllProvidersFailed(
                        f"Wall-clock deadline of {self.deadline}s exceeded. "
                        f"Errors so far: {usage.errors}"
                    )
                usage.attempts += 1
                try:
                    t0 = time.time()
                    body = self._call(prov, system, user)
                    usage.latency_s = round(time.time() - t0, 3)
                    usage.provider, usage.model = prov["name"], prov["model"]
                    usage.fell_back = pi > 0
                    u = body.get("usage") or {}
                    usage.prompt_tokens = u.get("prompt_tokens", 0)
                    usage.completion_tokens = u.get("completion_tokens", 0)
                    content = body["choices"][0]["message"]["content"]
                    return _parse_json(content), usage
                except RateLimited as exc:
                    # The reported reset is when the token bucket next refills, not
                    # when it holds enough for a whole request. Honouring it
                    # literally causes a 1s retry that fails again immediately, so
                    # a floor is applied.
                    wait = max(exc.wait_s, self.rate_limit_floor)
                    wait = min(wait, max(0.0, self.deadline - (time.time() - started)))
                    usage.errors.append(f"{prov['name']}#{attempt}: rate limited, waited {wait:.1f}s"[:200])
                    if wait > 0 and attempt < self.max_retries:
                        time.sleep(wait)
                except Exception as exc:  # noqa: BLE001 - recorded, then retried
                    usage.errors.append(f"{prov['name']}#{attempt}: {type(exc).__name__}: {exc}"[:200])
                    if attempt < self.max_retries:
                        time.sleep(self.backoff * attempt)

        raise AllProvidersFailed(
            "Every provider failed after retries. Errors: " + " | ".join(usage.errors)
        )

    def _call(self, prov: dict[str, Any], system: str, user: str) -> dict[str, Any]:
        key = api_key_for(prov["name"])
        if not key:
            raise RuntimeError(f"no key for {prov['name']}")
        payload = {
            "model": prov["model"],
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
        }
        resp = httpx.post(
            ENDPOINTS[prov["name"]],
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=payload,
            timeout=self.timeout,
        )
        if resp.status_code == 429:
            # Rate limits are a wait, not a failure. Providers say how long in a
            # header; guessing with a fixed backoff either wastes time or hammers
            # the endpoint. Screening a batch back to back overruns a
            # tokens-per-minute budget long before it exhausts a quota.
            raise RateLimited(_retry_after(resp), f"HTTP 429: {resp.text[:120]}")
        if resp.status_code != 200:
            # Never echo the key; the header is not included in the message.
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:180]}")
        return resp.json()


def _parse_json(content: str | None) -> dict[str, Any]:
    # A provider can return HTTP 200 with message.content set to null. Calling
    # .strip() on that crashed the run with an AttributeError that told the user
    # nothing. Observed live on 2026-09-11 while screening candidate B4.
    if not content:
        raise ValueError("provider returned an empty message body")
    content = content.strip()
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        start, end = content.find("{"), content.rfind("}")
        if start != -1 and end > start:
            return json.loads(content[start : end + 1])
        raise ValueError(f"model did not return JSON: {content[:200]}") from exc
