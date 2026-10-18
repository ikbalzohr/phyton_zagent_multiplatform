import unittest
from pathlib import Path

from orchestrator.release import catalog_from_mcp, load_catalog, compare_catalogs, evaluate_release

class ReleaseReadinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from mcp_server import server
        cls.candidate=catalog_from_mcp(server.mcp)
        root=Path(__file__).resolve().parents[2]
        cls.baseline=load_catalog(root/"orchestrator"/"capabilities"/"o0_baseline_124.json")
        cls.diff=compare_catalogs(cls.baseline,cls.candidate)

    def test_baseline_124_tools_remain_schema_identical(self):
        self.assertEqual(self.diff["baseline_count"],124)
        self.assertEqual(self.diff["common"],124)
        self.assertEqual(self.diff["removed"],[])
        self.assertEqual(self.diff["changed"],[])
        self.assertTrue(self.diff["baseline_preserved"])

    def test_candidate_adds_exactly_eight_goal_tools(self):
        self.assertEqual(self.diff["candidate_count"],132)
        self.assertEqual(self.diff["added"],[
            "arcmap_goal_build_map",
            "arcmap_goal_cancel",
            "arcmap_goal_execute",
            "arcmap_goal_plan",
            "arcmap_goal_report",
            "arcmap_goal_resume",
            "arcmap_goal_status",
            "arcmap_goal_validate",
        ])

    def test_unit_only_policy_blocks_release_promotion(self):
        gates={"G%d"%i:("PASS" if i in (1,2,3,4,5,6,7,8,9,10) else "DEFERRED") for i in range(11)}
        r=evaluate_release(gates,self.diff,files_preserved=True,unit_only_policy=True)
        self.assertFalse(r["ok"]); self.assertEqual(r["status"],"BLOCKED")
        self.assertTrue(any(x["code"]=="LIVE_ACCEPTANCE_DEFERRED" for x in r["blockers"]))

    def test_contract_regression_blocks_even_if_all_gates_pass(self):
        bad=dict(self.diff); bad["baseline_preserved"]=False; bad["changed"]=["arcmap_ping"]
        r=evaluate_release({"G%d"%i:"PASS" for i in range(11)},bad,True,False)
        self.assertFalse(r["ok"])
        self.assertTrue(any(x["code"]=="BASELINE_CONTRACT_REGRESSION" for x in r["blockers"]))

    def test_release_ready_only_when_all_full_gates_and_contracts_pass(self):
        r=evaluate_release({"G%d"%i:"PASS" for i in range(11)},self.diff,True,False)
        self.assertTrue(r["ok"]); self.assertEqual(r["status"],"READY")

if __name__=="__main__": unittest.main()
