"""Action executors theo pattern_type: urgent (K8s API) vs deferred (GitOps)."""
from models import DecideResponse

from .base import ActionExecutor
from .deferred import DeferredExecutor
from .urgent import UrgentExecutor


def pick(decide: DecideResponse) -> ActionExecutor:
    """Chọn executor theo pattern_type (đã được safety gate validate routing)."""
    if decide.pattern_type == "urgent":
        return UrgentExecutor()
    return DeferredExecutor()


__all__ = ["ActionExecutor", "UrgentExecutor", "DeferredExecutor", "pick"]
