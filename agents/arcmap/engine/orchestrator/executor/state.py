RUN_PHASE_ORDER = (
    "PLANNED","PREFLIGHT","QUEUED","RUNNING","VALIDATING","STAGING","PUBLISHING","SUCCEEDED"
)
TERMINAL = {"SUCCEEDED","FAILED","CANCELLED","ROLLED_BACK","RECOVERY_REQUIRED"}

def is_terminal(state):
    return state in TERMINAL

def progress_fraction(state):
    if state in TERMINAL:
        return 1.0 if state == "SUCCEEDED" else None
    try:
        return RUN_PHASE_ORDER.index(state) / float(len(RUN_PHASE_ORDER) - 1)
    except ValueError:
        return None
