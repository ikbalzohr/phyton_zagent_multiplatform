import hashlib
import json
import re

_VERSION=re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")

def _canonical(v):
    return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":"),default=str)

class RecipeLibrary:
    def __init__(self,allowed_actions):
        self.allowed_actions=set(allowed_actions or [])
        self._recipes={}
    def register(self,name,version,recipe):
        if not name or not _VERSION.match(str(version)):
            raise ValueError("INVALID_RECIPE_ID")
        data=dict(recipe or {})
        actions=list(data.get("actions") or [])
        if not actions:
            raise ValueError("RECIPE_ACTIONS_REQUIRED")
        unknown=[a.get("action") for a in actions if a.get("action") not in self.allowed_actions]
        if unknown:
            raise ValueError("RECIPE_ACTION_FORBIDDEN:"+",".join(str(x) for x in unknown))
        if any("code" in a or "script" in a or "eval" in a for a in actions):
            raise ValueError("ARBITRARY_CODE_FORBIDDEN")
        key=(str(name),str(version))
        if key in self._recipes:
            raise ValueError("RECIPE_VERSION_EXISTS")
        content_hash=hashlib.sha256(_canonical(data).encode("utf-8")).hexdigest()
        entry={"name":name,"version":version,"recipe":data,"sha256":content_hash}
        self._recipes[key]=entry
        return dict(entry)
    def get(self,name,version):
        entry=self._recipes.get((str(name),str(version)))
        return dict(entry) if entry else None
    def versions(self,name):
        return sorted(v for n,v in self._recipes if n==str(name))
