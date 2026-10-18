# -*- coding: utf-8 -*-
from __future__ import print_function
import json
import os
import shutil
import sys
import traceback

def _read(path):
    with open(path, "rb") as f:
        raw=f.read()
    if not isinstance(raw, str):
        raw=raw.decode("utf-8")
    return json.loads(raw)

def _write(path, value):
    data=json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)
    if not isinstance(data, bytes):
        data=data.encode("utf-8")
    with open(path, "wb") as f:
        f.write(data)

def _engine(root):
    if root not in sys.path:
        sys.path.insert(0, root)
    from stage2 import engine
    return engine

def _merge_layout(engine, profile, recipe, company_name, map_type, name):
    layout={}
    layout.update((profile or {}).get("layout") or {})
    for k,v in (recipe.get("layout") or {}).items():
        if isinstance(v,dict) and isinstance(layout.get(k),dict):
            merged=dict(layout.get(k) or {})
            merged.update(v)
            layout[k]=merged
        else:
            layout[k]=v
    engine._render_layout_tokens(layout, {
        "company_name":company_name or "",
        "map_type":map_type or "",
        "map_name":name,
    })
    return layout

def _prepare(engine, seed_mxd, data_root, workspace, goal, blank):
    if not os.path.isfile(seed_mxd):
        raise ValueError("Seed/template MXD tidak ditemukan: "+seed_mxd)
    if not os.path.isdir(data_root):
        raise ValueError("Folder data tidak ditemukan: "+data_root)
    if not os.path.isdir(workspace):
        os.makedirs(workspace)

    recipe=goal.get("recipe") or {}
    profile=goal.get("profile") or {}
    name=engine.safe_filename(
        goal.get("title") or goal.get("map_type") or
        ("Zagent Blank A4" if blank else "Zagent Template A4")
    )
    working=os.path.join(workspace, "working.mxd")
    shutil.copy2(seed_mxd, working)

    discovered=engine.discover_data(
        data_root, int(recipe.get("max_discovery_items",10000)))
    matches=engine.match_slots(
        recipe.get("layers",[]),
        discovered,
        float(recipe.get("min_match_score",0.62)))
    if matches["missing"] and recipe.get("fail_on_missing_required",True):
        raise RuntimeError(
            "Dataset wajib tidak ditemukan: "+
            ", ".join([x.get("name","?") for x in matches["missing"]]))

    mxd=engine.open_mxd(working)
    try:
        df=engine.get_df(mxd, recipe.get("data_frame",""))
        # ArcGIS standard A4 page templates are used as the C seed.
        # They contain no production source datasets. Remove any seed layers
        # defensively before applying C data.
        if blank:
            import arcpy
            for lyr in list(arcpy.mapping.ListLayers(mxd, "", df))[::-1]:
                try:
                    arcpy.mapping.RemoveLayer(df, lyr)
                except Exception:
                    pass

        for mr in matches["matches"]:
            slot,item=mr["slot"],mr["item"]
            lname=slot.get("layer") or slot.get("name") or item["name"]
            mode=slot.get("mode","replace_or_add")
            existing=None
            try:
                existing=engine.find_layer(mxd,df,lname)
            except Exception:
                existing=None
            if existing and mode in ("replace","replace_or_add"):
                try:
                    lyr=engine.replace_source(mxd,df,lname,item["path"])
                except Exception:
                    if mode=="replace":
                        raise
                    lyr=engine.add_dataset(
                        mxd,df,item["path"],lname,slot.get("position","BOTTOM"))
            elif existing and mode=="skip_if_exists":
                lyr=existing
            else:
                lyr=engine.add_dataset(
                    mxd,df,item["path"],lname,slot.get("position","BOTTOM"))
            engine.configure_layer(mxd,df,lyr.name,slot)

        if recipe.get("layer_order"):
            engine.apply_order(mxd,df,recipe["layer_order"])
        for gp in recipe.get("geoprocessing",[]):
            engine.run_gp(
                gp["tool"],gp.get("args"),gp.get("kwargs"),
                bool(gp.get("allow_destructive",False)))
        if recipe.get("extent"):
            engine.configure_extent(mxd,df,recipe["extent"])

        layout=_merge_layout(
            engine,profile,recipe,
            goal.get("company_name"),goal.get("map_type"),name)
        if layout:
            engine.apply_layout(mxd,layout)
        legend={}
        legend.update(profile.get("legend") or {})
        legend.update(recipe.get("legend") or {})
        if legend:
            engine.rebuild_legend(mxd,df,legend)
        mxd.save()

        qa=engine.qa(mxd,recipe,profile)
        if not qa.get("ok") and recipe.get("fail_on_qa",True):
            raise RuntimeError("QA gagal: "+"; ".join(qa.get("errors") or []))
        return {
            "ok":True,
            "working_mxd":working,
            "base_name":name,
            "discovery":discovered,
            "matches":matches,
            "qa":qa,
            "blank_seed":bool(blank),
            "seed_mxd":seed_mxd,
        }
    finally:
        try:
            del mxd
        except Exception:
            pass

def _blank_seed(goal):
    root=goal.get("arcgis_desktop_root") or r"C:\Program Files (x86)\ArcGIS\Desktop10.6"
    orientation=str((goal.get("layout") or {}).get("orientation") or "landscape").lower()
    leaf="ISO A4 Portrait.mxd" if orientation=="portrait" else "ISO A4 Landscape.mxd"
    return os.path.join(
        root,"MapTemplates","Standard Page Sizes","ISO (A) Page Sizes",leaf)

def main():
    req_path=sys.argv[1]
    res_path=sys.argv[2]
    req=_read(req_path)
    engine=_engine(req["engine_root"])
    op=req.get("operation")
    args=req.get("arguments") or {}
    if op=="probe":
        import arcpy
        result={
            "ok":True,
            "python":sys.version,
            "arcgis_version":(arcpy.GetInstallInfo() or {}).get("Version"),
            "arcpy":True,
        }
    elif op=="discover_data":
        result=engine.discover_data(
            args["data_root"],
            int(args.get("max_items",10000)))
        result["ok"]=True
        result["execution_lane"]="arcgis_file_worker"
    elif op=="preview_match":
        discovered=engine.discover_data(
            args["data_root"],
            int(args.get("max_items",10000)))
        recipe=args.get("recipe") or {}
        result=engine.match_slots(
            recipe.get("layers",[]),
            discovered,
            float(args.get("min_score",recipe.get("min_match_score",0.62))))
        result["ok"]=True
        result["discovery"]={
            "root":discovered.get("root"),
            "count":discovered.get("count"),
            "warnings":discovered.get("warnings") or [],
        }
        result["execution_lane"]="arcgis_file_worker"
    elif op=="validate_template":
        mxd=engine.open_mxd(args["template_mxd"])
        try:
            profile=args.get("profile") or {}
            names=set([x["name"] for x in engine.layout_manifest(mxd)])
            missing=[
                x for x in profile.get("required_layout_elements",[])
                if x not in names
            ]
            a4=engine.a4_check(mxd)
            result={
                "ok":bool(a4.get("ok")) and not missing,
                "a4":a4,
                "missing_elements":missing,
                "elements":engine.layout_manifest(mxd),
                "execution_lane":"arcgis_file_worker",
            }
        finally:
            try:
                del mxd
            except Exception:
                pass
    elif op=="prepare_template":
        result=_prepare(
            engine,args["template_mxd"],args["data_root"],
            args["workspace"],args.get("goal") or {},False)
    elif op=="prepare_blank":
        goal=args.get("goal") or {}
        if not bool(args.get("disposable")):
            raise RuntimeError("DISPOSABLE_TARGET_REQUIRED")
        seed=goal.get("blank_seed_mxd") or _blank_seed(goal)
        result=_prepare(
            engine,seed,args["data_root"],args["workspace"],goal,True)
    elif op=="render_staging":
        working=args["working_mxd"]
        staging=args["staging_dir"]
        outputs=args.get("outputs") or {}
        if not os.path.isdir(staging):
            os.makedirs(staging)
        mxd=engine.open_mxd(working)
        try:
            base=engine.safe_filename(args.get("base_name") or "Zagent Map")
            cfg={
                "resolution":int(outputs.get("dpi") or 400),
                "formats":outputs.get("formats") or ["PDF","PNG"],
            }
            exported=engine.export_map(
                mxd,staging,base,cfg,allow_custom_export=True)
        finally:
            try:
                del mxd
            except Exception:
                pass
        artifacts=[]
        for kind,path in sorted(exported.items()):
            artifacts.append({
                "kind":kind,
                "path":path,
                "metadata":{"dpi":int(outputs.get("dpi") or 400)},
            })
        result={"ok":True,"artifacts":artifacts}
    else:
        raise ValueError("UNKNOWN_OPERATION: "+str(op))
    _write(res_path,result)

if __name__=="__main__":
    try:
        main()
    except Exception as exc:
        try:
            _write(sys.argv[2],{
                "ok":False,
                "code":"FILE_WORKER_FAILED",
                "error":repr(exc),
                "traceback":traceback.format_exc(),
            })
        except Exception:
            pass
        raise
