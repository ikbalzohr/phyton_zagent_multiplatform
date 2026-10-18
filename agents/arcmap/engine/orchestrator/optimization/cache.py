from collections import OrderedDict

class RevisionCache:
    def __init__(self,max_items=128):
        self.max_items=max(1,int(max_items)); self._items=OrderedDict()
    @staticmethod
    def key(device_id,instance_id,document_revision,tool_hash,namespace="context"):
        return (str(namespace),str(device_id),str(instance_id),str(document_revision),str(tool_hash))
    def get(self,key):
        if key not in self._items: return None
        value=self._items.pop(key); self._items[key]=value; return value
    def put(self,key,value):
        if key in self._items: self._items.pop(key)
        self._items[key]=value
        while len(self._items)>self.max_items: self._items.popitem(last=False)
    def invalidate_document(self,device_id,instance_id):
        dead=[k for k in self._items if k[1]==str(device_id) and k[2]==str(instance_id)]
        for k in dead: self._items.pop(k,None)
        return len(dead)
    def clear(self): self._items.clear()
    def __len__(self): return len(self._items)
