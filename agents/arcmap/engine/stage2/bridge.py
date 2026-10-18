# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function, unicode_literals
import os

from .engine import (
    discover_data, match_slots, read_json, build_a4, batch_build,
    restore_checkpoint, list_checkpoints, run_gp, open_mxd, a4_check,
    layout_manifest, string_types,
)


def _recipe(v):
    return read_json(v) if isinstance(v,string_types) and os.path.isfile(v) else v


def stage2_discover_data(p):
    return discover_data(p['data_root'],int(p.get('max_items',10000)))


def stage2_preview_match(p):
    d=discover_data(p['data_root'],int(p.get('max_items',10000)))
    r=_recipe(p['recipe']) or {}
    return match_slots(r.get('layers',[]),d,float(p.get('min_score',r.get('min_match_score',0.62))))


def stage2_validate_template(p):
    m=open_mxd(p['template_mxd'])
    try:
        prof=_recipe(p.get('profile')) or {}
        names=set([x['name'] for x in layout_manifest(m)])
        miss=[x for x in prof.get('required_layout_elements',[]) if x not in names]
        a=a4_check(m)
        return {
            'ok':a['ok'] and not miss,
            'a4':a,
            'missing_elements':miss,
            'elements':layout_manifest(m)
        }
    finally:
        del m


def stage2_build_a4(p):
    return build_a4(
        p['template_mxd'],p['data_root'],p['output_dir'],p['recipe'],
        p.get('profile'),p.get('base_name'),p.get('snapshot_root'),
        bool(p.get('save_mxd',True)),p.get('company_name'),p.get('map_type')
    )


def stage2_batch_build(p):
    return batch_build(p.get('job_file') or p)


def stage2_restore_checkpoint(p):
    return restore_checkpoint(p['checkpoint_mxd'],p['target_mxd'])


def stage2_list_checkpoints(p):
    return {'items':list_checkpoints(p['snapshot_root'],p['job_id'])}


def stage2_generic_gp(p):
    return run_gp(p['tool'],p.get('args'),p.get('kwargs'),bool(p.get('allow_destructive',False)))


ACTIONS={
    'stage2_discover_data':stage2_discover_data,
    'stage2_preview_match':stage2_preview_match,
    'stage2_validate_template':stage2_validate_template,
    'stage2_build_a4':stage2_build_a4,
    'stage2_batch_build':stage2_batch_build,
    'stage2_restore_checkpoint':stage2_restore_checkpoint,
    'stage2_list_checkpoints':stage2_list_checkpoints,
    'stage2_generic_gp':stage2_generic_gp,
}


def install_into_registry(reg):
    for k,v in ACTIONS.items():
        reg[k]=v
    return sorted(ACTIONS.keys())


def auto_install(namespace):
    """Legacy compatibility only. Explicit dispatcher integration is preferred."""
    candidates=[]
    for k,v in namespace.items():
        if isinstance(v,dict):
            cc=sum(1 for x in v.values() if callable(x))
            known=any(x in v for x in ('ping','get_status','get_capability_matrix','snapshot_state'))
            if known or cc>=10:
                candidates.append((1 if known else 0,cc,k,v))
    if not candidates:
        return {'ok':False,'reason':'action registry dict not auto-detected'}
    candidates.sort(reverse=True)
    reg=candidates[0][3]
    installed=install_into_registry(reg)
    return {'ok':True,'registry':candidates[0][2],'installed':installed,'count':len(installed)}
