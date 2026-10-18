from .model import aggregate, result, critical_failures

class VisualReviewService:
    def __init__(self,provider=None):
        self.provider=provider
    def review(self,artifact,deterministic_report=None):
        deterministic_report=deterministic_report or {"status":"PASS","results":[]}
        if critical_failures(deterministic_report):
            return aggregate(list(deterministic_report.get("results") or []) + [
                result("VISUAL_REVIEW_SKIPPED","FAIL",expected="deterministic critical gates pass",
                       actual="critical deterministic failure",severity="critical")
            ])
        if self.provider is None:
            return aggregate(list(deterministic_report.get("results") or []) + [
                result("VISUAL_PROVIDER","NEEDS_REVIEW",expected="configured reasoner or human review",
                       actual="unavailable",severity="warning")
            ])
        assessment=self.provider.assess(artifact)
        allowed={"PASS","WARN","FAIL","NEEDS_REVIEW"}
        if not isinstance(assessment,dict) or assessment.get("status") not in allowed:
            return aggregate([result("VISUAL_PROVIDER_RESULT","FAIL",expected="structured assessment",
                                     actual=assessment,severity="critical")])
        items=list(deterministic_report.get("results") or [])
        for item in assessment.get("results") or []:
            if item.get("status") not in allowed or not item.get("rule_id"):
                items.append(result("VISUAL_PROVIDER_RESULT","FAIL",expected="valid rule result",actual=item,severity="critical"))
            else:
                items.append(item)
        if not assessment.get("results"):
            items.append(result("VISUAL_SUMMARY",assessment["status"],expected="readable map",actual=assessment.get("summary"),
                                severity="critical" if assessment["status"]=="FAIL" else "warning"))
        return aggregate(items)
