"""Runtime settings, read from environment variables (never from files in the repo)."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass


def _positive(
    env: Mapping[str, str], name: str, cast: Callable[[str], float], default: float
) -> float:
    raw = env.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = cast(raw)
    except ValueError:
        value = 0
    if value <= 0:
        raise ValueError(f"{name} must be a positive number, got {raw!r}")
    return value


@dataclass(frozen=True)
class Settings:
    query_timeout_seconds: float = 10.0
    row_cap: int = 1000
    busy_timeout_ms: int = 5000

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env
        defaults = cls()
        return cls(
            query_timeout_seconds=_positive(
                env, "ASKDB_QUERY_TIMEOUT_SECONDS", float, defaults.query_timeout_seconds
            ),
            row_cap=int(_positive(env, "ASKDB_ROW_CAP", int, defaults.row_cap)),
            busy_timeout_ms=int(
                _positive(env, "ASKDB_BUSY_TIMEOUT_MS", int, defaults.busy_timeout_ms)
            ),
        )
