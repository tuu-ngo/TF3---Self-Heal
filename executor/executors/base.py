"""Interface chung cho action executor."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from models import DecideResponse


@dataclass
class ExecutionResult:
    action: str
    target: str
    status: str                      # COMPLETED | FAILED (khớp action_executed.status verify)
    execution_time_seconds: int = 0
    detail: dict[str, Any] | None = None

    def to_action_executed(self) -> dict[str, Any]:
        """Format cho /v1/verify request action_executed."""
        out = {"action": self.action, "target": self.target, "status": self.status}
        if self.execution_time_seconds:
            out["execution_time_seconds"] = self.execution_time_seconds
        return out


class ActionExecutor(ABC):
    @abstractmethod
    def execute(self, decide: DecideResponse) -> ExecutionResult:
        """Thực thi action_plan. Urgent: dry-run rồi K8s API. Deferred: Git commit → ArgoCD."""

    @abstractmethod
    def rollback(self, decide: DecideResponse, snapshot) -> ExecutionResult:
        """Khôi phục về snapshot khi /v1/verify trả next_action=ROLLBACK."""
