from enum import Enum
from typing import Any
import hashlib
import json

from pydantic import BaseModel


class AmapAPIType(str, Enum):
    POI_SEARCH = "poi_search"
    POI_DETAIL = "poi_detail"
    GEOCODE = "geocode"
    REVERSE_GEOCODE = "reverse_geocode"


class AmapAPIRequest(BaseModel):
    api_type: AmapAPIType
    params: dict[str, Any]

    def get_cache_key(self) -> str:
        sorted_params = dict(sorted(self.params.items()))
        cache_params = {key: value for key, value in sorted_params.items() if key != "key"}
        key_string = f"{self.api_type.value}:{json.dumps(cache_params, sort_keys=True, ensure_ascii=False)}"
        return hashlib.md5(key_string.encode("utf-8")).hexdigest()


class AmapAPIResponse(BaseModel):
    status: str
    info: str
    data: dict[str, Any]
    count: int | None = None

    def is_success(self) -> bool:
        return self.status == "1"

    def is_quota_exceeded(self) -> bool:
        return "CUQPS_HAS_EXCEEDED_THE_LIMIT" in self.info

