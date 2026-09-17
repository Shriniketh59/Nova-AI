"""
Token Budget & Everyday Limitation Service.

Provides:
- Daily token allowance tracking per user
- Sub-millisecond in-memory cached checks
- Asynchronous database persistence to user_daily_token_usage
- Configurable daily limit (default 100,000 tokens/day for everyday use)
"""
import asyncio
import time
from datetime import datetime, timezone
from typing import Dict, Tuple

from ..core import db
from ..core.config import DAILY_TOKEN_LIMIT, DEFAULT_USER_ID
from ..core.logger import logger


class TokenBudgetService:
    def __init__(self):
        # In-memory fast cache: key=(user_id, date_str) -> {"prompt": int, "completion": int, "total": int}
        self._cache: Dict[Tuple[str, str], dict] = {}
        self._lock = asyncio.Lock()

    def _today_str(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def estimate_tokens(self, text: str) -> int:
        """Heuristic token count (~4 characters per token)."""
        if not text:
            return 0
        return max(1, len(text.strip()) // 4)

    async def get_daily_usage(self, user_id: str = DEFAULT_USER_ID, date_str: str | None = None) -> dict:
        """Fetch total token usage for a user on a given UTC date."""
        u_id = user_id or DEFAULT_USER_ID
        date_key = date_str or self._today_str()
        cache_key = (u_id, date_key)

        async with self._lock:
            if cache_key in self._cache:
                entry = self._cache[cache_key]
                total = entry["total"]
                return {
                    "user_id": u_id,
                    "date": date_key,
                    "prompt_tokens": entry["prompt"],
                    "completion_tokens": entry["completion"],
                    "total_tokens": total,
                    "daily_limit": DAILY_TOKEN_LIMIT,
                    "remaining_tokens": max(0, DAILY_TOKEN_LIMIT - total),
                    "is_exceeded": total >= DAILY_TOKEN_LIMIT,
                }

        # Check database
        try:
            res = await db.query(
                "SELECT prompt_tokens, completion_tokens, total_tokens FROM user_daily_token_usage WHERE user_id = $1 AND usage_date = $2",
                [u_id, date_key],
            )
            if res.get("rows"):
                row = res["rows"][0]
                p = int(row.get("prompt_tokens") or 0)
                c = int(row.get("completion_tokens") or 0)
                t = int(row.get("total_tokens") or (p + c))
            else:
                p, c, t = 0, 0, 0
        except Exception as err:
            logger.warn(f"token_budget.db_read_failed: {err}")
            p, c, t = 0, 0, 0

        async with self._lock:
            self._cache[cache_key] = {"prompt": p, "completion": c, "total": t}

        return {
            "user_id": u_id,
            "date": date_key,
            "prompt_tokens": p,
            "completion_tokens": c,
            "total_tokens": t,
            "daily_limit": DAILY_TOKEN_LIMIT,
            "remaining_tokens": max(0, DAILY_TOKEN_LIMIT - t),
            "is_exceeded": t >= DAILY_TOKEN_LIMIT,
        }

    async def check_allowance(self, user_id: str = DEFAULT_USER_ID, estimated_tokens: int = 50) -> Tuple[bool, str]:
        """
        Verifies whether the user has sufficient tokens remaining for today.
        Returns: (allowed: bool, reason_message: str)
        """
        usage = await self.get_daily_usage(user_id)
        if usage["is_exceeded"]:
            msg = (
                f"Daily token limit reached ({usage['daily_limit']:,} tokens/day). "
                f"Your quota will reset at 00:00 UTC."
            )
            return False, msg

        if usage["remaining_tokens"] < estimated_tokens:
            msg = (
                f"Approaching daily limit: only {usage['remaining_tokens']:,} tokens left for today. "
                f"Your quota will reset at 00:00 UTC."
            )
            # Still permit if some tokens remain
            return True, msg

        return True, ""

    async def record_usage(
        self,
        user_id: str = DEFAULT_USER_ID,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ) -> dict:
        """Records token usage and persists asynchronously."""
        u_id = user_id or DEFAULT_USER_ID
        date_key = self._today_str()
        cache_key = (u_id, date_key)
        p = max(0, int(prompt_tokens))
        c = max(0, int(completion_tokens))
        total_delta = p + c

        if total_delta == 0:
            return await self.get_daily_usage(u_id)

        async with self._lock:
            if cache_key not in self._cache:
                self._cache[cache_key] = {"prompt": 0, "completion": 0, "total": 0}
            self._cache[cache_key]["prompt"] += p
            self._cache[cache_key]["completion"] += c
            self._cache[cache_key]["total"] += total_delta
            current_totals = dict(self._cache[cache_key])

        # Async DB persist
        try:
            await db.query(
                "INSERT INTO user_daily_token_usage (user_id, usage_date, prompt_tokens, completion_tokens, total_tokens) "
                "VALUES ($1, $2, $3, $4, $5)",
                [u_id, date_key, p, c, total_delta],
            )
        except Exception as err:
            logger.warn(f"token_budget.db_write_failed: {err}")

        return {
            "user_id": u_id,
            "date": date_key,
            "prompt_tokens": current_totals["prompt"],
            "completion_tokens": current_totals["completion"],
            "total_tokens": current_totals["total"],
            "daily_limit": DAILY_TOKEN_LIMIT,
            "remaining_tokens": max(0, DAILY_TOKEN_LIMIT - current_totals["total"]),
            "is_exceeded": current_totals["total"] >= DAILY_TOKEN_LIMIT,
        }


token_budget_service = TokenBudgetService()
