from __future__ import annotations

from copy import deepcopy

from .semantics import infer_administrative_location


class AdministrativeLocationReasoner:
    """
    Resolves administrative hierarchy only from explicit values or supplied
    authoritative feature samples. It never invents a location.
    """

    LEVELS = ("desa", "kecamatan", "kabupaten", "provinsi")

    def resolve(self, explicit=None, samples=None):
        explicit = deepcopy(explicit or {})
        inferred = infer_administrative_location(samples or [])
        resolved = {}
        sources = {}
        for level in self.LEVELS:
            value = explicit.get(level)
            if value not in (None, ""):
                resolved[level] = str(value).strip()
                sources[level] = "explicit"
                continue
            value = (inferred.get("location") or {}).get(level)
            if value not in (None, ""):
                resolved[level] = str(value).strip()
                sources[level] = "dataset_sample"
        return {
            "location": resolved,
            "sources": sources,
            "conflicts": inferred.get("conflicts") or {},
            "complete": all(level in resolved for level in ("desa", "kecamatan", "kabupaten")),
            "missing": [level for level in self.LEVELS if level not in resolved],
        }
