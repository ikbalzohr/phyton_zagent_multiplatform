class UpdateDrainController:
    def __init__(self,preserved_services=None):
        self.draining=False
        self.reason=None
        self.active={}
        self.preserved_services=set(preserved_services or {"zagent_files"})

    def register_active(self,task_id,service_id,effect_class):
        self.active[str(task_id)]={"service_id":str(service_id),"effect_class":str(effect_class)}

    def complete(self,task_id):
        self.active.pop(str(task_id),None)

    def begin(self,reason="update"):
        self.draining=True; self.reason=reason
        return self.snapshot()

    def can_submit(self,service_id,effect_class):
        if not self.draining:
            return True
        if str(service_id) in self.preserved_services:
            return True
        return str(effect_class)=="read"

    def safe_to_restart(self,service_id):
        if str(service_id) in self.preserved_services:
            return False
        for item in self.active.values():
            if item["service_id"]==str(service_id) and item["effect_class"]!="read":
                return False
        return True

    def snapshot(self):
        return {"draining":self.draining,"reason":self.reason,"active":dict(self.active),
                "preserved_services":sorted(self.preserved_services)}
