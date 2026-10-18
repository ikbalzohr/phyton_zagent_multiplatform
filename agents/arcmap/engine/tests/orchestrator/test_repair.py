import unittest

from orchestrator.repair import RepairRegistry, RepairEngine

class FakeRepairAdapter:
    def __init__(self,apply_ok=True,verify_ok=True,score=10):
        self.apply_ok=apply_ok; self.verify_ok=verify_ok; self.score=score; self.calls=[]
    def apply_repair(self,action,issue,checkpoint=None):
        self.calls.append(("apply",action)); return {"ok":self.apply_ok}
    def verify_repair(self,action,issue):
        self.calls.append(("verify",action)); return {"ok":self.verify_ok,"score":self.score}

def cp(action,issue): return {"ok":True,"checkpoint_id":"cp1"}

class RepairTests(unittest.TestCase):
    def test_forbidden_repair_rejected(self):
        r=RepairEngine().run_cycle({"repair_count":0},{}, "guess_crs", FakeRepairAdapter(), cp)
        self.assertEqual(r["code"],"REPAIR_FORBIDDEN")

    def test_unregistered_repair_rejected(self):
        r=RepairEngine().run_cycle({"repair_count":0},{}, "arbitrary_code", FakeRepairAdapter(), cp)
        self.assertEqual(r["code"],"REPAIR_UNREGISTERED")

    def test_budget_max_three(self):
        r=RepairEngine().run_cycle({"repair_count":3},{}, "move_element_in_bounds", FakeRepairAdapter(), cp)
        self.assertEqual(r["code"],"REPAIR_BUDGET_EXHAUSTED")

    def test_same_issue_action_not_repeated(self):
        e=RepairEngine(); state={"repair_count":0}
        a=e.run_cycle(state,{"rule":"bounds"},"move_element_in_bounds",FakeRepairAdapter(),cp)
        self.assertTrue(a["ok"])
        b=e.run_cycle(a["state"],{"rule":"bounds"},"move_element_in_bounds",FakeRepairAdapter(),cp)
        self.assertEqual(b["code"],"REPAIR_LOOP_DETECTED")

    def test_checkpoint_required_before_apply(self):
        adapter=FakeRepairAdapter()
        r=RepairEngine().run_cycle({"repair_count":0},{}, "move_element_in_bounds",adapter,lambda a,i:{"ok":False})
        self.assertEqual(r["code"],"CHECKPOINT_FAILED"); self.assertEqual(adapter.calls,[])

    def test_worsening_score_stops(self):
        adapter=FakeRepairAdapter(score=5)
        r=RepairEngine().run_cycle({"repair_count":0},{}, "move_element_in_bounds",adapter,cp,score_before=10)
        self.assertEqual(r["code"],"REPAIR_WORSENED")

    def test_success_increments_repair_count(self):
        r=RepairEngine().run_cycle({"repair_count":0},{}, "move_element_in_bounds",FakeRepairAdapter(score=10),cp,score_before=8)
        self.assertTrue(r["ok"]); self.assertEqual(r["state"]["repair_count"],1)

if __name__=="__main__": unittest.main()
