from abc import ABC, abstractmethod
from typing import Any


class Actuator(ABC):
    id: str

    def describe(self) -> dict[str, Any]:
        return {}

    @abstractmethod
    def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError
