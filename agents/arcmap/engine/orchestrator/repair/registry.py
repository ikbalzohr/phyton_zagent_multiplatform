import hashlib
import json

DEFAULT_REPAIRS={
    "move_element_in_bounds":{"kind":"layout","requires_checkpoint":True},
    "resize_title":{"kind":"layout","requires_checkpoint":True,"min_font_required":True},
    "correct_extent_from_aoi":{"kind":"map","requires_checkpoint":True,"requires_unambiguous_aoi":True},
    "reapply_known_style":{"kind":"style","requires_checkpoint":True,"requires_known_good":True},
    "rebuild_legend":{"kind":"layout","requires_checkpoint":True,"requires_capability":True},
    "reconnect_identified_source":{"kind":"source","requires_checkpoint":True,"requires_exact_candidate":True},
}
FORBIDDEN={"delete_layer_to_hide_error","lower_dpi_without_permission","guess_crs","modify_source_data","relax_gate"}

def fingerprint_issue(issue,action):
    raw=json.dumps({"issue":issue,"action":action},sort_keys=True,separators=(",",":"),default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

class RepairRegistry:
    def __init__(self,repairs=None,max_cycles=3):
        self.repairs=dict(repairs or DEFAULT_REPAIRS); self.max_cycles=max_cycles
    def validate_action(self,action):
        if action in FORBIDDEN: return {"ok":False,"code":"REPAIR_FORBIDDEN"}
        if action not in self.repairs: return {"ok":False,"code":"REPAIR_UNREGISTERED"}
        return {"ok":True,"policy":self.repairs[action]}
