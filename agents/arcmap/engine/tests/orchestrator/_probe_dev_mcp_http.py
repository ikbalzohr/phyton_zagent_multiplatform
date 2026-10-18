import json, time, uuid
import httpx

URL="http://127.0.0.3:19040/mcp"
headers={"Accept":"application/json, text/event-stream","Content-Type":"application/json","User-Agent":"O1-Probe"}

def extract(resp):
    ct=resp.headers.get("content-type","").lower()
    if "application/json" in ct:
        return resp.json()
    payloads=[]
    for line in resp.text.splitlines():
        if line.startswith("data:"):
            payloads.append(line[5:].strip())
    for p in reversed(payloads):
        if p and p != "[DONE]":
            try: return json.loads(p)
            except Exception: pass
    return {"raw":resp.text[:2000]}

with httpx.Client(timeout=10.0, trust_env=False) as c:
    init={"jsonrpc":"2.0","id":"init-"+uuid.uuid4().hex,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"O1-Probe","version":"1"}}}
    r=c.post(URL,json=init,headers=headers)
    sid=r.headers.get("mcp-session-id")
    print("INIT",r.status_code,"sid",sid,extract(r))
    h=dict(headers)
    if sid: h["Mcp-Session-Id"]=sid
    r=c.post(URL,json={"jsonrpc":"2.0","method":"notifications/initialized","params":{}},headers=h)
    print("NOTIFY",r.status_code)
    goal={"schema_version":"2.0","goal_type":"build_map","raw_goal":"Susun peta administrasi PT Buol Agri Lestari dari data yang tersedia","target_mode":"CURRENT","required_layer_roles":["batas_perusahaan","jalan","sungai","desa"],"layout":{"paper":"A4","orientation":"landscape"},"outputs":{"formats":["PDF","PNG"],"dpi":400,"save_mxd":False},"dry_run":True,"max_repair_cycles":3,"source_edit_policy":"read_only"}
    call={"jsonrpc":"2.0","id":"call-"+uuid.uuid4().hex,"method":"tools/call","params":{"name":"arcmap_goal_plan","arguments":{"goal":goal}}}
    t=time.monotonic()
    try:
        r=c.post(URL,json=call,headers=h,timeout=10.0)
        print("CALL_ELAPSED",round(time.monotonic()-t,3),"STATUS",r.status_code)
        data=extract(r)
        print(json.dumps(data,ensure_ascii=False)[:12000])
    except Exception as e:
        print("CALL_ELAPSED",round(time.monotonic()-t,3),"ERROR",type(e).__name__,repr(str(e)))
