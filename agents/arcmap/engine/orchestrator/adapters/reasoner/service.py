ALLOWED_STATUS={"PASS","WARN","FAIL","NEEDS_REVIEW"}

class ReasonerService:
    def __init__(self,provider=None,timeout_seconds=30,budget=None):
        self.provider=provider
        self.timeout_seconds=max(1,float(timeout_seconds))
        self.budget=dict(budget or {})
    def assess(self,payload):
        if self.provider is None:
            return {"ok":False,"status":"WAITING_FOR_REVIEW",
                    "errors":[{"code":"REASONER_UNAVAILABLE"}],"decision":None}
        try:
            decision=self.provider.assess(
                dict(payload or {}),
                timeout_seconds=self.timeout_seconds,
                budget=dict(self.budget),
            )
        except TimeoutError:
            return {"ok":False,"status":"WAITING_FOR_REVIEW",
                    "errors":[{"code":"REASONER_TIMEOUT"}],"decision":None}
        except Exception as exc:
            return {"ok":False,"status":"WAITING_FOR_REVIEW",
                    "errors":[{"code":"REASONER_ERROR","message":str(exc)}],"decision":None}
        if not isinstance(decision,dict) or decision.get("status") not in ALLOWED_STATUS:
            return {"ok":False,"status":"WAITING_FOR_REVIEW",
                    "errors":[{"code":"REASONER_RESULT_INVALID"}],"decision":None}
        confidence=decision.get("confidence")
        if confidence is not None and not (0<=float(confidence)<=1):
            return {"ok":False,"status":"WAITING_FOR_REVIEW",
                    "errors":[{"code":"REASONER_RESULT_INVALID"}],"decision":None}
        return {"ok":True,"status":decision["status"],"decision":decision,
                "provider_version":decision.get("provider_version"),
                "prompt_version":decision.get("prompt_version")}
