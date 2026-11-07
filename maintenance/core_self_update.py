"""Independent Zagent Core single-file updater, invoked by owner Core Dashboard.

The worker must run in its OWN Python process. It survives Core shutdown,
waits for the original Core PID to exit, replaces only Zagent.Core.exe plus
payload-manifest.json with exact-byte backups, and restarts via the bound
Zagent.Launcher.exe. No MCP/Tunnel transport is used after the worker starts.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path


def digest(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as stream:
        for b in iter(lambda:stream.read(1024*1024),b""):
            h.update(b)
    return h.hexdigest()


def atomic(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+".new-"+uuid.uuid4().hex)
    try:
        with temporary.open("xb") as stream:
            stream.write(data);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        if temporary.exists():temporary.unlink()


def journal(data,update_id,state,**values):
    root=Path(data)/"core-updates/results"
    root.mkdir(parents=True,exist_ok=True)
    record=dict(schema=1,update_id=update_id,state=state,at=time.time(),**values)
    atomic(root/(update_id+".json"),json.dumps(record,sort_keys=True,indent=2).encode())
    return record


def validate_id(value):
    if not isinstance(value,str) or re.fullmatch(r"[A-Za-z0-9_-]{8,60}",value) is None:
        raise ValueError("UPDATE_ID_INVALID")
    return value


def paths(install,data,update_id):
    update_id=validate_id(update_id)
    install=Path(install).resolve(strict=True)
    data=Path(data).resolve(strict=True)
    if not (install/"Zagent.Core.exe").is_file() or not (install/"Zagent.Launcher.exe").is_file():
        raise ValueError("INSTALL_ROOT_INVALID")
    return install,data,data/"core-updates/staged"/update_id


def validate(install,data,update_id,expected_plan=None):
    install,data,stage=paths(install,data,update_id)
    planfile=stage/"plan.json";candidate=stage/"Zagent.Core.exe"
    if not planfile.is_file() or not candidate.is_file():
        raise ValueError("STAGING_INCOMPLETE")
    if stage.is_symlink() or candidate.is_symlink() or planfile.is_symlink():
        raise ValueError("REPARSE_PATH_REJECTED")
    raw=planfile.read_bytes()
    plan=json.loads(raw)
    if set(plan)!={"schema","update_id","old_sha256","new_sha256","new_size","old_manifest_sha256"}:
        raise ValueError("PLAN_SCHEMA_INVALID")
    if plan["schema"]!=1 or plan["update_id"]!=update_id:
        raise ValueError("PLAN_ID_MISMATCH")
    for key in ("old_sha256","new_sha256","old_manifest_sha256"):
        if not isinstance(plan[key],str) or not re.fullmatch(r"[a-f0-9]{64}",plan[key]):
            raise ValueError("HASH_INVALID")
    if (type(plan["new_size"]) is not int or not 1 <= plan["new_size"]<=512*1024*1024
            or candidate.stat().st_size!=plan["new_size"]):
        raise ValueError("FILE_SIZE_INVALID")
    if expected_plan and hashlib.sha256(raw).hexdigest()!=expected_plan:
        raise ValueError("PLAN_DIGEST_CONFLICT")
    if digest(install/"Zagent.Core.exe")!=plan["old_sha256"]:
        raise ValueError("CORE_BASELINE_CHANGED")
    if digest(install/"payload-manifest.json")!=plan["old_manifest_sha256"]:
        raise ValueError("MANIFEST_BASELINE_CHANGED")
    if digest(candidate)!=plan["new_sha256"]:
        raise ValueError("CANDIDATE_HASH_MISMATCH")
    return install,data,stage,plan,hashlib.sha256(raw).hexdigest()


def prepare(install,data,update_id,source):
    install,data,stage=paths(install,data,update_id)
    if stage.exists():raise ValueError("STAGED_UPDATE_EXISTS")
    source=Path(source).resolve(strict=True)
    if source.is_symlink() or not source.is_file():raise ValueError("CANDIDATE_INVALID")
    assert source.stat().st_size<=512*1024*1024
    stage.mkdir(parents=True,exist_ok=False)
    candidate=stage/"Zagent.Core.exe"
    shutil.copyfile(source,candidate)
    plan={
        "schema":1,"update_id":update_id,"old_sha256":digest(install/"Zagent.Core.exe"),
        "new_sha256":digest(candidate),"new_size":candidate.stat().st_size,
        "old_manifest_sha256":digest(install/"payload-manifest.json")
    }
    atomic(stage/"plan.json",json.dumps(plan,sort_keys=True,indent=2).encode())
    _,_,_,_,expected=validate(install,data,update_id)
    return expected


def modified_manifest(blob,old_sha,old_size,new_sha,new_size):
    old=json.loads(blob.decode("utf-8-sig"))
    assert len(old.get("files",[]))==old.get("file_count")
    hits=[row for row in old["files"] if row.get("Path")=="Zagent.Core.exe"]
    if len(hits)!=1 or hits[0]["Sha256"]!=old_sha or hits[0]["Size"]!=old_size:
        raise ValueError("CORE_MANIFEST_ENTRY_MISMATCH")
    pat=re.compile(rb'(\{\s*"Path"\s*:\s*"Zagent.Core\.exe"\s*,\s*"Size"\s*:\s*)(\d+)(\s*,\s*"Sha256"\s*:\s*")([a-f0-9]{64})("\s*\})')
    matches=list(pat.finditer(blob))
    if len(matches)!=1:raise ValueError("MANIFEST_ENCODING_UNKNOWN")
    if int(matches[0].group(2))!=old_size or matches[0].group(4).decode()!=old_sha:
        raise ValueError("MANIFEST_BASELINE_MISMATCH")
    blob,count=pat.subn(lambda m:m.group(1)+str(new_size).encode()+m.group(3)+new_sha.encode()+m.group(5),blob)
    assert count==1
    pat_total=re.compile(rb'("total_bytes"\s*:\s*)(\d+)')
    matches=list(pat_total.finditer(blob))
    if len(matches)!=1 or int(matches[0].group(2))!=old["total_bytes"]:
        raise ValueError("MANIFEST_TOTAL_UNKNOWN")
    blob,count=pat_total.subn(lambda m:m.group(1)+str(old["total_bytes"]+new_size-old_size).encode(),blob)
    assert count==1
    fresh=json.loads(blob.decode("utf-8-sig"))
    assert len(fresh["files"])==old["file_count"]
    assert fresh["total_bytes"]==old["total_bytes"]+new_size-old_size
    return blob


def pid_alive(pid):
    if os.name!="nt":
        try:os.kill(pid,0);return True
        except ProcessLookupError:return False
    import ctypes
    handle=ctypes.windll.kernel32.OpenProcess(0x100000,False,int(pid))
    if not handle:return False
    try:return ctypes.windll.kernel32.WaitForSingleObject(handle,0)!=0
    finally:ctypes.windll.kernel32.CloseHandle(handle)


def wait_pid_exit(pid,timeout=70):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        if not pid_alive(pid):return True
        time.sleep(.3)
    return False


def restart_core(install,data):
    # Existing product launcher validates enrolled installation, TLS owner ACL,
    # bundled runtimes and the exact saved DataRoot before it starts Core.
    environment=os.environ.copy()
    environment["ZAGENT_LAUNCHER_DATA_ROOT"]=str(data)
    # The launcher normally exits shortly after spawning Core; do not confuse
    # launcher's PID with Core PID.
    return subprocess.Popen([str(install/"Zagent.Launcher.exe")],
          cwd=str(install),env=environment,close_fds=True)


def reachable(port=19444,timeout=75):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        try:
            with socket.create_connection(("127.0.0.1",port),timeout=1):
                return True
        except OSError:time.sleep(.5)
    return False


def worker(install,data,update_id,expected_plan,core_pid,health_port=19444):
    install,data,stage,plan,actual=validate(install,data,update_id,expected_plan)
    if not isinstance(core_pid,int) or core_pid<=4:
        raise ValueError("CORE_PID_INVALID")
    backup=data/"core-updates/backups"/update_id
    if backup.exists():raise ValueError("UPDATE_ALREADY_PROCESSED")
    old_exe=install/"Zagent.Core.exe"
    old_manifest=install/"payload-manifest.json"
    backup.mkdir(parents=True,exist_ok=False)
    shutil.copyfile(old_exe,backup/"Zagent.Core.exe")
    shutil.copyfile(old_manifest,backup/"payload-manifest.json")
    if digest(backup/"Zagent.Core.exe")!=plan["old_sha256"] or digest(backup/"payload-manifest.json")!=plan["old_manifest_sha256"]:
        raise ValueError("BACKUP_MISMATCH")
    newmanifest=modified_manifest((backup/"payload-manifest.json").read_bytes(),plan["old_sha256"],
                                 old_exe.stat().st_size,plan["new_sha256"],plan["new_size"])
    atomic(backup/"planned-manifest.json",newmanifest)
    journal(data,update_id,"waiting_core_exit",expected_plan=actual,core_pid=core_pid)
    if not wait_pid_exit(core_pid):
        journal(data,update_id,"failed",reason="CORE_EXIT_TIMEOUT")
        return False
    changed=False
    try:
        # Verify no simultaneous updater replaced binaries after the Core exited.
        validate(install,data,update_id,expected_plan)
        journal(data,update_id,"applying")
        temp=install/("Zagent.Core.exe.pending-"+uuid.uuid4().hex)
        try:
            shutil.copyfile(stage/"Zagent.Core.exe",temp)
            if digest(temp)!=plan["new_sha256"]:raise ValueError("STAGED_FILE_COPY_FAILED")
            os.replace(temp,old_exe)
        finally:
            if temp.exists():temp.unlink()
        changed=True
        atomic(old_manifest,newmanifest)
        if digest(old_exe)!=plan["new_sha256"] or digest(old_manifest)!=hashlib.sha256(newmanifest).hexdigest():
            raise ValueError("POST_APPLY_VERIFICATION_FAILED")
        journal(data,update_id,"restarting")
        launcher=restart_core(install,data)
        launcher.wait(timeout=35)
        if launcher.returncode!=0:raise RuntimeError("LAUNCHER_EXIT_FAILURE")
        if not reachable(port=health_port,timeout=75):
            raise RuntimeError("CORE_LISTENER_UNAVAILABLE_AFTER_UPDATE")
        journal(data,update_id,"succeeded",new_core_sha256=plan["new_sha256"],
                new_manifest_sha256=digest(old_manifest),listener_port=health_port)
        return True
    except BaseException as error:
        # Independent worker remains alive to restore exact bytes on failure;
        # state is never claimed successful if the launcher or Core fails.
        journal(data,update_id,"rolling_back",reason=type(error).__name__)
        if changed:
            atomic(old_exe,(backup/"Zagent.Core.exe").read_bytes())
        atomic(old_manifest,(backup/"payload-manifest.json").read_bytes())
        recovered=bool(digest(old_exe)==plan["old_sha256"] and digest(old_manifest)==plan["old_manifest_sha256"])
        if not recovered:
            journal(data,update_id,"manual_recovery_required",reason="ROLLBACK_HASH_MISMATCH")
            raise
        try:
            launcher=restart_core(install,data);launcher.wait(timeout=35)
            journal(data,update_id,"rolled_back",reason=type(error).__name__,
                    old_core_restored=True,launcher_exit=launcher.returncode)
        except BaseException:
            journal(data,update_id,"manual_recovery_required",reason="ROLLBACK_RESTART_FAILED")
            raise
        raise


def main(argv=None):
    parser=argparse.ArgumentParser()
    action=parser.add_subparsers(dest="action",required=True)
    p=action.add_parser("prepare")
    p.add_argument("install");p.add_argument("data");p.add_argument("update_id");p.add_argument("candidate")
    p=action.add_parser("validate")
    p.add_argument("install");p.add_argument("data");p.add_argument("update_id");p.add_argument("expected_plan")
    p=action.add_parser("worker")
    p.add_argument("install");p.add_argument("data");p.add_argument("update_id");p.add_argument("expected_plan")
    p.add_argument("core_pid",type=int);p.add_argument("--health-port",type=int,default=19444)
    opts=parser.parse_args(argv)
    if opts.action=="prepare":
        print("CORE_UPDATE_STAGED",prepare(opts.install,opts.data,opts.update_id,opts.candidate))
    elif opts.action=="validate":
        print("CORE_UPDATE_PLAN_VALID",validate(opts.install,opts.data,opts.update_id,opts.expected_plan)[-1])
    else:
        if not worker(opts.install,opts.data,opts.update_id,opts.expected_plan,opts.core_pid,opts.health_port):
            raise SystemExit(1)
        print("CORE_UPDATE_SUCCEEDED",opts.update_id)


if __name__=="__main__":
    main()
