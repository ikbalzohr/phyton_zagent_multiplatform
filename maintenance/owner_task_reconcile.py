"""Owner-reviewed reconciliation of an interrupted Core lifecycle request.

This script is an offline/owner maintenance control, not an MCP recovery bypass.
It keeps the original task record, checks Core's authenticated lifecycle journal
and legacy no-effect probes, then performs a single ACID journal transition
while the Tunnel is stopped through the owner Core management API.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import http.cookiejar
import json
import os
import shutil
import sqlite3
import ssl
import sys
import time
import urllib.request
import uuid
from pathlib import Path

REPO = Path(r"D:\3-Ikbalzohr\Agent\phyton_zagent_multiplatform")
INSTALL = Path(r"D:\3-Ikbalzohr\Agent\ZohrSystem\Zagent Multi Platform")
CERT = REPO / "_validation/arcmap-deploy-d6579b805c874fbbb9a4147cf048677f/dashboard-public-cert.pem"
EVIDENCE = REPO / "_validation/mp-owner-recovery-20261107"
DB = INSTALL / "data/tunnel/runtime/tasks.db"
ORIGINAL = "tsk_a02e8da4558f4801b05ff072b5035f18"
OBSERVATIONS = frozenset({"tsk_cf5119a1a6af4ac9b937bf9d4a38baf1",
                          "tsk_a5d8892938df44c68151649b7cbf0cbb"})
OPERATION_ID = "2bab324a9e3c486496cfacb9867fea24"
EXPECTED_KEY = "headless-chat-20261107-tunnel-restart-v1"
ACK = REPO / "_validation/arcmap-headless-deploy-20261107-chat/tunnel-restart-ack.json"
VERSION = "owner-scoped-core-lifecycle-reconciliation-v1"
URL = "https://localhost:19444/api/management/v1/"
ACTIVE = {"accepted","queued","running","waiting_capacity","waiting_lock","cancelling","recovering"}


def sha(value):
    if not isinstance(value,(bytes,bytearray)):
        value=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
    return hashlib.sha256(value).hexdigest()


def client():
    return urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=str(CERT))),
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def get(browser,path):
    with browser.open(URL+path,timeout=12) as res:
        if res.status != 200:
            raise RuntimeError("OWNER_MANAGEMENT_RESPONSE_INVALID")
        return json.load(res)


def operation(browser):
    obj=get(browser,"operations/"+OPERATION_ID)
    assert obj["operationId"]==OPERATION_ID
    assert obj["method"]=="lifecycle.agent"
    assert obj["state"]=="succeeded"
    assert obj["idempotencyKey"]==EXPECTED_KEY
    assert len(obj["actorId"])>12
    ack=json.loads(ACK.read_text("utf-8"))
    assert ack["operationId"]==OPERATION_ID and ack["accepted"] is True
    snap=get(browser,"agents")["data"]
    if isinstance(snap,dict):snap=snap["agents"]
    agents={r["agentId"]:r for r in snap}
    assert agents["system.tunnel"]["processState"]=="Running"
    assert agents["system.tunnel"]["osProcessId"]!=ack["pid_before"]
    return obj,ack


def load(conn,ids):
    conn.row_factory=sqlite3.Row
    return [dict(x) for x in conn.execute("SELECT * FROM tasks WHERE task_id IN (?,?,?) ORDER BY task_id",
        tuple(sorted(ids))).fetchall()]


def verify_row(row,op):
    assert row["state"]=="orphaned" and row["started_at"] is not None
    assert row["resource_key"].startswith("installation:")
    c=json.loads(row["execution_context_json"])
    assert c["context_version"]==1
    assert c["task_id"]==row["task_id"]
    assert c["request_id"]==row["request_id"]
    assert c["trace_id"]==row["trace_id"]
    assert c["device_id"]==row["target_device_id"]==row["executed_on"]
    assert c["resource_id"] if "resource_id" in c else True
    assert c["installation_id"] and row["resource_key"]=="installation:"+c["installation_id"]
    assert c["workspace_id"]=="zagent-mp-test"
    assert c["principal_id"] and row["session_id"].startswith("owner_v1_")
    args=json.loads(row["arguments_json"])
    if row["task_id"]==ORIGINAL:
        assert row["service_id"]=="zagent_files" and row["tool_name"]=="files_exec_command"
        assert c["public_tool"]=="files_exec_command" and c["required_scope"]=="files:execute"
        assert c["effective_access"]=="write"
        assert args["args"]==["_validation/arcmap-headless-deploy-20261107-chat.py","restart_router"]
        assert args["profile_id"]=="agent-dev" and args["cwd"]=="."
        assert args["timeout_seconds"]==45
        assert Path(args["executable"]).resolve()==(
            INSTALL/"agents/arcmap/runtime/python/python.exe").resolve()
        moment=dt.datetime.fromisoformat(op["updatedAtUtc"])
        assert moment.timestamp()>=row["started_at"]
        return "CORE_LIFECYCLE_SUCCEEDED_TRANSPORT_RESULT_LOST"
    assert row["task_id"] in OBSERVATIONS
    assert row["service_id"]=="zagent_arcmap"
    assert row["tool_name"] in {"arcmap_ping","arcmap_execution_capabilities"}
    assert c["public_tool"]==row["tool_name"]
    assert c["required_scope"] in {"arcmap:inspect","arcmap:execute"}
    assert c["effective_resources"]==[{"kind":"arcmap","resource_id":row["resource_key"]}]
    assert args=={}
    return "NO_EFFECT_OBSERVATION_TRANSPORT_FAILED"


def inspect(browser):
    op,ack=operation(browser)
    jobs=get(browser,"jobs").get("data",{})
    assert not any(row.get("state") in ACTIVE for row in jobs.get("tasks",[]))
    conn=sqlite3.connect(f"file:{DB.as_posix()}?mode=ro",uri=True)
    try:
        rows=load(conn,{ORIGINAL}|OBSERVATIONS)
    finally:conn.close()
    assert len(rows)==3
    outcomes={r["task_id"]:verify_row(r,op) for r in rows}
    plan={"version":VERSION,"core_operation_id":OPERATION_ID,
        "operation_hash":sha(op),"ack_hash":sha(ack),
        "task_ids":sorted(outcomes),
        "row_hashes":{r["task_id"]:sha(r) for r in rows},
        "reconciliation":outcomes}
    plan["expected_plan"]=sha(plan)
    return plan


def write(name,value):
    EVIDENCE.mkdir(parents=True,exist_ok=True)
    part=EVIDENCE/(name+".tmp-"+uuid.uuid4().hex)
    try:
        with part.open("xb") as h:
            h.write(json.dumps(value,indent=2,sort_keys=True).encode())
            h.flush();os.fsync(h.fileno())
        os.replace(part,EVIDENCE/name)
    finally:
        if part.exists():part.unlink()


def lifecycle(browser,action,nonce):
    token=get(browser,"csrf")["token"]
    req=urllib.request.Request(URL+"agents/system.tunnel/actions",method="POST",
            data=json.dumps({"operation":action}).encode(),
            headers={"X-CSRF-TOKEN":token,"Origin":"https://localhost:19444",
                "Content-Type":"application/json",
                "Idempotency-Key":"owner-audited-reconciliation-20261107-"+nonce})
    with browser.open(req,timeout=20) as res:
        assert res.status==202
        op=json.load(res)
    ident=op["operationId"]
    write(nonce+"-ack.json",{"operation_id":ident})
    end=time.monotonic()+65
    while time.monotonic()<end:
        result=get(browser,"operations/"+ident)
        if result["state"] in ("succeeded","failed","unknown","conflict"):
            if result["state"]!="succeeded":raise RuntimeError("CORE_LIFECYCLE_"+result["state"])
            return ident
        time.sleep(.7)
    raise RuntimeError("CORE_LIFECYCLE_UNCONFIRMED")


def apply():
    browser=client()
    expected=json.loads((EVIDENCE/"plan.json").read_text("utf-8"))
    current=inspect(browser)
    assert current==expected,"OWNER_PLAN_CHANGED_REVIEW_REQUIRED"
    # A bounded, independent Production->Core control, not an orphan MCP task.
    lifecycle(browser,"stop","stop")
    try:
        snap=get(browser,"agents").get("data",[])
        if isinstance(snap,dict):snap=snap["agents"]
        assert next(x for x in snap if x["agentId"]=="system.tunnel")["processState"]=="Stopped"
        # Exact historical journal backup, including active WAL transactions.
        backup=EVIDENCE/"tasks-before-backup.db"
        assert not backup.exists()
        db=sqlite3.connect(DB,timeout=15)
        try:
            other=sqlite3.connect(backup)
            try:db.backup(other);other.commit()
            finally:other.close()
            assert sqlite3.connect(backup).execute("PRAGMA integrity_check").fetchone()[0]=="ok"
            db.execute("BEGIN IMMEDIATE")
            originals=load(db,set(expected["task_ids"]))
            assert len(originals)==3
            assert {r["task_id"]:sha(r) for r in originals}==expected["row_hashes"]
            db.execute("""CREATE TABLE IF NOT EXISTS task_owner_reconciliation_audit(
                 task_id TEXT PRIMARY KEY, plan_digest TEXT NOT NULL,
                 core_operation_id TEXT NOT NULL, classification TEXT NOT NULL,
                 recovered_at REAL NOT NULL, before_json TEXT NOT NULL,
                 after_json TEXT NOT NULL)""")
            for before in originals:
                task_id=before["task_id"]
                assert db.execute("SELECT 1 FROM task_owner_reconciliation_audit WHERE task_id=?",
                                  (task_id,)).fetchone() is None
                stamp=time.time()
                error="OWNER_RECONCILED:"+expected["reconciliation"][task_id]
                # Full-row compare and swap, never delete/overwrite historical evidence.
                where=" AND ".join('"'+k+'" IS ?' for k in before)
                args=[stamp,stamp,error,task_id,*before.values()]
                cursor=db.execute("UPDATE tasks SET state='failed', updated_at=?, recovered_at=?, "
                    "error=? WHERE task_id=? AND "+where,args)
                assert cursor.rowcount==1,"CAS_CONFLICT"
                after=dict(db.execute("SELECT * FROM tasks WHERE task_id=?",(task_id,)).fetchone())
                assert after==dict(before,state="failed",updated_at=stamp,recovered_at=stamp,error=error)
                db.execute("INSERT INTO task_owner_reconciliation_audit VALUES(?,?,?,?,?,?,?)",
                    (task_id,expected["expected_plan"],OPERATION_ID,expected["reconciliation"][task_id],
                     stamp,json.dumps(before,sort_keys=True),json.dumps(after,sort_keys=True)))
            db.commit()
            assert db.execute("PRAGMA integrity_check").fetchone()[0]=="ok"
            write("journal-audit.json",{"status":"APPLIED_WITH_CAS","task_ids":expected["task_ids"],
                "plan":expected["expected_plan"],"db_integrity":"ok"})
        finally:db.close()
    finally:
        lifecycle(browser,"start","start")
    # This readback uses a fresh connection after the Tunnel has restarted.
    db=sqlite3.connect(f"file:{DB.as_posix()}?mode=ro",uri=True)
    try:
        status=[list(r) for r in db.execute("SELECT task_id,state,error FROM tasks WHERE task_id IN (?,?,?)",
                    tuple(expected["task_ids"])).fetchall()]
        assert len(status)==3 and all(x[1]=="failed" for x in status)
    finally:db.close()
    write("result.json",{"task_states":status,"restored_tunnel":True})
    print("RECONCILED",len(status),"HISTORICAL_ROWS_AUDITED","TUNNEL_RESTARTED")


if __name__=="__main__":
    if len(sys.argv)!=2 or sys.argv[1] not in {"plan","apply"}:
        raise SystemExit("plan | apply")
    if sys.argv[1]=="plan":
        value=inspect(client())
        write("plan.json",value)
        print("RECONCILIATION_PLAN",value["expected_plan"],value["task_ids"])
    else:apply()
