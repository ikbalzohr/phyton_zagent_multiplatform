from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path
from typing import Any

_ARCMAP_ENGINE_ROOT = Path(__file__).resolve().parents[3] / "arcmap" / "engine"
if str(_ARCMAP_ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(_ARCMAP_ENGINE_ROOT))

from .workflow_security import authorize_step


def workflow_execution_unavailable() -> dict[str, Any] | None:
    """Source prerequisite only: presence is NOT an ArcMap readiness claim.

    Do not import an unavailable optional engine, or replace its integrity gate.
    A retained, validated artifacts implementation is required for all strategies.
    """
    source = _ARCMAP_ENGINE_ROOT / "orchestrator" / "artifacts"
    if source.with_suffix(".py").is_file() or (source / "__init__.py").is_file():
        return None
    return {
        "ok": False,
        "status": "BLOCKED",
        "errors": [{
            "code": "WORKFLOW_ARTIFACTS_UNAVAILABLE",
            "module": "orchestrator.artifacts",
            "message": "ArcMap workflow execution is disabled: artifacts validation/publication source is missing.",
        }],
    }


def _sha256(path: str) -> str:
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()


class ConcreteWorkflowExecutor:
    def __init__(self, journal, workspace_root: str | Path):
        if workflow_execution_unavailable():
            raise RuntimeError("WORKFLOW_ARTIFACTS_UNAVAILABLE")
        # Optional execution imports must precede all executor construction.
        # Other import errors remain visible; never broadly suppress them.
        from orchestrator.adapters.file_worker import ArcGISProcessFileWorker
        from orchestrator.artifacts import Publisher
        from orchestrator.executor.strategy_a import StrategyAExecutor
        from orchestrator.executor.strategy_d import StrategyDExecutor
        from orchestrator.staging import RunWorkspace, StrategyBCStager
        from .workflow_live_adapter import ProductionArcMapLiveAdapter

        self.journal=journal
        self.workspace_root=Path(workspace_root).resolve()
        self.worker=ArcGISProcessFileWorker(_ARCMAP_ENGINE_ROOT)
        self.stager=StrategyBCStager(self.worker,self.workspace_root)
        self.workspaces=RunWorkspace(self.workspace_root)
        self.publisher=Publisher(journal=journal)
        self.live=ProductionArcMapLiveAdapter()
        self.strategy_a=StrategyAExecutor(journal,self.live)
        self.strategy_d=StrategyDExecutor(journal,self.live,self.publisher,self.workspaces)

    def _cancelled(self, run_id: str, owner_session_id: str) -> bool:
        authorize_step()
        row=self.journal.get_run(run_id,owner_session_id)
        return bool(row.get("cancel_requested"))

    def _fail(self, run_id, owner, status, errors):
        target=status if status in ("BLOCKED","RECOVERY_REQUIRED","WAITING_FOR_REVIEW") else "FAILED"
        transition_error=None
        try:
            self.journal.transition(
                run_id,target,owner_session_id=owner,blockers=errors)
        except Exception as exc:
            transition_error=str(exc)
        durable_state=target
        try:
            durable_state=str(self.journal.get_run(run_id,owner).get("state") or target)
        except Exception:
            pass
        result={
            "ok":False,
            "status":durable_state,
            "requested_status":target,
            "errors":errors,
        }
        if transition_error:
            result["transition_error"]=transition_error
        return result

    def _acquire_leases(self, keys, run_id, owner_session_id):
        authorize_step()
        leases=[]
        try:
            for key in sorted(set(str(x) for x in keys if x)):
                lease=self.journal.acquire_lease(
                    key,run_id,owner_session_id,ttl_seconds=600)
                leases.append((key,lease))
            return leases
        except Exception:
            for key,_ in reversed(leases):
                try:
                    self.journal.release_lease(
                        key,run_id,owner_session_id)
                except Exception:
                    pass
            raise

    def _release_leases(self, leases, run_id, owner_session_id):
        for key,_ in reversed(leases or []):
            try:
                self.journal.release_lease(
                    key,run_id,owner_session_id)
            except Exception:
                pass

    def execute_a(
        self,
        *,
        run_id: str,
        owner_session_id: str,
        plan: dict[str, Any],
        task_id: str = "",
    ) -> dict[str, Any]:
        if str(plan.get("strategy") or "")!="A_EXISTING_MXD":
            return self._fail(
                run_id,owner_session_id,"BLOCKED",
                [{"code":"STRATEGY_MISMATCH"}])
        goal=plan.get("goal") or {}
        recipe=goal.get("recipe") or {}
        if not isinstance(recipe,dict) or not (recipe.get("operations") or []):
            return self._fail(
                run_id,owner_session_id,"BLOCKED",
                [{"code":"RECIPE_REQUIRED"}])
        outputs=goal.get("outputs") or {}
        output_dir=str(outputs.get("output_dir") or "").strip()
        if not output_dir:
            return self._fail(
                run_id,owner_session_id,"BLOCKED",
                [{"code":"OUTPUT_DIR_REQUIRED"}])

        expected=plan.get("target_context") or {}
        instance_id=str(expected.get("instance_id") or "")
        document_id=str(expected.get("document_id") or "")
        if not instance_id or not document_id:
            return self._fail(
                run_id,owner_session_id,"BLOCKED",
                [{"code":"CONTEXT_INCOMPLETE"}])

        live_resource="arcmap-live:%s:%s"%(instance_id,document_id)
        output_resource="output:"+str(Path(output_dir).resolve()).lower()
        try:
            leases=self._acquire_leases(
                [live_resource,output_resource],
                run_id,owner_session_id)
        except RuntimeError as exc:
            return self._fail(
                run_id,owner_session_id,"BLOCKED",
                [{"code":"LOCK_CONFLICT","message":str(exc)}])

        snapshot=None
        restored=False
        fencing_epoch=max(
            int(x[1].get("fencing_epoch") or 0)
            for x in leases
        )
        try:
            row=self.journal.get_run(run_id,owner_session_id)
            if row["state"]=="QUEUED":
                self.journal.transition(
                    run_id,"RUNNING",owner_session_id=owner_session_id)

            for step_id in (
                "s001","s010","s020","s030",
                "s040","s050","s055","s060",
            ):
                self.journal.mark_step_state(
                    run_id,step_id,
                    owner_session_id=owner_session_id,
                    state="SUCCEEDED",
                    task_id=task_id,
                    result={
                        "target_locked":True,
                        "instance_id":instance_id,
                        "document_id":document_id,
                    })

            result=self.strategy_a.execute(
                run_id,
                owner_session_id,
                plan,
                expected,
                recipe,
                fencing_epoch,
                cancel_requested=lambda:self._cancelled(
                    run_id,owner_session_id),
            )
            snapshot=result.get("snapshot")
            if not result.get("ok"):
                status=str(result.get("status") or "FAILED")
                if status=="RECONCILING":
                    return result
                return self._fail(
                    run_id,owner_session_id,
                    "BLOCKED" if status=="BLOCKED" else "FAILED",
                    result.get("errors") or [{"code":"EXECUTION_FAILED"}])

            self.journal.transition(
                run_id,"VALIDATING",owner_session_id=owner_session_id)
            self.journal.add_validation(
                run_id,"live_postconditions","PASS",
                result.get("verification") or {})

            self.journal.transition(
                run_id,"STAGING",owner_session_id=owner_session_id)
            ws=self.workspaces.create(run_id)
            staged=self.live.export_staging(
                staging_dir=ws["staging"],
                base_name=str(goal.get("title") or "Zagent Strategy A"),
                outputs=outputs,
                expected_context=expected,
            )
            if not staged.get("ok"):
                restore=self.live.restore_snapshot(
                    snapshot or {},
                    expected_context=expected,
                    fencing_epoch=fencing_epoch)
                restored=bool(restore.get("ok"))
                self.journal.add_validation(
                    run_id,"live_restore",
                    "PASS" if restored else "FAIL",
                    restore)
                if not restored:
                    self.journal.transition(
                        run_id,"RECOVERY_REQUIRED",
                        owner_session_id=owner_session_id)
                    return {
                        "ok":False,
                        "status":"RECOVERY_REQUIRED",
                        "errors":[{"code":"RECOVERY_REQUIRED",
                                   "details":restore}],
                    }
                return self._fail(
                    run_id,owner_session_id,"FAILED",
                    [{"code":"STAGING_RENDER_FAILED",
                      "details":staged}])

            gate=self.publisher.validate(
                staged.get("artifacts") or [])
            self.journal.add_validation(
                run_id,"artifact_gate",
                "PASS" if gate.get("ok") else "FAIL",
                gate)
            for item in gate.get("artifacts") or []:
                validation=item.get("validation") or {}
                self.journal.add_artifact(
                    run_id,
                    str(item.get("kind") or ""),
                    "STAGING",
                    item.get("path"),
                    validation.get("sha256"),
                    bool(validation.get("ok")),
                    {
                        **(item.get("metadata") or {}),
                        "validation":validation,
                    })
            if not gate.get("ok"):
                restore=self.live.restore_snapshot(
                    snapshot or {},
                    expected_context=expected,
                    fencing_epoch=fencing_epoch)
                restored=bool(restore.get("ok"))
                self.journal.add_validation(
                    run_id,"live_restore",
                    "PASS" if restored else "FAIL",
                    restore)
                if not restored:
                    self.journal.transition(
                        run_id,"RECOVERY_REQUIRED",
                        owner_session_id=owner_session_id)
                    return {
                        "ok":False,
                        "status":"RECOVERY_REQUIRED",
                        "errors":[{"code":"RECOVERY_REQUIRED"}],
                    }
                return self._fail(
                    run_id,owner_session_id,"FAILED",
                    [{"code":"ARTIFACT_INVALID",
                      "details":gate}])

            self.journal.mark_step_state(
                run_id,"s200",
                owner_session_id=owner_session_id,
                state="SUCCEEDED",
                task_id=task_id,
                result=gate)

            restore=self.live.restore_snapshot(
                snapshot or {},
                expected_context=expected,
                fencing_epoch=fencing_epoch)
            restored=bool(restore.get("ok"))
            self.journal.add_validation(
                run_id,"live_restore",
                "PASS" if restored else "FAIL",
                restore)
            if not restored:
                self.journal.transition(
                    run_id,"RECOVERY_REQUIRED",
                    owner_session_id=owner_session_id)
                return {
                    "ok":False,
                    "status":"RECOVERY_REQUIRED",
                    "errors":[{"code":"RECOVERY_REQUIRED",
                               "details":restore}],
                }

            self.journal.transition(
                run_id,"PUBLISHING",
                owner_session_id=owner_session_id)
            authorize_step()
            published=self.publisher.publish(
                run_id,
                staged.get("artifacts") or [],
                output_dir,
                str(outputs.get("overwrite_policy") or "deny"))
            if not published.get("ok"):
                return self._fail(
                    run_id,owner_session_id,"FAILED",
                    [{"code":published.get("status")
                              or "PUBLISH_PARTIAL",
                      "details":published}])
            for path in published.get("published") or []:
                kind=Path(path).suffix.lstrip(".").upper()
                self.journal.add_artifact(
                    run_id,kind,"FINAL",path,
                    _sha256(path),True,
                    {"dpi":int(outputs.get("dpi") or 400)})
            self.journal.mark_step_state(
                run_id,"s300",
                owner_session_id=owner_session_id,
                state="SUCCEEDED",
                task_id=task_id,
                result=published)
            self.journal.transition(
                run_id,"SUCCEEDED",
                owner_session_id=owner_session_id)
            return {
                "ok":True,
                "status":"SUCCEEDED",
                "run_id":run_id,
                "task_id":task_id or None,
                "strategy":"A_EXISTING_MXD",
                "checkpoint_id":result.get("checkpoint_id"),
                "receipt_id":result.get("receipt_id"),
                "artifact_gate":gate,
                "publish":published,
                "live_restore":restore,
                "fencing_epoch":fencing_epoch,
            }
        except Exception as exc:
            if snapshot and not restored:
                try:
                    restore=self.live.restore_snapshot(
                        snapshot,
                        expected_context=expected,
                        fencing_epoch=fencing_epoch)
                    restored=bool(restore.get("ok"))
                    self.journal.add_validation(
                        run_id,"live_restore_on_exception",
                        "PASS" if restored else "FAIL",
                        restore)
                    if not restored:
                        try:
                            self.journal.transition(
                                run_id,"RECOVERY_REQUIRED",
                                owner_session_id=owner_session_id)
                        except Exception:
                            pass
                except Exception:
                    pass
            raise
        finally:
            self._release_leases(
                leases,run_id,owner_session_id)

    def execute_d(
        self,
        *,
        run_id: str,
        owner_session_id: str,
        plan: dict[str, Any],
        task_id: str = "",
    ) -> dict[str, Any]:
        strategy=str(plan.get("strategy") or "")
        if strategy!="D_CURRENT_MXD_IN_PLACE_CARTOGRAPHY":
            return self._fail(
                run_id,owner_session_id,"BLOCKED",
                [{"code":"STRATEGY_MISMATCH"}])

        goal=plan.get("goal") or {}
        expected=plan.get("target_context") or {}
        document_path=str(expected.get("document_path") or "").strip()
        if not document_path:
            return self._fail(
                run_id,owner_session_id,"BLOCKED",
                [{"code":"CURRENT_MXD_PATH_REQUIRED"}])

        outputs=goal.get("outputs") or {}
        project_root=str(goal.get("project_root") or Path(document_path).resolve().parent)
        output_dir=str(outputs.get("output_dir") or (Path(project_root)/"Hasil Peta"))

        document_resource=(
            "arcmap-document:"+str(
                expected.get("document_id")
                or Path(document_path).resolve()
            ).lower()
        )
        output_resource="output:"+str(Path(output_dir).resolve()).lower()
        try:
            leases=self._acquire_leases(
                [document_resource,output_resource],
                run_id,owner_session_id)
        except RuntimeError as exc:
            return self._fail(
                run_id,owner_session_id,"BLOCKED",
                [{"code":"LOCK_CONFLICT","message":str(exc)}])

        lease_map=dict(leases)
        fencing_epoch=int(
            (lease_map.get(document_resource) or {}).get("fencing_epoch")
            or max(
                [int((x or {}).get("fencing_epoch") or 0) for _,x in leases]
                or [0]
            )
        )
        try:
            result=self.strategy_d.execute(
                run_id=run_id,
                owner_session_id=owner_session_id,
                plan=plan,
                task_id=task_id,
                fencing_epoch=fencing_epoch,
            )
            if result.get("ok"):
                return result
            status=str(result.get("status") or "FAILED")
            errors=result.get("errors") or [{"code":"STRATEGY_D_FAILED","details":result}]
            failed=self._fail(
                run_id,owner_session_id,status,errors)
            failed.update({
                "strategy":strategy,
                "details":result,
                "fencing_epoch":fencing_epoch,
            })
            return failed
        finally:
            self._release_leases(
                leases,run_id,owner_session_id)

    def execute_bc(
        self,
        *,
        run_id: str,
        owner_session_id: str,
        plan: dict[str, Any],
        task_id: str = "",
    ) -> dict[str, Any]:
        authorize_step()
        strategy=str(plan.get("strategy") or "")
        if strategy not in {"B_TEMPLATE_DATA","C_BLANK_DATA"}:
            return self._fail(
                run_id,owner_session_id,"BLOCKED",
                [{"code":"STRATEGY_MISMATCH"}])

        goal=plan.get("goal") or {}
        outputs=goal.get("outputs") or {}
        output_dir=str(outputs.get("output_dir") or "").strip()
        if not output_dir:
            return self._fail(
                run_id,owner_session_id,"BLOCKED",
                [{"code":"OUTPUT_DIR_REQUIRED"}])

        output_resource="output:"+str(Path(output_dir).resolve()).lower()
        try:
            lease=self.journal.acquire_lease(
                output_resource,run_id,owner_session_id,ttl_seconds=600)
        except RuntimeError as exc:
            return self._fail(
                run_id,owner_session_id,"BLOCKED",
                [{"code":"LOCK_CONFLICT","message":str(exc)}])

        try:
            row=self.journal.get_run(run_id,owner_session_id)
            if row["state"]=="QUEUED":
                self.journal.transition(
                    run_id,"RUNNING",owner_session_id=owner_session_id)

            self.journal.mark_step_state(
                run_id,"s001",owner_session_id=owner_session_id,
                state="SUCCEEDED",task_id=task_id,
                result={"goal_validated":True,"strategy":strategy})

            probe=self.worker.probe()
            if not probe.get("ok"):
                self.journal.mark_step_state(
                    run_id,"s010",owner_session_id=owner_session_id,
                    state="FAILED",task_id=task_id,result=probe)
                return self._fail(
                    run_id,owner_session_id,"BLOCKED",
                    [{"code":"CAPABILITY_UNAVAILABLE","details":probe}])
            self.journal.mark_step_state(
                run_id,"s010",owner_session_id=owner_session_id,
                state="SUCCEEDED",task_id=task_id,result=probe)

            if self._cancelled(run_id,owner_session_id):
                return {"ok":False,"status":"CANCEL_REQUESTED",
                        "errors":[{"code":"CANCEL_REQUESTED"}]}

            prepared=self.stager.prepare(run_id,plan,probe=probe)
            if not prepared.get("ok"):
                return self._fail(
                    run_id,owner_session_id,
                    prepared.get("status") or "FAILED",
                    prepared.get("errors") or [{"code":"PREPARE_FAILED"}])
            self.journal.mark_step_state(
                run_id,"s060",owner_session_id=owner_session_id,
                state="SUCCEEDED",task_id=task_id,
                result={
                    "working_mxd":prepared.get("working_mxd"),
                    "workspace":prepared.get("workspace"),
                    "worker":prepared.get("worker_result"),
                    "fencing_epoch":lease.get("fencing_epoch"),
                })

            self.journal.transition(
                run_id,"VALIDATING",owner_session_id=owner_session_id)
            qa=(prepared.get("worker_result") or {}).get("qa") or {}
            qa_status="PASS" if qa.get("ok",False) else "FAIL"
            self.journal.add_validation(
                run_id,"working_copy_qa",qa_status,qa)
            if qa_status!="PASS":
                return self._fail(
                    run_id,owner_session_id,"FAILED",
                    [{"code":"VALIDATION_FAILED","details":qa}])

            if self._cancelled(run_id,owner_session_id):
                return {"ok":False,"status":"CANCEL_REQUESTED",
                        "errors":[{"code":"CANCEL_REQUESTED"}]}

            self.journal.transition(
                run_id,"STAGING",owner_session_id=owner_session_id)
            staged=self.stager.render_staging(prepared,outputs)
            if not staged.get("ok"):
                return self._fail(
                    run_id,owner_session_id,"FAILED",
                    staged.get("errors") or [{"code":"STAGING_RENDER_FAILED"}])

            gate=self.publisher.validate(staged.get("artifacts") or [])
            self.journal.add_validation(
                run_id,
                "artifact_gate",
                "PASS" if gate.get("ok") else "FAIL",
                gate)
            for item in gate.get("artifacts") or []:
                validation=item.get("validation") or {}
                self.journal.add_artifact(
                    run_id,
                    str(item.get("kind") or ""),
                    "STAGING",
                    item.get("path"),
                    validation.get("sha256"),
                    bool(validation.get("ok")),
                    {
                        **(item.get("metadata") or {}),
                        "validation":validation,
                    })
            if not gate.get("ok"):
                return self._fail(
                    run_id,owner_session_id,"FAILED",
                    [{"code":"ARTIFACT_INVALID","details":gate}])
            self.journal.mark_step_state(
                run_id,"s200",owner_session_id=owner_session_id,
                state="SUCCEEDED",task_id=task_id,result=gate)

            if self._cancelled(run_id,owner_session_id):
                return {"ok":False,"status":"CANCEL_REQUESTED",
                        "errors":[{"code":"CANCEL_REQUESTED"}]}

            self.journal.transition(
                run_id,"PUBLISHING",owner_session_id=owner_session_id)
            authorize_step()
            published=self.publisher.publish(
                run_id,
                staged.get("artifacts") or [],
                output_dir,
                str(outputs.get("overwrite_policy") or "deny"))
            if not published.get("ok"):
                return self._fail(
                    run_id,owner_session_id,"FAILED",
                    [{"code":published.get("status") or "PUBLISH_PARTIAL",
                      "details":published}])
            for path in published.get("published") or []:
                kind=Path(path).suffix.lstrip(".").upper()
                self.journal.add_artifact(
                    run_id,kind,"FINAL",path,_sha256(path),True,
                    {"dpi":int(outputs.get("dpi") or 400)})
            self.journal.mark_step_state(
                run_id,"s300",owner_session_id=owner_session_id,
                state="SUCCEEDED",task_id=task_id,result=published)
            self.journal.transition(
                run_id,"SUCCEEDED",owner_session_id=owner_session_id)

            return {
                "ok":True,
                "status":"SUCCEEDED",
                "run_id":run_id,
                "task_id":task_id or None,
                "strategy":strategy,
                "workspace":prepared.get("workspace"),
                "working_mxd":prepared.get("working_mxd"),
                "qa":qa,
                "artifact_gate":gate,
                "publish":published,
                "fencing_epoch":lease.get("fencing_epoch"),
            }
        finally:
            try:
                self.journal.release_lease(
                    output_resource,run_id,owner_session_id)
            except Exception:
                pass
