"""Operator policy for normal RunManager-backed lead runs."""

import math
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, ConfigDict, field_validator


class RunConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    execution_timeout_seconds: float | None = 2700
    prestart_wait_seconds: float | None = 300

    @field_validator("execution_timeout_seconds", "prestart_wait_seconds", mode="before")
    @classmethod
    def finite_seconds(cls, value):
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)) or (isinstance(value, float) and not math.isfinite(value)):
            raise ValueError("Run limits must be finite seconds or null")
        if value <= 0:
            return None
        try:
            seconds = float(value)
            datetime.now(UTC) + timedelta(seconds=seconds)
        except OverflowError as exc:
            raise ValueError("Run limit exceeds the UTC timestamp range") from exc
        return seconds
