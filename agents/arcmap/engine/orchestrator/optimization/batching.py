def coalesce_refresh(operations):
    ops=list(operations or [])
    refresh=[o for o in ops if o.get("action") in {"refresh","refresh_toc","refresh_view"}]
    non=[o for o in ops if o not in refresh]
    if refresh:
        non.append({"action":"refresh","coalesced":len(refresh)})
    return non

def context_projection(context,detail="metadata"):
    ctx=dict(context or {})
    base={k:ctx.get(k) for k in ("schema_version","fingerprint","document_revision","map","dataframe","errors")}
    if detail=="metadata":
        layers=ctx.get("layers")
        if isinstance(layers,dict):
            compact=[]
            for item in layers.get("layers") or []:
                compact.append({k:item.get(k) for k in ("name","role","geometry_type","feature_count","broken")})
            base["layers"]={"layers":compact}
        else:
            base["layers"]=layers
        base["layout"]=ctx.get("layout")
        return base
    return ctx
