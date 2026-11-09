"""Owner-controlled scoped deployment of known tested Router modules and independent updater.
No edits to Production, app journal or user data. Stop/start only Multi Platform Tunnel.
"""
from pathlib import Path
import hashlib,json,ssl,http.cookiejar,urllib.request,os,uuid,time,shutil,sys
SRC=Path(r"D:\3-Ikbalzohr\Agent\phyton_zagent_multiplatform")
DEST=Path(r"D:\3-Ikbalzohr\Agent\ZohrSystem\Zagent Multi Platform")
BASE_SHA="ef0a3ffe21aed3c1a1c5e551e25b757f571c629217fbd12596fbf1c679e41897"
EVIDENCE=SRC/"_validation/mp-parallel-and-selfupdater-stage-20261107"
CERT=SRC/"_validation/arcmap-deploy-d6579b805c874fbbb9a4147cf048677f/dashboard-public-cert.pem"
ROOT="https://localhost:19444/api/management/v1/"
PATHS=(
"agents/tunnel/engine/router/orchestration.py",
"agents/tunnel/engine/router/resource_scope.py",
"maintenance/core_self_update.py")
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest() if Path(p).is_file() else None
def atomic(p,raw):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
 temp=p.with_name(p.name+".install-"+uuid.uuid4().hex)
 try:
  with temp.open("xb") as f:f.write(raw);f.flush();os.fsync(f.fileno())
  os.replace(temp,p)
 finally:
  if temp.exists():temp.unlink()
def save(p,obj):atomic(EVIDENCE/p,json.dumps(obj,indent=2,sort_keys=True).encode())
def browser():
 return urllib.request.build_opener(
  urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=str(CERT))),
  urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
def get(client,path):
 with client.open(ROOT+path,timeout=13) as res:
  if res.status!=200:raise RuntimeError("GET_NOT_200 "+path)
  return json.load(res)
def agents(c):
 raw=get(c,"agents")["data"]
 if isinstance(raw,dict):raw=raw.get("agents",[])
 return {a["agentId"]:{"pid":a.get("osProcessId"),"state":a.get("processState"),"health":a.get("health")}
         for a in raw}
def lifecycle(c,action,nonce):
 csrf=get(c,"csrf")["token"]
 req=urllib.request.Request(ROOT+"agents/system.tunnel/actions",method="POST",
  headers={"X-CSRF-TOKEN":csrf,"Origin":"https://localhost:19444","Content-Type":"application/json",
   "Idempotency-Key":"mp-parallel-selfupdate-20261107-"+nonce},
  data=json.dumps({"operation":action}).encode())
 with c.open(req,timeout=18) as x:
  if x.status!=202:raise RuntimeError("LIFECYCLE_POST_FAILED")
  result=json.load(x)
 ident=result["operationId"]
 save(nonce+"-ack.json",{"operation_id":ident})
 end=time.monotonic()+70
 while time.monotonic()<end:
  row=get(c,"operations/"+ident)
  if row["state"]=="succeeded":return ident
  if row["state"] in ("failed","unknown","conflict"):raise RuntimeError("LIFECYCLE_"+row["state"])
  time.sleep(.8)
 raise RuntimeError("LIFECYCLE_TIMEOUT")
def build_manifest(base):
 doc=json.loads(base.decode("utf-8-sig"))
 records=doc["files"]
 assert len(records)==doc["file_count"]==12005
 count=0;delta=0
 for name in PATHS:
  replacement=EVIDENCE/"staged"/name
  old=DEST/name
  matching=[p for p in records if p.get("Path")==name]
  if old.is_file():
   assert len(matching)==1 and sha(old)==matching[0]["Sha256"] and old.stat().st_size==matching[0]["Size"]
   delta+=replacement.stat().st_size-old.stat().st_size
   matching[0]["Sha256"]=sha(replacement);matching[0]["Size"]=replacement.stat().st_size
  else:
   assert len(matching)==0
   records.append({"Path":name,"Size":replacement.stat().st_size,"Sha256":sha(replacement)})
   delta+=replacement.stat().st_size
   count+=1
 doc["file_count"]+=count
 doc["total_bytes"]+=delta
 assert doc["file_count"]==len(records)
 return (json.dumps(doc,ensure_ascii=False,indent=2)+"\n").encode()
def stage():
 assert not EVIDENCE.exists(),"STAGE_ALREADY_EXISTS"
 assert sha(DEST/"payload-manifest.json")==BASE_SHA
 (EVIDENCE/"staged").mkdir(parents=True)
 (EVIDENCE/"before").mkdir()
 prior={}
 for rel in PATHS:
  src=SRC/rel; target=DEST/rel
  assert src.is_file()
  dest=EVIDENCE/"staged"/rel;dest.parent.mkdir(parents=True,exist_ok=True)
  shutil.copyfile(src,dest)
  assert sha(src)==sha(dest)
  if target.is_file():
   old=EVIDENCE/"before"/rel;old.parent.mkdir(parents=True,exist_ok=True)
   shutil.copyfile(target,old)
   assert sha(old)==sha(target)
  prior[rel]={"original":sha(target),"staged":sha(dest)}
 shutil.copyfile(DEST/"payload-manifest.json",EVIDENCE/"before"/"payload-manifest.json")
 manifest=build_manifest((EVIDENCE/"before"/"payload-manifest.json").read_bytes())
 atomic(EVIDENCE/"staged"/"payload-manifest.json",manifest)
 c=browser()
 before=agents(c)
 assert all(before[k]["state"]=="Running" for k in ("system.tunnel","files.service","web.service","arcmap.service","qgis.service"))
 tasks=get(c,"jobs")["data"]["tasks"]
 active=[x for x in tasks if x["state"] in ("running","queued","waiting_capacity","waiting_lock","accepted","recovering","cancelling")]
 assert not active,"ACTIVE_JOBS_BLOCK_STAGE"
 save("plan.json",{"base_manifest":BASE_SHA,"new_manifest":sha(EVIDENCE/"staged"/"payload-manifest.json"),
  "entries":prior,"services":before,"active_jobs":0})
 print("STAGED",len(PATHS),"NEW_MANIFEST",sha(EVIDENCE/"staged"/"payload-manifest.json"))
def check_baseline(plan):
 assert sha(DEST/"payload-manifest.json")==BASE_SHA,"LIVE_MANIFEST_CHANGED"
 assert sha(EVIDENCE/"before"/"payload-manifest.json")==BASE_SHA
 for rel,item in plan["entries"].items():
  assert sha(DEST/rel)==item["original"],"LIVE_MODULE_CHANGED "+rel
  assert sha(EVIDENCE/"staged"/rel)==item["staged"],"STAGE_CHANGED "+rel
 assert sha(EVIDENCE/"staged"/"payload-manifest.json")==plan["new_manifest"]
def install():
 plan=json.loads((EVIDENCE/"plan.json").read_text("utf-8"))
 check_baseline(plan)
 c=browser();initial=agents(c)
 assert initial==plan["services"],"AGENT_PID_CHANGED_REVIEW"
 jobs=get(c,"jobs")["data"]["tasks"]
 assert not any(t["state"] in ("running","accepted","queued","waiting_capacity","waiting_lock","cancelling","recovering") for t in jobs)
 was_stopped=False;was_applied=False
 try:
  lifecycle(c,"stop","stop")
  was_stopped=True
  assert agents(c)["system.tunnel"]["state"]=="Stopped"
  check_baseline(plan)
  for rel in PATHS:atomic(DEST/rel,(EVIDENCE/"staged"/rel).read_bytes())
  atomic(DEST/"payload-manifest.json",(EVIDENCE/"staged"/"payload-manifest.json").read_bytes())
  was_applied=True
  for rel,item in plan["entries"].items():assert sha(DEST/rel)==item["staged"]
  assert sha(DEST/"payload-manifest.json")==plan["new_manifest"]
  save("applied.json",{"new_manifest":plan["new_manifest"],"paths":list(PATHS)})
  lifecycle(c,"start","start")
  after=agents(c)
  assert after["system.tunnel"]["state"]=="Running" and after["system.tunnel"]["pid"]!=initial["system.tunnel"]["pid"]
  for key in ("files.service","web.service","arcmap.service","qgis.service"):
   assert after[key]["state"]=="Running" and after[key]["pid"]==initial[key]["pid"],"UNRELATED_AGENT_CHANGED "+key
  routes=get(c,"routes")["data"]
  assert routes["routerStatus"]=="Ready"
  save("success.json",{"manifest":sha(DEST/"payload-manifest.json"),"agents_before":initial,
     "agents_after":after,"router_status":routes["routerStatus"]})
  print("DEPLOY_SUCCESS","ROUTER_PID",after["system.tunnel"]["pid"],"UNRELATED_UNCHANGED",True)
 except BaseException as ex:
  save("error.json",{"type":type(ex).__name__,"message":str(ex),"applied":was_applied,"stopped":was_stopped})
  if was_stopped:
   try:
    state=agents(c)["system.tunnel"]["state"]
    if state=="Running":lifecycle(c,"stop","rollback-stop")
    assert agents(c)["system.tunnel"]["state"]=="Stopped"
    if was_applied:
     for rel,item in plan["entries"].items():
      prior=EVIDENCE/"before"/rel
      if prior.is_file():atomic(DEST/rel,prior.read_bytes())
      elif (DEST/rel).exists() and sha(DEST/rel)==item["staged"]:(DEST/rel).unlink()
     atomic(DEST/"payload-manifest.json",(EVIDENCE/"before"/"payload-manifest.json").read_bytes())
     assert sha(DEST/"payload-manifest.json")==BASE_SHA
     print("ROLLBACK_BYTES_RESTORED")
    lifecycle(c,"start","rollback-start")
   except BaseException as second: print("ROLLBACK_REQUIRES_OWNER_REVIEW",str(second))
  raise
def verify():
 plan=json.loads((EVIDENCE/"plan.json").read_text("utf-8"))
 for rel,item in plan["entries"].items():assert sha(DEST/rel)==item["staged"]
 assert sha(DEST/"payload-manifest.json")==plan["new_manifest"]
 c=browser()
 a=agents(c)
 assert a["system.tunnel"]["state"]=="Running"
 print("INSTALLED_VERIFIED",plan["new_manifest"],[(k,v["state"],v["pid"]) for k,v in a.items()])
if __name__=="__main__":
 if len(sys.argv)!=2 or sys.argv[1] not in ("stage","apply","verify"):
  raise SystemExit("stage | apply | verify")
 {"stage":stage,"apply":install,"verify":verify}[sys.argv[1]]()
