from __future__ import annotations

import re
import unicodedata
from typing import Literal

from croniter import croniter
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_DURATION = re.compile(r"^(\d+(?:\.\d+)?)([smhd])$")
_NAME = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
_WINDOW = re.compile(r"^(\d{2}):(\d{2})-(\d{2}):(\d{2})$")
_TR = str.maketrans("çğıöşüıâîûÇĞİÖŞÜÂÎÛ", "cgiosuiaiuCGIOSUAIU")
KNOWN_TOOLS = {"send_email", "send_sms", "http_request"}


def parse_duration(value: str) -> int:
    text = value.strip().lower()
    if text.isdigit():
        seconds = int(text)
    else:
        match = _DURATION.match(text)
        if not match:
            raise ValueError(f"süre biçimi geçersiz: {value}")
        amount, unit = match.groups()
        seconds = int(float(amount) * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit])
    if seconds <= 0:
        raise ValueError("süre pozitif olmalı")
    return seconds


def slugify(text: str, fallback: str = "ajan") -> str:
    folded = unicodedata.normalize("NFKD", text.translate(_TR))
    ascii_text = folded.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
    slug = slug[:40].strip("-")
    if not slug or not _NAME.match(slug):
        slug = fallback
    return slug


class Metadata(BaseModel):
    name: str
    version: int = Field(ge=1)
    owner: str = "ekip"

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        if not _NAME.match(value):
            raise ValueError("metadata.name küçük harf, rakam ve tire içermeli (en fazla 63)")
        return value


class ModelSpec(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    class_: str = Field(default="local-default", alias="class")
    fallback: str | None = None


class DataSourceRef(BaseModel):
    ref: str
    allowTables: list[str] = Field(min_length=1)


class RuntimeSpec(BaseModel):
    image: str = "agent-runtime-py312:0.2.0"
    cpu: str = "500m"
    memory: str = "1Gi"
    timeoutSeconds: int = Field(default=900, ge=30, le=86_400)


class SelfScheduling(BaseModel):
    minInterval: str = "1h"
    maxInterval: str = "7d"
    maxRunsPerDay: int = Field(default=4, ge=1, le=48)
    window: str = "07:00-20:00"

    @field_validator("minInterval", "maxInterval")
    @classmethod
    def _duration(cls, value: str) -> str:
        parse_duration(value)
        return value

    @field_validator("window")
    @classmethod
    def _window(cls, value: str) -> str:
        if value in {"always", "*"}:
            return value
        match = _WINDOW.match(value)
        if not match:
            raise ValueError("pencere HH:MM-HH:MM veya always olmalı")
        sh, sm, eh, em = (int(part) for part in match.groups())
        if not (0 <= sh <= 23 and 0 <= eh <= 23 and 0 <= sm <= 59 and 0 <= em <= 59):
            raise ValueError("pencere saati geçersiz")
        if (sh, sm) >= (eh, em):
            raise ValueError("pencere aynı gün içinde olmalı; geceyi aşan pencere MVP'de yok")
        return value


class ScheduleSpec(BaseModel):
    mode: Literal["cron", "self", "hybrid", "manual"] = "manual"
    cron: str | None = None
    timeZone: str = "Europe/Istanbul"
    selfScheduling: SelfScheduling | None = None

    @field_validator("timeZone")
    @classmethod
    def _tz(cls, value: str) -> str:
        from zoneinfo import ZoneInfo

        ZoneInfo(value)
        return value

    @field_validator("cron")
    @classmethod
    def _cron(cls, value: str | None) -> str | None:
        if value and not croniter.is_valid(value):
            raise ValueError(f"cron ifadesi geçersiz: {value}")
        return value


class OutputSpec(BaseModel):
    report: Literal["markdown"] = "markdown"
    artifacts: list[str] = Field(default_factory=lambda: ["json", "md", "svg"])
    notify: list[str] = Field(default_factory=list)


class VerificationSpec(BaseModel):
    crossCheckSql: bool = True
    maxRepairRounds: int = Field(default=2, ge=0, le=5)
    numericTolerance: float = Field(default=1.0, gt=0, le=10_000)


class SpecBody(BaseModel):
    goal: str = Field(min_length=8, max_length=4_000)
    model: ModelSpec = Field(default_factory=ModelSpec)
    datasources: list[DataSourceRef] = Field(min_length=1)
    tools: list[str] = Field(default_factory=list)
    runtime: RuntimeSpec = Field(default_factory=RuntimeSpec)
    schedule: ScheduleSpec = Field(default_factory=ScheduleSpec)
    output: OutputSpec = Field(default_factory=OutputSpec)
    verification: VerificationSpec = Field(default_factory=VerificationSpec)
    dryRunRowLimit: int = Field(default=1_000, ge=1, le=100_000)

    @field_validator("tools")
    @classmethod
    def _tools(cls, value: list[str]) -> list[str]:
        unknown = [item for item in value if item not in KNOWN_TOOLS]
        if unknown:
            raise ValueError(f"bilinmeyen araç: {', '.join(unknown)}")
        return value


class AgentSpec(BaseModel):
    apiVersion: Literal["agents.internal/v1"] = "agents.internal/v1"
    kind: Literal["AgentSpec"] = "AgentSpec"
    metadata: Metadata
    spec: SpecBody

    @model_validator(mode="after")
    def _schedule_rules(self) -> AgentSpec:
        schedule = self.spec.schedule
        if schedule.mode in {"cron", "hybrid"} and not schedule.cron:
            raise ValueError("cron ve hybrid modda cron ifadesi zorunlu")
        if schedule.mode in {"self", "hybrid"} and schedule.selfScheduling is None:
            schedule.selfScheduling = SelfScheduling()
        if schedule.selfScheduling:
            minimum = parse_duration(schedule.selfScheduling.minInterval)
            maximum = parse_duration(schedule.selfScheduling.maxInterval)
            if minimum > maximum:
                raise ValueError("minInterval, maxInterval değerinden büyük olamaz")
        notify = [item for item in self.spec.output.notify if item not in self.spec.tools]
        if notify:
            raise ValueError("output.notify içindeki araçlar tools listesinde de olmalı")
        return self

    def canonical(self) -> dict:
        return self.model_dump(by_alias=True, mode="json")

    def model_class(self) -> str:
        return self.spec.model.class_

    def sensitivity_allows_model(self, sensitivities: list[str]) -> bool:
        restricted = any(item == "restricted" for item in sensitivities)
        if restricted and self.model_class().startswith("cloud"):
            return False
        return True
