from pydantic import BaseModel, Field


class InteractionRequest(BaseModel):
    user_id: str = Field(min_length=1)


class GenerateRequest(BaseModel):
    user_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    location_text: str | None = None
    location_lat: float | None = None
    location_lng: float | None = None
    time_context: str | None = None
    companion_type: str | None = None
    preference_tags: list[str] = []


class LocationSuggestRequest(BaseModel):
    query: str | None = None
    lat: float | None = None
    lng: float | None = None


class LocationSuggestion(BaseModel):
    name: str
    address: str = ""
    lat: float
    lng: float
    source: str
    amap_id: str | None = None


class ImagePolishRequest(BaseModel):
    image_url: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    post_id: int | None = None


class PostExportRequest(BaseModel):
    image_urls: list[str] | None = None


class SubscriptionCreateRequest(BaseModel):
    pass

