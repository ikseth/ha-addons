from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class ModuleResult:
    id: str
    kind: str
    enabled: bool
    available: bool
    data: Optional[dict[str, Any]] = None
    reason: Optional[str] = None
