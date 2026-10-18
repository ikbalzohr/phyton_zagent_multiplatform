"""Thread-local workflow authority carried through asyncio.to_thread."""
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Callable
from .access import AuthorizationError

_state: ContextVar[Any] = ContextVar("zagent_workflow_authority", default=None)


@contextmanager
def execution_authority(context: dict[str, Any], authorize: Callable[[], Any]):
    token = _state.set((dict(context), authorize))
    try:
        yield
    finally:
        _state.reset(token)


def current_context() -> dict[str, Any]:
    state = _state.get()
    if state is None:
        raise AuthorizationError("WORKFLOW_AUTHORITY_REQUIRED", 403)
    return dict(state[0])


def authorize_step() -> None:
    state = _state.get()
    if state is None:
        raise AuthorizationError("WORKFLOW_AUTHORITY_REQUIRED", 403)
    state[1]()
