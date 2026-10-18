from dataclasses import dataclass
from typing import Any

MANDATORY_ERROR_CODES = frozenset({
    "ACCESS_DENIED",
    "TARGET_STALE",
    "CONTEXT_INCOMPLETE",
    "CAPABILITY_UNAVAILABLE",
    "LICENSE_UNAVAILABLE",
    "DATA_INVALID",
    "LOCK_CONFLICT",
    "DEADLINE_EXCEEDED",
    "OUTCOME_UNKNOWN",
    "VALIDATION_FAILED",
    "ARTIFACT_INVALID",
    "PUBLISH_PARTIAL",
    "RECOVERY_REQUIRED",
})

# Additional domain codes are allowed, but the mandatory taxonomy above is stable
# and must remain available to callers/Manager across versioned additions.
KNOWN_ERROR_CODES = frozenset(set(MANDATORY_ERROR_CODES) | {
    "BLOCKED",
    "CHECKPOINT_FAILED",
    "DISPOSABLE_TARGET_REQUIRED",
    "DRY_RUN_WRITE_BLOCKED",
    "IDEMPOTENCY_CONFLICT",
    "INVALID_GOAL",
    "INVALID_PLAN",
    "INVALID_STATE_TRANSITION",
    "OUTPUT_COLLISION",
    "PLAN_HASH_MISMATCH",
    "REASONER_TIMEOUT",
    "REASONER_UNAVAILABLE",
    "REPAIR_BUDGET_EXHAUSTED",
    "REPAIR_FORBIDDEN",
    "REPAIR_LOOP_DETECTED",
    "REPAIR_UNREGISTERED",
    "REPAIR_VERIFICATION_FAILED",
    "REPAIR_WORSENED",
    "REVIEW_DECISION_REQUIRED",
    "ROLLBACK_COVERAGE_INSUFFICIENT",
    "RUN_NOT_FOUND",
    "SCHEDULER_SUBMIT_FAILED",
    "SOURCE_INSIDE_WORKSPACE",
    "TEMPLATE_REQUIRED",
    "WORKSPACE_ESCAPE",
})


@dataclass(frozen=True)
class OrchestratorError:
    code: str
    message: str = ""
    details: Any = None
    retryable: bool = False

    def as_dict(self) -> dict[str, Any]:
        data = {
            "code": self.code,
            "message": self.message,
            "retryable": bool(self.retryable),
        }
        if self.details is not None:
            data["details"] = self.details
        return data


def error(code: str, message: str = "", *, details: Any = None,
          retryable: bool = False) -> dict[str, Any]:
    if not isinstance(code, str) or not code:
        raise ValueError("ERROR_CODE_REQUIRED")
    return OrchestratorError(
        code=code,
        message=message,
        details=details,
        retryable=retryable,
    ).as_dict()
