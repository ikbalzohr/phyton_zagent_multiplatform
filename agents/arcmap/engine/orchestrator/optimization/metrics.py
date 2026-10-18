COMPONENTS=("queue","context","reasoning","dispatch_ipc","gis","validation","render","artifact_transfer","publish")
def timing_breakdown(values):
    data={k:float((values or {}).get(k,0.0)) for k in COMPONENTS}
    data["total"]=sum(data.values())
    data["dominant"]=max(COMPONENTS,key=lambda k:data[k]) if data["total"] else None
    return data

def choose_ipc_mode(capabilities,requested="event"):
    caps=set(capabilities or [])
    if requested=="event" and "ipc_event_verified" in caps:
        return "event"
    return "file_poll"
