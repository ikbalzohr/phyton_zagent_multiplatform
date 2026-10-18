from .config import AGENT

class SafetyPolicy:
    def status(self):
        return {
            "safe_mode": bool(AGENT.get("safe_mode", True)),
            "allow_live_write": bool(AGENT.get("allow_live_write", False)),
            "allow_save": bool(AGENT.get("allow_save", False)),
            "allow_destructive_operations": bool(AGENT.get("allow_destructive_operations", False)),
            "allow_geoprocessing": bool(AGENT.get("allow_geoprocessing", False)),
            "allow_export": bool(AGENT.get("allow_export", True)),
        }

    def guard(self, kind):
        mapping = {
            "live_write": ("allow_live_write", False),
            "save": ("allow_save", False),
            "destructive": ("allow_destructive_operations", False),
            "geoprocessing": ("allow_geoprocessing", False),
            "export": ("allow_export", True),
        }
        key, default = mapping[kind]
        if not AGENT.get(key, default):
            return {
                "ok": False, "blocked": True,
                "error": f"{kind} operation is blocked by Safe Mode.",
                "safety": self.status()
            }
        return None
