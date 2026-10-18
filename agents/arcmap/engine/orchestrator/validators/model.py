STATUS_RANK={"PASS":0,"WARN":1,"NEEDS_REVIEW":2,"FAIL":3}

def result(rule_id,status,expected=None,actual=None,severity="warning",**extra):
    if status not in STATUS_RANK:
        raise ValueError("INVALID_VALIDATION_STATUS")
    return {"rule_id":rule_id,"status":status,"severity":severity,
            "expected":expected,"actual":actual,**extra}

def aggregate(results):
    items=list(results or [])
    if not items:
        return {"schema_version":"2.0","status":"PASS","results":[]}
    status=max((x["status"] for x in items),key=lambda s:STATUS_RANK[s])
    return {"schema_version":"2.0","status":status,"results":items}

def critical_failures(report):
    return [x for x in report.get("results",[]) if x.get("status")=="FAIL" and x.get("severity")=="critical"]
