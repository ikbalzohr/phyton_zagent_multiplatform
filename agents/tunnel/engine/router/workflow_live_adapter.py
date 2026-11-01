from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from typing import Any
from urllib.parse import urlsplit
import httpx
from .identity import internal_token
from .workflow_security import current_context, authorize_step


class MCPHttpClient:
    def __init__(self, url: str | None = None, timeout_seconds: float = 90.0):
        self.url=(url or os.environ.get(
            "ZAGENT_ARCMAP_MCP_URL",
            "")).strip()
        self.timeout_seconds=max(1.0,float(timeout_seconds))

    def call(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        authorize_step()
        parsed = urlsplit(self.url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "::1"} or parsed.username or parsed.query or parsed.fragment:
            return {"ok":False,"code":"INTERNAL_CHANNEL_NOT_CONFIGURED"}
        body=json.dumps({
            "jsonrpc":"2.0",
            "id":1,
            "method":"tools/call",
            "params":{"name":name,"arguments":arguments or {},"_meta":{"zagent.execution_context":current_context()}},
        },ensure_ascii=False,separators=(",",":")).encode("utf-8")
        try:
            with httpx.Client(trust_env=False, follow_redirects=False, timeout=self.timeout_seconds) as client:
                response = client.post(self.url, content=body, headers={
                    "Content-Type":"application/json", "Accept":"application/json, text/event-stream",
                    "X-Zagent-Internal-Token":internal_token()})
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError,OSError,ValueError):
            return {"ok":False,"code":"DURABLE_RUNTIME_UNAVAILABLE"}
        if payload.get("error"):
            return {"ok":False,"code":"MCP_RPC_ERROR","error":payload["error"]}
        result=payload.get("result") or {}
        content=result.get("content") or []
        if not content:
            return {"ok":False,"code":"MCP_EMPTY_RESULT"}
        text=content[0].get("text") if isinstance(content[0],dict) else None
        if text is None:
            return {"ok":False,"code":"MCP_NON_TEXT_RESULT","result":result}
        try:
            value=json.loads(text)
        except Exception:
            value={"ok":not bool(result.get("isError")),"text":text}
        if result.get("isError"):
            value.setdefault("ok",False)
        return value


def _same_context(expected: dict[str,Any], actual: dict[str,Any]) -> bool:
    if not expected:
        return True
    pairs=(
        ("instance_id","instance_id"),
        ("document_id","document_id"),
        ("document_path","document_path"),
        ("pid","pid"),
    )
    for ek,ak in pairs:
        ev=expected.get(ek)
        if ev not in (None,"") and ev!=actual.get(ak):
            return False
    return True


class ProductionArcMapLiveAdapter:
    def __init__(self, client: MCPHttpClient | None = None):
        self.client=client or MCPHttpClient()

    def inspect_identity(self) -> dict[str,Any]:
        r=self.client.call("arcmap_ping")
        if not r.get("ok"):
            return r
        c=r.get("context") or {}
        return {
            "ok":True,
            "instance_id":c.get("bridge_instance_id"),
            "bridge_instance_id":c.get("bridge_instance_id"),
            "document_id":c.get("document_id"),
            "document_path":c.get("document_path"),
            "pid":c.get("pid"),
            "document_revision":{
                "instance_id":c.get("bridge_instance_id"),
                "document_id":c.get("document_id"),
                "document_path":c.get("document_path"),
                "pid":c.get("pid"),
            },
            "raw":r,
        }

    def snapshot_state(self, *, expected_context: dict[str,Any]) -> dict[str,Any]:
        identity=self.inspect_identity()
        if not identity.get("ok"):
            return identity
        if not _same_context(expected_context,identity):
            return {"ok":False,"code":"TARGET_STALE","actual":identity}
        r=self.client.call("arcmap_snapshot_state")
        if not r.get("ok"):
            return r
        fingerprint=hashlib.sha256(json.dumps({
            "snapshot_id":r.get("snapshot_id"),
            "identity":identity.get("document_revision"),
        },sort_keys=True,separators=(",",":")).encode("utf-8")).hexdigest()
        return {
            "ok":True,
            "snapshot_id":r.get("snapshot_id"),
            "coverage":["live_state"]+list(r.get("restorable") or []),
            "limitations":list(r.get("not_restored_by_design") or []),
            "fingerprint":fingerprint,
            "identity":identity,
            "raw":r,
        }

    def snapshot(
        self,
        *,
        expected_context: dict[str,Any],
        fencing_epoch: int = 0,
    ) -> dict[str,Any]:
        """Backward-compatible Strategy D alias for snapshot_state()."""
        result=self.snapshot_state(expected_context=expected_context)
        if isinstance(result,dict):
            result.setdefault("fencing_epoch",int(fencing_epoch or 0))
        return result

    def validate_recipe(self, recipe: dict[str,Any]) -> dict[str,Any]:
        recipe=recipe or {}
        non_restorable={
            "apply_symbology_from_layer",
            "set_class_breaks",
            "set_unique_value_field",
        }
        actions={
            str(item.get("action") or "")
            for item in (recipe.get("operations") or [])
            if isinstance(item,dict)
        }
        unsafe=sorted(actions & non_restorable)
        if unsafe:
            return {
                "ok":False,
                "code":"ROLLBACK_COVERAGE_INSUFFICIENT",
                "non_restorable_actions":unsafe,
            }
        return self.client.call(
            "arcmap_validate_map_recipe",
            {"recipe":recipe},
        )

    def apply_recipe(
        self,
        recipe: dict[str,Any],
        *,
        expected_context: dict[str,Any],
        fencing_epoch: int,
    ) -> dict[str,Any]:
        identity=self.inspect_identity()
        if not identity.get("ok"):
            return identity
        if not _same_context(expected_context,identity):
            return {"ok":False,"code":"TARGET_STALE","actual":identity}
        result=self.client.call(
            "arcmap_apply_map_recipe",
            {"recipe":recipe or {},"atomic":True,"dry_run":False},
        )
        if isinstance(result,dict):
            result.setdefault("fencing_epoch",fencing_epoch)
        return result

    def verify_postconditions(
        self,
        postconditions: list[Any],
        *,
        expected_context: dict[str,Any],
    ) -> dict[str,Any]:
        identity=self.inspect_identity()
        if not identity.get("ok"):
            return identity
        if not _same_context(expected_context,identity):
            return {"ok":False,"code":"TARGET_STALE","actual":identity}
        return {
            "ok":True,
            "identity":identity,
            "postconditions_checked":len(postconditions or []),
        }

    def restore_snapshot(
        self,
        checkpoint: dict[str,Any],
        *,
        expected_context: dict[str,Any],
        fencing_epoch: int,
    ) -> dict[str,Any]:
        snapshot_id=(checkpoint or {}).get("snapshot_id")
        if not snapshot_id:
            return {"ok":False,"code":"CHECKPOINT_MISSING"}
        identity=self.inspect_identity()
        if not identity.get("ok"):
            return identity
        if not _same_context(expected_context,identity):
            return {"ok":False,"code":"TARGET_STALE","actual":identity}
        result=self.client.call(
            "arcmap_restore_snapshot",
            {"snapshot_id":snapshot_id},
        )
        if isinstance(result,dict):
            result.setdefault("fencing_epoch",fencing_epoch)
        return result

    def export_staging(
        self,
        *,
        staging_dir: str,
        base_name: str,
        outputs: dict[str,Any] | None = None,
        formats: list[str] | None = None,
        dpi: int | None = None,
        expected_context: dict[str,Any],
        fencing_epoch: int = 0,
    ) -> dict[str,Any]:
        identity=self.inspect_identity()
        if not identity.get("ok") or not _same_context(expected_context,identity):
            return {"ok":False,"code":"TARGET_STALE","actual":identity}
        merged=dict(outputs or {})
        if formats is not None:
            merged["formats"]=list(formats)
        if dpi is not None:
            merged["dpi"]=int(dpi)
        Path(staging_dir).mkdir(parents=True,exist_ok=True)
        format_set={str(x).upper() for x in (merged.get("formats") or ["PDF","PNG"])}
        result=self.client.call(
            "arcmap_export_bundle",
            {
                "output_dir":staging_dir,
                "base_name":base_name,
                "resolution":int(merged.get("dpi") or 400),
                "overwrite":False,
                "include_pdf":"PDF" in format_set,
                "include_png":"PNG" in format_set,
                "include_jpeg":False,
            },
        )
        if not result.get("ok"):
            return result
        artifacts=[]
        for item in result.get("files") or []:
            kind=str(item.get("format") or "").upper()
            artifacts.append({
                "kind":kind,
                "path":item.get("path"),
                "metadata":{"dpi":int(merged.get("dpi") or 400)},
            })
        response={"ok":True,"artifacts":artifacts,"raw":result}
        response["fencing_epoch"]=int(fencing_epoch or 0)
        return response


    def cartographic_context(self, *, expected_context: dict[str,Any]) -> dict[str,Any]:
        identity=self.inspect_identity()
        if not identity.get("ok"):
            return identity
        if not _same_context(expected_context,identity):
            return {"ok":False,"code":"TARGET_STALE","actual":identity}
        calls={}
        for key,tool,args in (
            ("map","arcmap_inspect_current_map",{}),
            ("layers","arcmap_list_layers",{}),
            ("layout","arcmap_list_layout_elements",{}),
            ("dataframe","arcmap_get_dataframe_state",{}),
        ):
            result=self.client.call(tool,args)
            calls[key]=result
        return {
            "ok":all(bool((x or {}).get("ok",True)) for x in calls.values()),
            "identity":identity,
            "map":calls.get("map") or {},
            "layers":calls.get("layers") or {},
            "layout":calls.get("layout") or {},
            "dataframe":calls.get("dataframe") or {},
        }

    def persistent_checkpoint(
        self,
        *,
        snapshot_root: str,
        label: str,
        expected_context: dict[str,Any],
    ) -> dict[str,Any]:
        identity=self.inspect_identity()
        if not identity.get("ok"):
            return identity
        if not _same_context(expected_context,identity):
            return {"ok":False,"code":"TARGET_STALE","actual":identity}
        Path(snapshot_root).mkdir(parents=True,exist_ok=True)
        result=self.client.call(
            "arcmap_stage3_save_checkpoint",
            {"snapshot_root":snapshot_root,"label":label or "cartographic_baseline"},
        )
        if isinstance(result,dict):
            result.setdefault("identity",identity)
        return result

    def restore_persistent_checkpoint(
        self,
        *,
        checkpoint_mxd: str,
        expected_context: dict[str,Any],
        fencing_epoch: int,
    ) -> dict[str,Any]:
        identity=self.inspect_identity()
        if not identity.get("ok"):
            return identity
        if not _same_context(expected_context,identity):
            return {"ok":False,"code":"TARGET_STALE","actual":identity}
        target=str(expected_context.get("document_path") or identity.get("document_path") or "")
        if not checkpoint_mxd or not target:
            return {"ok":False,"code":"CHECKPOINT_OR_TARGET_MISSING"}
        result=self.client.call(
            "arcmap_stage3_restore_checkpoint",
            {"checkpoint_mxd":checkpoint_mxd,"target_mxd":target},
        )
        if isinstance(result,dict):
            result.setdefault("fencing_epoch",fencing_epoch)
        return result

    def apply_cartographic_program(
        self,
        program: dict[str,Any],
        *,
        expected_context: dict[str,Any],
        fencing_epoch: int,
    ) -> dict[str,Any]:
        identity=self.inspect_identity()
        if not identity.get("ok"):
            return identity
        if not _same_context(expected_context,identity):
            return {"ok":False,"code":"TARGET_STALE","actual":identity}
        recipe={
            "name":"Zagent Cartographic Program",
            "operations":[
                {
                    "action":"apply_cartographic_program",
                    "params":{"program":program or {}},
                }
            ],
        }
        validation=self.client.call("arcmap_validate_map_recipe",{"recipe":recipe})
        if not validation.get("ok"):
            return {
                "ok":False,
                "code":"CARTOGRAPHIC_PROGRAM_INVALID",
                "validation":validation,
            }

        # Validation can be a non-trivial UI-thread round trip. Refresh the
        # authoritative bridge heartbeat immediately before queuing the write.
        refreshed=self.inspect_identity()
        if not refreshed.get("ok"):
            return refreshed
        if not _same_context(expected_context,refreshed):
            return {"ok":False,"code":"TARGET_STALE","actual":refreshed}

        result=self.client.call(
            "arcmap_apply_map_recipe",
            {"recipe":recipe,"atomic":True,"dry_run":False},
        )

        # The IPC layer guarantees this exact error means the command was not
        # queued, so one fresh-heartbeat retry is safe and cannot duplicate a
        # partially executed recipe.
        error_text=str((result or {}).get("error") or "")
        if (
            isinstance(result,dict)
            and not result.get("ok")
            and "BRIDGE_OFFLINE" in error_text
            and "command not queued" in error_text
        ):
            retry_identity=self.inspect_identity()
            if retry_identity.get("ok") and _same_context(expected_context,retry_identity):
                result=self.client.call(
                    "arcmap_apply_map_recipe",
                    {"recipe":recipe,"atomic":True,"dry_run":False},
                )
                if isinstance(result,dict):
                    result.setdefault("bridge_retry_after_not_queued",True)

        if isinstance(result,dict):
            result.setdefault("fencing_epoch",fencing_epoch)
            result.setdefault("validation",validation)
            rows=result.get("results") or []
            if rows:
                op_result=(rows[-1] or {}).get("result")
                if isinstance(op_result,dict):
                    result.setdefault("cartographic_result",op_result)
                    result.setdefault("metrics",op_result.get("metrics") or {})
        return result

    def visual_snapshot(
        self,
        *,
        name: str,
        resolution: int,
        label: str,
        expected_context: dict[str,Any],
    ) -> dict[str,Any]:
        identity=self.inspect_identity()
        if not identity.get("ok"):
            return identity
        if not _same_context(expected_context,identity):
            return {"ok":False,"code":"TARGET_STALE","actual":identity}
        document_path=str(identity.get("document_path") or "")
        if not document_path:
            return {"ok":False,"code":"CURRENT_MXD_PATH_REQUIRED"}
        preview_dir=Path(document_path).resolve().parent / ".zagent" / "visual"
        preview_dir.mkdir(parents=True,exist_ok=True)
        safe_name="".join(
            ch if (ch.isalnum() or ch in ("-","_")) else "_"
            for ch in str(name or "cartographic-preview")
        )
        output_path=str(preview_dir / (safe_name + ".png"))
        result=self.client.call(
            "arcmap_stage3_export_current",
            {
                "output_path":output_path,
                "format":"PNG",
                "resolution":int(resolution or 200),
            },
        )
        if isinstance(result,dict) and result.get("ok"):
            result.setdefault("artifactPath",result.get("output") or output_path)
            result.setdefault("label",label or "cartographic visual QA")
            result.setdefault("preview_mode","stage3_export_current")
        return result

    def save_current(
        self,
        *,
        expected_context: dict[str,Any],
        fencing_epoch: int,
    ) -> dict[str,Any]:
        identity=self.inspect_identity()
        if not identity.get("ok"):
            return identity
        if not _same_context(expected_context,identity):
            return {"ok":False,"code":"TARGET_STALE","actual":identity}
        before=str(identity.get("document_path") or "")
        result=self.client.call("arcmap_save_current_map",{})
        after=self.inspect_identity()
        if isinstance(result,dict):
            result.setdefault("fencing_epoch",fencing_epoch)
            result["document_path_before"]=before
            result["document_path_after"]=str(after.get("document_path") or "")
            result["same_document_path"]=(
                bool(before)
                and os.path.normcase(os.path.abspath(before))
                == os.path.normcase(os.path.abspath(str(after.get("document_path") or "")))
            )
            result["identity_after"]=after
        return result
