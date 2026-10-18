from .gis import validate_gis
from .layout import validate_layout
from .model import aggregate

class ValidatorRegistry:
    def validate(self,context,layout,profile):
        gis=validate_gis(context,profile.get("gis") or {})
        carto=validate_layout(layout,profile.get("layout") or {})
        return aggregate(list(gis["results"])+list(carto["results"]))
