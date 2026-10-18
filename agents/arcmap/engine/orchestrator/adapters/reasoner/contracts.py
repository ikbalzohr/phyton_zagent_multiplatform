from typing import Protocol, Any

class ReasonerPort(Protocol):
    def assess(self,payload: dict[str,Any],*,timeout_seconds: float,budget: dict[str,Any]) -> dict[str,Any]: ...
