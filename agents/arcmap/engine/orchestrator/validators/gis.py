from .model import result, aggregate

def _layers(context):
    raw=(context or {}).get("layers")
    if isinstance(raw,dict):
        raw=raw.get("layers")
    return list(raw or [])

def validate_gis(context,profile):
    results=[]
    layers=_layers(context)
    by_role={str(x.get("role")):x for x in layers if x.get("role")}
    required=list(profile.get("required_layer_roles") or [])
    missing=[r for r in required if r not in by_role]
    results.append(result("GIS_REQUIRED_LAYERS","FAIL" if missing else "PASS",
                          expected=required,actual={"missing":missing},
                          severity="critical",permitted_repair=None))
    broken=[x.get("name") or x.get("role") for x in layers if x.get("broken")]
    results.append(result("GIS_BROKEN_REQUIRED_SOURCE","FAIL" if broken else "PASS",
                          expected=0,actual=broken,severity="critical"))
    crs=(context or {}).get("crs")
    if not crs:
        df=(context or {}).get("dataframe") or {}
        if isinstance(df,dict):
            crs=df.get("spatial_reference")
    results.append(result("GIS_CRS_KNOWN","PASS" if crs else "FAIL",
                          expected="known CRS",actual=crs,severity="critical"))
    mixed=bool((context or {}).get("mixed_crs"))
    transform_ok=bool((context or {}).get("datum_transformation_verified"))
    mixed_status="PASS" if (not mixed or transform_ok) else "FAIL"
    results.append(result("GIS_MIXED_CRS_TRANSFORM",mixed_status,
                          expected="verified transformation when CRS differs",
                          actual={"mixed":mixed,"transformation_verified":transform_ok},severity="critical"))
    subset_required=bool(profile.get("subset_verification_required"))
    subset_ok=bool((context or {}).get("gp_subset_verified"))
    results.append(result("GIS_SUBSET_SEMANTICS","PASS" if (not subset_required or subset_ok) else "FAIL",
                          expected=not subset_required or True,actual=subset_ok if subset_required else "not_required",
                          severity="critical"))
    required_caps=list(profile.get("required_capabilities") or [])
    available=set((context or {}).get("available_capabilities") or [])
    missing_caps=[c for c in required_caps if c not in available]
    results.append(result("GIS_CAPABILITIES","FAIL" if missing_caps else "PASS",
                          expected=required_caps,actual={"missing":missing_caps},severity="critical"))
    for role,spec in (profile.get("layer_rules") or {}).items():
        layer=by_role.get(role)
        if not layer:
            continue
        if spec.get("geometry_type"):
            ok=layer.get("geometry_type")==spec["geometry_type"]
            results.append(result("GIS_GEOMETRY_TYPE:"+role,"PASS" if ok else "FAIL",
                                  expected=spec["geometry_type"],actual=layer.get("geometry_type"),severity="critical"))
        req_fields=set(spec.get("required_fields") or [])
        fields=set(layer.get("fields") or [])
        missing_fields=sorted(req_fields-fields)
        results.append(result("GIS_REQUIRED_FIELDS:"+role,"FAIL" if missing_fields else "PASS",
                              expected=sorted(req_fields),actual={"missing":missing_fields},severity="critical"))
        if spec.get("nonempty",False):
            count=layer.get("feature_count")
            ok=isinstance(count,int) and count>0
            results.append(result("GIS_NONEMPTY:"+role,"PASS" if ok else "FAIL",
                                  expected=">0",actual=count,severity="critical"))
    return aggregate(results)
