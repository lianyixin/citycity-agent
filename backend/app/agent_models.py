from datetime import datetime
from enum import Enum
from typing import Any
import uuid

from pydantic import BaseModel, Field


class TransportMode(str, Enum):
    WALKING = "walking"
    DRIVING = "driving"
    TRANSIT = "transit"
    CYCLING = "cycling"


class POICategory(str, Enum):
    RESTAURANT = "restaurant"
    ENTERTAINMENT = "entertainment"
    SHOPPING = "shopping"
    TOURISM = "tourism"
    SPORTS = "sports"
    CULTURE = "culture"
    NIGHTLIFE = "nightlife"
    OUTDOOR = "outdoor"
    WELLNESS = "wellness"
    OTHER = "other"


class PathNodeStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    ENDED = "ended"
    NO_SUITABLE_POI = "no_suitable_poi"


class POIInfo(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    address: str = ""
    latitude: float = 0.0
    longitude: float = 0.0
    category: POICategory = POICategory.OTHER
    rating: float = 0.0
    price_level: int | None = None
    description: str | None = None
    phone: str | None = None
    opening_hours: str | None = None
    tags: list[str] = Field(default_factory=list)
    source: str | None = None
    photos: list[str] = Field(default_factory=list)
    distance_meters: float | None = None
    cost_per_person: str | None = None
    business_area: str | None = None
    type_code: str | None = None
    amap_poi_id: str | None = None
    cuisine_tags: list[str] = Field(default_factory=list)
    specialty_dishes: list[str] = Field(default_factory=list)
    business_status: str | None = None
    biz_ext: dict[str, Any] | None = None

    @property
    def image_url(self) -> str | None:
        return self.photos[0] if self.photos else None


class PlayStep(BaseModel):
    step_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    step_number: int = Field(ge=1)
    poi: POIInfo
    estimated_start_time: str | None = None
    duration_minutes: int = Field(ge=1)
    distance_from_previous_meters: float | None = None
    transport_duration_minutes: int | None = None
    description: str
    recommendation_reason: str | None = None
    tips: list[str] = Field(default_factory=list)


class PlayMethod(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    description: str
    steps: list[PlayStep]
    total_duration_minutes: int = Field(ge=1)
    estimated_cost: float | None = None
    difficulty_level: int = Field(default=1, ge=1, le=5)
    tags: list[str] = Field(default_factory=list)
    suitable_weather: list[str] = Field(default_factory=list)
    suitable_time: list[str] = Field(default_factory=list)
    rating: float = 0.0
    is_valid: bool = True
    invalid_reason: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class PlayPlan(BaseModel):
    plan_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    description: str = ""
    keywords: list[str]
    priority: float = Field(default=1.0, ge=0.0, le=1.0)
    category: POICategory
    estimated_duration: int | None = None
    duration_minutes: int | None = None
    suitable_start_time: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class PathNode(BaseModel):
    node_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    parent_id: str | None = None
    children_ids: list[str] = Field(default_factory=list)
    status: PathNodeStatus = PathNodeStatus.PENDING
    depth: int = 0
    current_step: PlayStep | None = None
    path_history: list[PlayStep] = Field(default_factory=list)
    pending_plans: list[PlayPlan] = Field(default_factory=list)
    current_plan: PlayPlan | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    path_start_time: datetime | None = None
    path_end_time: datetime | None = None
    total_processing_time_ms: float | None = None

    def add_child(self, child_id: str) -> None:
        if child_id not in self.children_ids:
            self.children_ids.append(child_id)
            self.updated_at = datetime.now()

    def add_step(self, step: PlayStep) -> None:
        self.path_history.append(step)
        self.current_step = step
        self.updated_at = datetime.now()

    def start_path_timing(self) -> None:
        if self.path_start_time is None:
            self.path_start_time = datetime.now()

    def end_path_timing(self) -> None:
        if self.path_start_time is not None and self.path_end_time is None:
            self.path_end_time = datetime.now()
            self.total_processing_time_ms = (
                self.path_end_time - self.path_start_time
            ).total_seconds() * 1000


class DiscoveryRequest(BaseModel):
    query: str
    user_location: dict[str, float] | None = None
    max_results: int = Field(default=10, ge=1, le=50)
    max_depth: int = Field(default=5, ge=1, le=10)
    preferences: dict[str, Any] = Field(default_factory=dict)


class DiscoveryResponse(BaseModel):
    success: bool = True
    message: str = "搜索成功"
    play_methods: list[PlayMethod] = Field(default_factory=list)
    total_count: int = 0
    processing_time: float = 0.0
    user_location_name: str | None = None
    debug_info: dict[str, Any] | None = None


class AgentState(BaseModel):
    user_query: str
    user_location: dict[str, float] | None = None
    user_location_name: str | None = None
    preferences: dict[str, Any] = Field(default_factory=dict)
    path_nodes: dict[str, PathNode] = Field(default_factory=dict)
    active_node_ids: list[str] = Field(default_factory=list)
    completed_paths: list[list[PlayStep]] = Field(default_factory=list)
    max_depth: int = 5
    max_paths: int = 10
    iteration_count: int = 0
    final_play_methods: list[PlayMethod] = Field(default_factory=list)
    debug_logs: list[str] = Field(default_factory=list)

    def add_debug_log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.debug_logs.append(f"[{timestamp}] {message}")

    def get_node(self, node_id: str) -> PathNode | None:
        return self.path_nodes.get(node_id)

    def add_node(self, node: PathNode) -> str:
        self.path_nodes[node.node_id] = node
        return node.node_id

    def complete_path(self, node_id: str) -> None:
        node = self.get_node(node_id)
        if node:
            node.status = PathNodeStatus.ENDED
            node.end_path_timing()
            if node.path_history:
                self.completed_paths.append(node.path_history.copy())

