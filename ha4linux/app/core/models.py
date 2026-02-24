from dataclasses import dataclass
from typing import Any


@dataclass
class ModuleResult:
    id: str
    kind: str
    enabled: bool
    available: bool
    data: dict[str, Any] | None = None
    reason: str | None = None
