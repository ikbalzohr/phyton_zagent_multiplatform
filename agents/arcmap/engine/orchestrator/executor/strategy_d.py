from __future__ import annotations

import copy
import os
import re
from pathlib import Path
from typing import Any

from ..cartography.discovery import discover_project_datasets, merge_explicit_and_discovered
from ..cartography.service import CartographicCapabilityEngine
from ..cartography.visual_inspector import RenderedImageInspector
from ..cartography.vision_feedback import merge_visual_feedback


def _safe_name(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r'[<>:"/\\|?*]+', "_", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text or "PETA"


def _sha256(path: str | Path) -> str | None:
    import hashlib

    p = Path(path)
    if not p.is_file():
        return None
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _unwrap(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    for key in ("data", "state", "result", "dataframe"):
        value = result.get(key)
        if isinstance(value, dict):
            merged = dict(result)
            merged.update(value)
            return merged
    return dict(result)


class StrategyDExecutor:
    STRATEGY = "D_CURRENT_MXD_IN_PLACE_CARTOGRAPHY"

    def __init__(self, journal, live_adapter, publisher, workspaces):
        self.journal = journal
        self.live = live_adapter
        self.publisher = publisher
        self.workspaces = workspaces
        self.cartography = CartographicCapabilityEngine()
        self.visual_inspector = RenderedImageInspector()

    @staticmethod
    def _output_name(goal: dict[str, Any]) -> str:
        outputs = goal.get("outputs") or {}
        if outputs.get("base_name"):
            return _safe_name(outputs["base_name"])
        if goal.get("output_name"):
            return _safe_name(goal["output_name"])
        company = str(goal.get("company_name") or goal.get("project_name") or "").strip()
        map_type = str(goal.get("map_type") or "ADMINISTRASI").strip()
        if company:
            return _safe_name("PETA A4 %s - %s" % (company, map_type))
        return _safe_name(goal.get("title") or "PETA ADMINISTRASI")

    @staticmethod
    def _project_root(goal: dict[str, Any], document_path: str) -> Path:
        explicit = str(goal.get("project_root") or "").strip()
        if explicit:
            return Path(explicit).resolve()
        data_root = str(goal.get("data_root") or "").strip()
        if data_root:
            candidate = Path(data_root).resolve()
            document_parent = Path(document_path).resolve().parent
            try:
                if document_parent == candidate or candidate in document_parent.parents:
                    return candidate
            except Exception:
                pass
        return Path(document_path).resolve().parent

    @staticmethod
    def _document_is_in_root(document_path: str, project_root: Path) -> bool:
        try:
            return Path(document_path).resolve().parent == project_root.resolve()
        except Exception:
            return False

    @staticmethod
    def _preview_path(result: dict[str, Any]) -> str:
        if not isinstance(result, dict):
            return ""
        for key in ("artifactPath", "artifact_path", "path"):
            value = result.get(key)
            if value:
                return str(value)
        artifact = result.get("artifact")
        if isinstance(artifact, dict):
            for key in ("artifactPath", "artifact_path", "path"):
                if artifact.get(key):
                    return str(artifact[key])
        return ""

    @staticmethod
    def _checkpoint_path(result: dict[str, Any]) -> str:
        if not isinstance(result, dict):
            return ""
        for key in ("checkpoint", "checkpoint_mxd", "path"):
            value = result.get(key)
            if value:
                return str(value)
        nested = result.get("result")
        if isinstance(nested, dict):
            for key in ("checkpoint", "checkpoint_mxd", "path"):
                if nested.get(key):
                    return str(nested[key])
        return ""

    def _mark(self, run_id, owner_session_id, step_id, task_id, result):
        self.journal.mark_step_state(
            run_id,
            step_id,
            owner_session_id=owner_session_id,
            state="SUCCEEDED",
            task_id=task_id,
            result=result,
        )

    def _restore_before_save(
        self,
        run_id: str,
        owner_session_id: str,
        *,
        live_snapshot: dict[str, Any] | None,
        checkpoint_mxd: str,
        expected: dict[str, Any],
        fencing_epoch: int,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {"live": None, "persistent": None, "ok": True}
        if live_snapshot:
            try:
                live_result = self.live.restore_snapshot(
                    live_snapshot,
                    expected_context=expected,
                    fencing_epoch=fencing_epoch,
                )
                result["live"] = live_result
                result["ok"] = bool(live_result.get("ok"))
                self.journal.add_validation(
                    run_id,
                    "strategy_d_live_restore",
                    "PASS" if live_result.get("ok") else "FAIL",
                    live_result,
                )
            except Exception as exc:
                result["live"] = {"ok": False, "error": str(exc)}
                result["ok"] = False
        if checkpoint_mxd:
            persistent = {
                "ok": True,
                "checkpoint_mxd": checkpoint_mxd,
                "mode": "recovery_source_only",
                "requires_close_or_reopen_before_file_restore": True,
            }
            result["persistent"] = persistent
            self.journal.add_validation(
                run_id,
                "strategy_d_persistent_recovery_available",
                "PASS",
                persistent,
            )
            limitations = list((live_snapshot or {}).get("limitations") or [])
            if limitations:
                # A live-state rollback cannot remove newly created layers,
                # data sources, symbology, or layout objects. When those
                # limitations are present, recovery is only complete after the
                # persistent MXD is reopened/restored.
                result["recovery_required"] = True
                result["rollback_limitations"] = limitations
                result["ok"] = False
        return result

    def execute(
        self,
        *,
        run_id: str,
        owner_session_id: str,
        plan: dict[str, Any],
        task_id: str,
        fencing_epoch: int,
    ) -> dict[str, Any]:
        if str(plan.get("strategy") or "") != self.STRATEGY:
            return {"ok": False, "status": "BLOCKED", "errors": [{"code": "STRATEGY_MISMATCH"}]}

        goal = copy.deepcopy(plan.get("goal") or {})
        expected = copy.deepcopy(plan.get("target_context") or {})
        document_path = str(expected.get("document_path") or "").strip()
        if not document_path:
            return {"ok": False, "status": "BLOCKED", "errors": [{"code": "CURRENT_MXD_PATH_REQUIRED"}]}

        project_root = self._project_root(goal, document_path)
        persistence = goal.get("persistence") or {}
        if persistence.get("require_document_in_project_root", True):
            if not self._document_is_in_root(document_path, project_root):
                return {
                    "ok": False,
                    "status": "BLOCKED",
                    "errors": [{
                        "code": "CURRENT_MXD_NOT_IN_PROJECT_ROOT",
                        "document_path": document_path,
                        "project_root": str(project_root),
                    }],
                }

        outputs = copy.deepcopy(goal.get("outputs") or {})
        output_dir = str(outputs.get("output_dir") or "").strip()
        if not output_dir:
            output_dir = str(project_root / str(outputs.get("output_subdir") or "Hasil Peta"))
        outputs["output_dir"] = output_dir
        outputs.setdefault("formats", ["PDF", "PNG"])
        outputs.setdefault("dpi", 400)
        outputs.setdefault("overwrite_policy", "deny")
        outputs["save_mxd"] = True
        goal["outputs"] = outputs
        goal["project_root"] = str(project_root)
        goal["target_mode"] = "CURRENT_IN_PLACE"

        row = self.journal.get_run(run_id, owner_session_id)
        if row["state"] == "QUEUED":
            self.journal.transition(run_id, "RUNNING", owner_session_id=owner_session_id)

        self._mark(
            run_id, owner_session_id, "s001", task_id,
            {"goal_validated": True, "strategy": self.STRATEGY},
        )

        live_context = self.live.cartographic_context(expected_context=expected)
        if not live_context.get("ok"):
            return {
                "ok": False,
                "status": "BLOCKED",
                "errors": [{"code": live_context.get("code") or "CONTEXT_INCOMPLETE", "details": live_context}],
            }
        identity = live_context.get("identity") or {}
        for step_id, key in (
            ("s010", "identity"),
            ("s020", "identity"),
            ("s030", "map"),
            ("s040", "layers"),
            ("s050", "layout"),
            ("s055", "dataframe"),
        ):
            self._mark(
                run_id,
                owner_session_id,
                step_id,
                task_id,
                live_context.get(key) or {},
            )

        data_root = str(goal.get("data_root") or project_root)
        discovery = discover_project_datasets(
            data_root,
            skip_dirs=goal.get("discovery_skip_dirs"),
            max_items=int(goal.get("max_discovery_items") or 5000),
        )
        datasets = merge_explicit_and_discovered(goal.get("datasets") or [], discovery)
        compile_context = {
            "map": _unwrap(live_context.get("map")),
            "layers": _unwrap(live_context.get("layers")),
            "layout": _unwrap(live_context.get("layout")),
            "dataframe": _unwrap(live_context.get("dataframe")),
            "document_revision": expected,
        }
        compiled = self.cartography.compile(
            goal,
            context=compile_context,
            datasets=datasets,
            reference_analysis=goal.get("reference_analysis") or {},
        )
        if not compiled.get("ok"):
            return {
                "ok": False,
                "status": "BLOCKED",
                "errors": [{"code": "CARTOGRAPHIC_SPEC_COMPILE_FAILED", "details": compiled}],
            }
        specification = compiled.get("specification") or {}
        program = compiled.get("program") or {}
        self._mark(
            run_id,
            owner_session_id,
            "s060",
            task_id,
            {
                "specification": specification,
                "semantic_layer_count": compiled.get("semantic_layer_count"),
                "symbology_count": compiled.get("symbology_count"),
                "label_plan_count": compiled.get("label_plan_count"),
                "inset_count": compiled.get("inset_count"),
                "discovery": {
                    "root": discovery.get("root"),
                    "count": discovery.get("count"),
                    "warnings": discovery.get("warnings"),
                },
            },
        )

        recovery_root = project_root / ".zagent" / "recovery" / run_id
        recovery_root.mkdir(parents=True, exist_ok=True)

        live_snapshot = self.live.snapshot(
            expected_context=expected,
            fencing_epoch=fencing_epoch,
        )
        if not live_snapshot.get("ok"):
            return {
                "ok": False,
                "status": "BLOCKED",
                "errors": [{"code": "CHECKPOINT_FAILED", "details": live_snapshot}],
            }

        persistent = self.live.persistent_checkpoint(
            snapshot_root=str(recovery_root),
            label="before_cartographic_compose",
            expected_context=expected,
        )
        checkpoint_mxd = self._checkpoint_path(persistent)
        if not persistent.get("ok") or not checkpoint_mxd:
            return {
                "ok": False,
                "status": "BLOCKED",
                "errors": [{"code": "PERSISTENT_MXD_CHECKPOINT_FAILED", "details": persistent}],
            }
        checkpoint_id = self.journal.add_checkpoint(
            run_id,
            owner_session_id,
            coverage={
                "strategy": self.STRATEGY,
                "document_path": document_path,
                "persistent_mxd": checkpoint_mxd,
                "live_snapshot": live_snapshot,
                "coverage": "full_current_mxd_plus_live_state",
            },
            fingerprint=_sha256(checkpoint_mxd),
            document_revision=expected,
        )
        self._mark(
            run_id,
            owner_session_id,
            "s070",
            task_id,
            {
                "checkpoint_id": checkpoint_id,
                "persistent_checkpoint": persistent,
                "checkpoint_mxd": checkpoint_mxd,
            },
        )

        compose = self.live.apply_cartographic_program(
            program,
            expected_context=expected,
            fencing_epoch=fencing_epoch,
        )
        if not compose.get("ok"):
            restore = self._restore_before_save(
                run_id,
                owner_session_id,
                live_snapshot=live_snapshot,
                checkpoint_mxd=checkpoint_mxd,
                expected=expected,
                fencing_epoch=fencing_epoch,
            )
            return {
                "ok": False,
                "status": "FAILED" if restore.get("ok") else "RECOVERY_REQUIRED",
                "errors": [{"code": "CARTOGRAPHIC_COMPOSE_FAILED", "details": compose}],
                "restore": restore,
            }
        self._mark(run_id, owner_session_id, "s100", task_id, compose)

        preview = self.live.visual_snapshot(
            name="cartographic-preview-%s" % run_id,
            resolution=int(goal.get("visual_preview_dpi") or 200),
            label="Strategy D cartographic preview",
            expected_context=expected,
        )

        self.journal.transition(run_id, "VALIDATING", owner_session_id=owner_session_id)
        metrics = compose.get("metrics") or ((compose.get("cartographic_result") or {}).get("metrics") or {})
        local_inspection = self.visual_inspector.inspect(
            self._preview_path(preview),
            specification,
            reference_image=goal.get("reference_image"),
        )
        combined_feedback = merge_visual_feedback(
            (local_inspection or {}).get("feedback") or {},
            goal.get("visual_feedback") or {},
        )
        visual = self.cartography.evaluate_visual(
            metrics,
            specification,
            vision_feedback=combined_feedback,
        )
        visual["preview"] = preview
        visual["local_inspection"] = local_inspection
        self.journal.add_validation(
            run_id,
            "cartographic_visual_qa_cycle_0",
            "PASS" if visual.get("ok") else "FAIL",
            visual,
        )
        self._mark(run_id, owner_session_id, "s150", task_id, visual)

        repair_receipts = []
        max_cycles = max(0, min(
            int((program.get("repair_policy") or {}).get("max_cycles") or goal.get("max_repair_cycles") or 3),
            3,
        ))
        cycle = 0
        while not visual.get("ok") and cycle < max_cycles:
            cycle += 1
            self.journal.transition(run_id, "REPAIRING", owner_session_id=owner_session_id)
            proposal = self.cartography.propose_repair(visual, specification, cycle)
            if not proposal.get("ok") or not proposal.get("operations"):
                break
            repair_program = copy.deepcopy(program)
            repair_program["mode"] = "repair_only"
            repair_program["repair_operations"] = proposal.get("operations") or []
            repair_program["repair_context"] = metrics
            receipt = self.live.apply_cartographic_program(
                repair_program,
                expected_context=expected,
                fencing_epoch=fencing_epoch,
            )
            repair_receipts.append({
                "cycle": cycle,
                "proposal": proposal,
                "receipt": receipt,
            })
            if not receipt.get("ok"):
                break
            metrics = receipt.get("metrics") or ((receipt.get("cartographic_result") or {}).get("metrics") or metrics)
            preview = self.live.visual_snapshot(
                name="cartographic-repair-%s-%s" % (run_id, cycle),
                resolution=int(goal.get("visual_preview_dpi") or 200),
                label="Strategy D visual repair cycle %s" % cycle,
                expected_context=expected,
            )
            self.journal.transition(run_id, "VALIDATING", owner_session_id=owner_session_id)
            local_inspection = self.visual_inspector.inspect(
                self._preview_path(preview),
                specification,
                reference_image=goal.get("reference_image"),
            )
            combined_feedback = merge_visual_feedback(
                (local_inspection or {}).get("feedback") or {},
                (goal.get("visual_feedback_by_cycle") or {}).get(str(cycle), {}),
            )
            visual = self.cartography.evaluate_visual(
                metrics,
                specification,
                vision_feedback=combined_feedback,
            )
            visual["preview"] = preview
            visual["local_inspection"] = local_inspection
            self.journal.add_validation(
                run_id,
                "cartographic_visual_qa_cycle_%s" % cycle,
                "PASS" if visual.get("ok") else "FAIL",
                visual,
            )

        self._mark(
            run_id,
            owner_session_id,
            "s160",
            task_id,
            {
                "cycles_used": cycle,
                "max_cycles": max_cycles,
                "receipts": repair_receipts,
                "final_visual_qa": visual,
            },
        )

        if not visual.get("ok"):
            restore = self._restore_before_save(
                run_id,
                owner_session_id,
                live_snapshot=live_snapshot,
                checkpoint_mxd=checkpoint_mxd,
                expected=expected,
                fencing_epoch=fencing_epoch,
            )
            return {
                "ok": False,
                "status": "FAILED" if restore.get("ok") else "RECOVERY_REQUIRED",
                "errors": [{"code": "CARTOGRAPHIC_VISUAL_VALIDATION_FAILED", "details": visual}],
                "restore": restore,
            }

        workspace = self.workspaces.create(run_id)
        staging_dir = workspace.get("staging_artifacts") or workspace.get("staging")
        if not staging_dir:
            return {
                "ok": False,
                "status": "FAILED",
                "errors": [{"code": "STAGING_WORKSPACE_UNAVAILABLE", "workspace": workspace}],
            }
        base_name = self._output_name(goal)

        self.journal.transition(run_id, "STAGING", owner_session_id=owner_session_id)
        staged = self.live.export_staging(
            staging_dir=staging_dir,
            base_name=base_name,
            formats=[str(x).upper() for x in outputs.get("formats") or ["PDF", "PNG"]],
            dpi=int(outputs.get("dpi") or 400),
            expected_context=expected,
            fencing_epoch=fencing_epoch,
        )
        if not staged.get("ok"):
            restore = self._restore_before_save(
                run_id,
                owner_session_id,
                live_snapshot=live_snapshot,
                checkpoint_mxd=checkpoint_mxd,
                expected=expected,
                fencing_epoch=fencing_epoch,
            )
            return {
                "ok": False,
                "status": "FAILED" if restore.get("ok") else "RECOVERY_REQUIRED",
                "errors": [{"code": "STAGING_RENDER_FAILED", "details": staged}],
                "restore": restore,
                "checkpoint_mxd": checkpoint_mxd,
            }

        gate = self.publisher.validate(staged.get("artifacts") or [])
        self.journal.add_validation(
            run_id,
            "artifact_gate",
            "PASS" if gate.get("ok") else "FAIL",
            gate,
        )
        for item in gate.get("artifacts") or []:
            validation = item.get("validation") or {}
            self.journal.add_artifact(
                run_id,
                str(item.get("kind") or ""),
                "STAGING",
                item.get("path"),
                validation.get("sha256"),
                bool(validation.get("ok")),
                {
                    **(item.get("metadata") or {}),
                    "validation": validation,
                },
            )
        if not gate.get("ok"):
            restore = self._restore_before_save(
                run_id,
                owner_session_id,
                live_snapshot=live_snapshot,
                checkpoint_mxd=checkpoint_mxd,
                expected=expected,
                fencing_epoch=fencing_epoch,
            )
            return {
                "ok": False,
                "status": "FAILED" if restore.get("ok") else "RECOVERY_REQUIRED",
                "errors": [{"code": "ARTIFACT_INVALID", "details": gate}],
                "restore": restore,
                "checkpoint_mxd": checkpoint_mxd,
            }
        staged_paths = [
            str(item.get("path") or "")
            for item in (gate.get("artifacts") or [])
            if item.get("path")
        ]
        technical_pre_save = {
            "ok": bool(gate.get("ok")) and not bool(metrics.get("broken_data_sources")),
            "artifact_gate": gate,
            "broken_data_sources": metrics.get("broken_data_sources") or [],
            "same_mxd_path": True,
            "phase": "pre_save",
        }
        acceptance = self.cartography.final_acceptance(
            technical_pre_save,
            visual,
            staged_paths,
            specification,
        )
        self.journal.add_validation(
            run_id,
            "cartographic_acceptance_pre_save",
            "PASS" if acceptance.get("ok") else "FAIL",
            acceptance,
        )
        if not acceptance.get("ok"):
            restore = self._restore_before_save(
                run_id,
                owner_session_id,
                live_snapshot=live_snapshot,
                checkpoint_mxd=checkpoint_mxd,
                expected=expected,
                fencing_epoch=fencing_epoch,
            )
            return {
                "ok": False,
                "status": "FAILED" if restore.get("ok") else "RECOVERY_REQUIRED",
                "errors": [{"code": "CARTOGRAPHIC_ACCEPTANCE_FAILED", "details": acceptance}],
                "restore": restore,
                "checkpoint_mxd": checkpoint_mxd,
            }
        self._mark(
            run_id,
            owner_session_id,
            "s200",
            task_id,
            {
                "artifact_gate": gate,
                "cartographic_acceptance": acceptance,
            },
        )

        save = self.live.save_current(
            expected_context=expected,
            fencing_epoch=fencing_epoch,
        )
        if not save.get("ok") or not save.get("same_document_path", True):
            restore = self._restore_before_save(
                run_id,
                owner_session_id,
                live_snapshot=live_snapshot,
                checkpoint_mxd=checkpoint_mxd,
                expected=expected,
                fencing_epoch=fencing_epoch,
            )
            return {
                "ok": False,
                "status": "RECOVERY_REQUIRED" if not restore.get("ok") else "FAILED",
                "errors": [{"code": "CURRENT_MXD_SAVE_FAILED", "details": save}],
                "restore": restore,
            }
        self._mark(run_id, owner_session_id, "s250", task_id, save)
        self.journal.add_artifact(
            run_id,
            "MXD_SOURCE",
            "FINAL",
            document_path,
            _sha256(document_path),
            True,
            {
                "persistence": "in_place",
                "same_document_path": True,
                "project_root": str(project_root),
            },
        )

        self.journal.transition(run_id, "PUBLISHING", owner_session_id=owner_session_id)
        published = self.publisher.publish(
            run_id,
            staged.get("artifacts") or [],
            output_dir,
            str(outputs.get("overwrite_policy") or "deny"),
        )
        if not published.get("ok"):
            return {
                "ok": False,
                "status": "FAILED",
                "errors": [{
                    "code": published.get("status") or "PUBLISH_PARTIAL",
                    "details": published,
                }],
            }

        final_paths = list(published.get("published") or [])
        for path in final_paths:
            kind = Path(path).suffix.lstrip(".").upper()
            self.journal.add_artifact(
                run_id,
                kind,
                "FINAL",
                path,
                _sha256(path),
                True,
                {
                    "dpi": int(outputs.get("dpi") or 400),
                    "cartographic_profile": specification.get("profile_name"),
                },
            )
        self._mark(run_id, owner_session_id, "s300", task_id, published)

        published_acceptance = self.cartography.final_acceptance(
            {
                "ok": bool(save.get("ok")) and bool(save.get("same_document_path", True)),
                "artifact_gate": gate,
                "broken_data_sources": metrics.get("broken_data_sources") or [],
                "same_mxd_path": bool(save.get("same_document_path", True)),
                "phase": "post_publish",
            },
            visual,
            final_paths,
            specification,
        )
        self.journal.add_validation(
            run_id,
            "cartographic_acceptance_post_publish",
            "PASS" if published_acceptance.get("ok") else "WARN",
            published_acceptance,
        )

        self.journal.transition(run_id, "SUCCEEDED", owner_session_id=owner_session_id)
        return {
            "ok": True,
            "status": "SUCCEEDED",
            "strategy": self.STRATEGY,
            "run_id": run_id,
            "task_id": task_id or None,
            "project_root": str(project_root),
            "document_path": document_path,
            "checkpoint_id": checkpoint_id,
            "checkpoint_mxd": checkpoint_mxd,
            "specification": specification,
            "cartographic_metrics": metrics,
            "visual_qa": visual,
            "repair_receipts": repair_receipts,
            "save": save,
            "artifact_gate": gate,
            "publish": published,
            "acceptance": acceptance,
            "published_acceptance": published_acceptance,
            "fencing_epoch": fencing_epoch,
        }
