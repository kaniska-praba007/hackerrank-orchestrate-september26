"""Centralized LLM/VLM client with structured output, SHA-256 disk caching, and usage tracking."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Type, TypeVar
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

ROOT_DIR = Path(__file__).resolve().parents[2]
CACHE_DIR = ROOT_DIR / "cache" / "extraction"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class UsageStats:
    calls: int = 0
    cached_hits: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_latency_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "cached_hits": self.cached_hits,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_latency_seconds": round(self.total_latency_seconds, 3),
        }

    def save(self, path: Path) -> None:
        try:
            path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        except Exception:
            pass


USAGE_TRACKER: dict[str, UsageStats] = {}


def get_usage_tracker(model_name: str) -> UsageStats:
    if model_name not in USAGE_TRACKER:
        stats = UsageStats()
        persist_file = CACHE_DIR / f"cumulative_usage_{model_name}.json"
        if persist_file.exists():
            try:
                d = json.loads(persist_file.read_text(encoding="utf-8"))
                stats.calls = d.get("calls", 0)
                stats.cached_hits = d.get("cached_hits", 0)
                stats.input_tokens = d.get("input_tokens", 0)
                stats.output_tokens = d.get("output_tokens", 0)
                stats.total_latency_seconds = d.get("total_latency_seconds", 0.0)
            except Exception:
                pass
        USAGE_TRACKER[model_name] = stats
    return USAGE_TRACKER[model_name]


def _hash_key(prefix: str, content: bytes) -> str:
    h = hashlib.sha256(content).hexdigest()
    return f"{prefix}_{h}"


def _load_env_file():
    current = Path.cwd()
    for _ in range(5):
        env_file = current / ".env"
        if env_file.exists():
            try:
                for line in env_file.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        if "=" in line:
                            k, v = line.split("=", 1)
                        elif " " in line:
                            k, v = line.split(" ", 1)
                        else:
                            continue
                        k = k.strip()
                        v = v.strip().strip("\"'")
                        if k:
                            os.environ[k] = v
            except Exception:
                pass
        current = current.parent


_load_env_file()


class LLMClient:
    def __init__(self, model_name: str = "gemini-3.6-flash", cache_dir: Path = CACHE_DIR):
        _load_env_file()
        self.model_name = model_name
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        self._client = None

    def _get_client(self):
        if self._client is None and self.api_key:
            from google import genai
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def generate_structured(
        self,
        prompt: str,
        response_schema: Type[T],
        image_bytes: bytes | None = None,
        image_mime: str = "image/png",
    ) -> tuple[T, bool]:
        """Generate structured output adhering to response_schema.
        
        Returns (parsed_instance, is_cache_hit).
        """
        stats = get_usage_tracker(self.model_name)
        # Compute exact deterministic hash
        hash_payload = (prompt + response_schema.model_json_schema().__str__()).encode("utf-8")
        if image_bytes:
            hash_payload += image_bytes
        cache_key = _hash_key(self.model_name, hash_payload)
        cache_file = self.cache_dir / f"{cache_key}.json"

        # Check Cache
        if cache_file.exists():
            stats.cached_hits += 1
            cached_data = json.loads(cache_file.read_text(encoding="utf-8"))
            return response_schema.model_validate(cached_data), True

        # Live API Call with Rate Limiting and Backoff
        client = self._get_client()
        if not client:
            raise RuntimeError(
                "GEMINI_API_KEY / GOOGLE_API_KEY not set in environment and no cached response found."
            )

        max_retries = 5
        base_delay = 13.0 if image_bytes else 0.5

        for attempt in range(max_retries):
            try:
                start_time = time.time()
                stats.calls += 1

                contents = []
                if image_bytes:
                    from google.genai import types
                    contents.append(
                        types.Part.from_bytes(data=image_bytes, mime_type=image_mime)
                    )
                contents.append(prompt)

                from google.genai import types
                response = client.models.generate_content(
                    model=self.model_name,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=response_schema,
                        temperature=0.0,
                    ),
                )

                latency = time.time() - start_time
                stats.total_latency_seconds += latency
                if hasattr(response, "usage_metadata") and response.usage_metadata:
                    stats.input_tokens += getattr(response.usage_metadata, "prompt_token_count", 0) or 0
                    stats.output_tokens += getattr(response.usage_metadata, "candidates_token_count", 0) or 0
                stats.save(self.cache_dir / f"cumulative_usage_{self.model_name}.json")

                raw_json = response.text
                parsed_dict = json.loads(raw_json)
                # Write to cache
                cache_file.write_text(json.dumps(parsed_dict, indent=2), encoding="utf-8")

                # Mandatory pacing between live calls to respect rate limits
                time.sleep(base_delay)
                return response_schema.model_validate(parsed_dict), False

            except Exception as e:
                err_msg = str(e)
                if any(x in err_msg for x in ["429", "RESOURCE_EXHAUSTED", "503", "500", "INTERNAL"]) and attempt < max_retries - 1:
                    wait_time = 15.0 * (attempt + 1)
                    print(f"[LLMClient] Transient API issue ({err_msg[:60]}...). Retrying in {wait_time}s (attempt {attempt+1}/{max_retries})...", file=sys.stderr)
                    time.sleep(wait_time)
                else:
                    raise e
