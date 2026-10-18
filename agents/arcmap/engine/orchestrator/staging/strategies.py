from .workspace import RunWorkspace, WorkspacePolicyError

class StrategyBCStager:
    def __init__(self,worker,workspace_root):
        self.worker=worker
        self.workspaces=RunWorkspace(workspace_root)

    def prepare(self,run_id,plan,probe=None):
        strategy=plan.get("strategy")
        if strategy not in ("B_TEMPLATE_DATA","C_BLANK_DATA"):
            return {"ok":False,"status":"BLOCKED","errors":[{"code":"STRATEGY_MISMATCH"}]}
        goal=plan.get("goal") or {}
        data_root=goal.get("data_root")
        if not data_root:
            return {"ok":False,"status":"BLOCKED","errors":[{"code":"DATA_ROOT_REQUIRED"}]}
        ws=self.workspaces.create(run_id)
        try: self.workspaces.assert_source_read_only(data_root,ws)
        except WorkspacePolicyError as exc:
            return {"ok":False,"status":"BLOCKED","errors":[{"code":str(exc)}]}
        probe=probe or self.worker.probe()
        if not probe.get("ok"):
            return {"ok":False,"status":"BLOCKED","errors":[{"code":"CAPABILITY_UNAVAILABLE","details":probe}]}
        if strategy=="B_TEMPLATE_DATA":
            template=goal.get("template_mxd")
            if not template:
                return {"ok":False,"status":"BLOCKED","errors":[{"code":"TEMPLATE_REQUIRED"}]}
            try: self.workspaces.assert_source_read_only(template,ws)
            except WorkspacePolicyError as exc:
                return {"ok":False,"status":"BLOCKED","errors":[{"code":str(exc)}]}
            result=self.worker.prepare_template(template_mxd=template,data_root=data_root,workspace=ws["root"],goal=goal)
        else:
            disposable=bool(goal.get("target_disposable",False))
            if not disposable:
                return {"ok":False,"status":"BLOCKED","errors":[{"code":"DISPOSABLE_TARGET_REQUIRED"}]}
            result=self.worker.prepare_blank(data_root=data_root,workspace=ws["root"],goal=goal,disposable=True)
        if not result.get("ok"):
            return {"ok":False,"status":"FAILED","errors":[{"code":result.get("code") or "PREPARE_FAILED","details":result}]}
        working=result.get("working_mxd")
        if not working or not str(working).startswith(ws["root"]):
            return {"ok":False,"status":"FAILED","errors":[{"code":"WORKSPACE_ESCAPE"}]}
        return {"ok":True,"status":"STAGING_READY","workspace":ws,"working_mxd":working,
                "source_unchanged_required":True,"publish_allowed":False,
                "worker_result":result,
                "base_name":result.get("base_name") or "Zagent Map"}

    def render_staging(self,prepared,outputs):
        if not prepared.get("ok"):
            return {"ok":False,"status":"BLOCKED","errors":[{"code":"PREPARE_REQUIRED"}]}
        ws=prepared["workspace"]
        result=self.worker.render_staging(
            working_mxd=prepared["working_mxd"],
            staging_dir=ws["staging"],
            outputs=outputs,
            base_name=prepared.get("base_name") or "Zagent Map")
        if not result.get("ok"):
            return {"ok":False,"status":"FAILED","errors":[{"code":result.get("code") or "STAGING_RENDER_FAILED","details":result}]}
        return {"ok":True,"status":"STAGED","artifacts":result.get("artifacts") or [],
                "publish_allowed":False,"workspace":ws}
