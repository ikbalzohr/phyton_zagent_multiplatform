# Python 3 module: augment existing MCP server, do not replace baseline tools.

def _find_transport(ns):
    for n in ['call_bridge','_call_bridge','bridge_request','_bridge_request','request_bridge','_request_bridge','invoke_bridge','_invoke_bridge']:
        if callable(ns.get(n)): return ns[n]
    for n,f in ns.items():
        low=n.lower()
        if callable(f) and 'bridge' in low and any(x in low for x in ('call','request','invoke','post')): return f
    return None

def _invoke(t,a,p):
    last=None
    for fn in [lambda:t(a,p),lambda:t(action=a,payload=p),lambda:t(a,**p),lambda:t({'action':a,'params':p}),lambda:t({'action':a,'payload':p})]:
        try: return fn()
        except TypeError as e: last=e
    raise RuntimeError('Signature transport bridge tidak cocok: %s'%last)

def auto_install(ns):
    t=_find_transport(ns)
    if not t: return {'ok':False,'reason':'bridge transport not auto-detected'}
    mcp=ns.get('mcp') or ns.get('server')
    if not mcp or not hasattr(mcp,'tool'):
        for o in ns.values():
            if hasattr(o,'tool') and callable(getattr(o,'tool')): mcp=o; break
    if not mcp: return {'ok':False,'reason':'FastMCP object not auto-detected'}
    installed=[]
    def reg(name,fn):
        try: mcp.tool(name=name)(fn)
        except TypeError: fn.__name__=name; mcp.tool()(fn)
        installed.append(name)
    def discover(data_root:str,max_items:int=10000): return _invoke(t,'stage2_discover_data',{'data_root':data_root,'max_items':max_items})
    def preview(data_root:str,recipe:str,max_items:int=10000,min_score:float=0.62): return _invoke(t,'stage2_preview_match',{'data_root':data_root,'recipe':recipe,'max_items':max_items,'min_score':min_score})
    def validate(template_mxd:str,profile:str=None): return _invoke(t,'stage2_validate_template',{'template_mxd':template_mxd,'profile':profile})
    def build(template_mxd:str,data_root:str,output_dir:str,recipe:str,profile:str=None,base_name:str=None,snapshot_root:str=None,save_mxd:bool=True): return _invoke(t,'stage2_build_a4',locals())
    def batch(job_file:str): return _invoke(t,'stage2_batch_build',{'job_file':job_file})
    def restore(checkpoint_mxd:str,target_mxd:str): return _invoke(t,'stage2_restore_checkpoint',locals())
    def gp(tool:str,args:list=None,kwargs:dict=None,allow_destructive:bool=False): return _invoke(t,'stage2_generic_gp',locals())
    reg('arcmap_stage2_discover_data',discover); reg('arcmap_stage2_preview_match',preview); reg('arcmap_stage2_validate_template',validate); reg('arcmap_stage2_build_a4',build); reg('arcmap_stage2_batch_build',batch); reg('arcmap_stage2_restore_checkpoint',restore); reg('arcmap_stage2_generic_gp',gp)
    return {'ok':True,'installed':installed}
