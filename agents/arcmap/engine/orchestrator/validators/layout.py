from .model import result, aggregate

A4_MM={"portrait":(210.0,297.0),"landscape":(297.0,210.0)}

def _inside(bounds,w,h):
    if not isinstance(bounds,(list,tuple)) or len(bounds)!=4:
        return False
    x,y,bw,bh=[float(v) for v in bounds]
    return x>=0 and y>=0 and bw>=0 and bh>=0 and x+bw<=w+0.01 and y+bh<=h+0.01

def _overlap(a,b):
    ax,ay,aw,ah=a; bx,by,bw,bh=b
    return not (ax+aw<=bx or bx+bw<=ax or ay+ah<=by or by+bh<=ay)

def validate_layout(layout,profile):
    results=[]
    orientation=profile.get("orientation","landscape")
    expected=A4_MM.get(orientation)
    actual=(float(layout.get("page_width_mm",0)),float(layout.get("page_height_mm",0)))
    page_ok=expected and abs(actual[0]-expected[0])<=0.5 and abs(actual[1]-expected[1])<=0.5
    results.append(result("LAYOUT_A4_PAGE","PASS" if page_ok else "FAIL",expected=expected,actual=actual,severity="critical"))
    elems=list(layout.get("elements") or [])
    by_role={str(e.get("role")):e for e in elems if e.get("role")}
    required=list(profile.get("required_elements") or [])
    missing=[x for x in required if x not in by_role]
    results.append(result("LAYOUT_REQUIRED_ELEMENTS","FAIL" if missing else "PASS",
                          expected=required,actual={"missing":missing},severity="critical"))
    if expected:
        out=[e.get("role") or e.get("name") for e in elems if not _inside(e.get("bounds_mm"),*expected)]
        results.append(result("LAYOUT_BOUNDS","FAIL" if out else "PASS",
                              expected="inside page",actual=out,severity="critical",
                              permitted_repair="move_element_in_bounds" if out else None))
    critical_roles=set(profile.get("non_overlap_roles") or [])
    overlaps=[]
    for i,a in enumerate(elems):
        for b in elems[i+1:]:
            ar=a.get("role"); br=b.get("role")
            if ar in critical_roles and br in critical_roles and _overlap(a.get("bounds_mm",[0,0,0,0]),b.get("bounds_mm",[0,0,0,0])):
                overlaps.append([ar,br])
    results.append(result("LAYOUT_CRITICAL_OVERLAP","FAIL" if overlaps else "PASS",
                          expected=[],actual=overlaps,severity="critical",
                          permitted_repair="move_element_in_bounds" if overlaps else None))
    return aggregate(results)
