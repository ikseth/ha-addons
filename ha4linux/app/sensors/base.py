from abc import ABC, abstractmethod
from typing import Any


class Sensor(ABC):
    id: str

    @abstractmethod
    def collect(self) -> dict[str, Any]:
        raise NotImplementedError
