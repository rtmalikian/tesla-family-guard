"""Transport-independent service: takes OpenAI-shaped request dicts,
returns OpenAI-shaped response dicts. The HTTP server (server.py) is a
thin wrapper; tests drive this class directly.

Flow for a user message:
  1. Rules engine answers report-card questions from the week's stats
     (no AI needed — "how fast did the Model Y go this week?").
  2. If rules don't match and ai_mode is auto|always → LLM backend with
     the week's stats as context. The model explains; it never commands
     a car (this app only watches and alerts, it never drives).
  3. ai_mode=never (or LLM failure) → capability-list answer.
"""
from __future__ import annotations

import itertools
import re
import time

from .embeddings import embed_text
from .guard import report_card_text, week_brief
from .llm import LlmBackend

CAPABILITY_BLURB = (
    "I watch your family's driving and write a weekly report card per car: "
    "top speed, over-limit moments, harsh events, night miles, curfew nights, "
    "and times the car left the allowed area. "
    "Try: \"weekly report for the Model Y\" or \"was anyone speeding this week?\" "
    "Connect an LLM backend (TFG_AI_BASE_URL) and I can explain the week in "
    "free-form words too. I never control a car — I only watch and alert."
)


class FamilyGuardService:
    def __init__(self, settings, stats_provider=None, llm_factory=None):
        self.settings = settings
        self.stats_provider = stats_provider or (lambda: {})
        self.llm_factory = llm_factory
        self._ids = itertools.count(1)

    # -- plumbing ------------------------------------------------------
    def _llm(self):
        if self.llm_factory is not None:
            return self.llm_factory()
        if self.settings.ai_mode == "never":
            return None
        if not self.settings.ai_base_url:
            return None
        return LlmBackend(self.settings.ai_base_url, self.settings.ai_api_key,
                          self.settings.ai_model, self.settings.ai_timeout_seconds)

    def _next_id(self, prefix: str) -> str:
        return f"{prefix}-{int(time.time())}-{next(self._ids)}"

    # -- OpenAI surface ------------------------------------------------
    def models_list(self) -> dict:
        return {"object": "list", "data": [{
            "id": self.settings.model_id,
            "object": "model",
            "created": int(time.time()),
            "owned_by": "tesla-family-guard",
        }]}

    def chat_completions(self, body: dict) -> dict:
        messages = body.get("messages") or []
        user_text = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                user_text = str(m.get("content") or "")
                break
        stats_map = self.stats_provider()
        text = self._rules_answer(user_text, stats_map)
        if text is None:
            text = self._llm_answer(user_text, stats_map)
        return {
            "id": self._next_id("chatcmpl"),
            "object": "chat.completion",
            "created": int(time.time()),
            "model": self.settings.model_id,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    def embeddings(self, body: dict) -> dict:
        raw = body.get("input", "")
        texts = raw if isinstance(raw, list) else [raw]
        data = []
        for i, t in enumerate(texts):
            data.append({
                "object": "embedding",
                "index": i,
                "embedding": embed_text(str(t), self.settings.embedding_dim),
            })
        return {
            "object": "list",
            "data": data,
            "model": self.settings.model_id,
            "usage": {"prompt_tokens": 0, "total_tokens": 0},
        }

    # -- internals -----------------------------------------------------
    def _rules_answer(self, user_text: str, stats_map: dict) -> str | None:
        q = user_text.lower()
        if not stats_map:
            return None
        wants_report = ("report" in q or "report card" in q or "how did" in q
                        or "week" in q or "speeding" in q or "top speed" in q)
        if not wants_report:
            return None
        # Pick a car mentioned by name, else the only car, else all cars.
        chosen = None
        for name in stats_map:
            if name.lower() in q:
                chosen = stats_map[name]
                break
        if chosen is None and len(stats_map) == 1:
            chosen = next(iter(stats_map.values()))
        if chosen is not None:
            return report_card_text(chosen, self.settings)
        return "\n\n".join(report_card_text(st, self.settings)
                           for st in stats_map.values())

    def _llm_answer(self, user_text: str, stats_map: dict) -> str:
        llm = self._llm()
        if llm is None:
            return CAPABILITY_BLURB
        try:
            return llm.chat(week_brief(stats_map, self.settings), user_text)
        except Exception:
            return CAPABILITY_BLURB + " (The AI backend didn't respond just now.)"
