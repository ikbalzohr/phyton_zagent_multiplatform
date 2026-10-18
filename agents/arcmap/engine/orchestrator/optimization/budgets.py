class BudgetDecision:
    def __init__(self,ok,code="OK",details=None):
        self.ok=ok; self.code=code; self.details=details or {}
    def as_dict(self): return {"ok":self.ok,"code":self.code,"details":self.details}

class WorkerBudget:
    def __init__(self,max_workers=1,max_memory_mb=1024,allow_nested_parallelism=False):
        self.max_workers=max(1,int(max_workers))
        self.max_memory_mb=max(64,int(max_memory_mb))
        self.allow_nested_parallelism=bool(allow_nested_parallelism)
    def admit(self,job,active_workers=0):
        if active_workers>=self.max_workers:
            return BudgetDecision(False,"WORKER_CAPACITY")
        mem=int(job.get("estimated_memory_mb") or 0)
        if mem>self.max_memory_mb:
            return BudgetDecision(False,"MEMORY_BUDGET",{"estimated":mem,"limit":self.max_memory_mb})
        ppf=int(job.get("parallel_processing_factor") or 1)
        if not self.allow_nested_parallelism and self.max_workers>1 and ppf>1:
            return BudgetDecision(False,"NESTED_PARALLELISM_FORBIDDEN",{"workers":self.max_workers,"ppf":ppf})
        return BudgetDecision(True)
