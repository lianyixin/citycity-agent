from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


class User(TimestampMixin, Base):
    """应用用户：id 对应 Logto sub。用于跟踪免费润色额度与订阅状态。"""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    display_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    free_polish_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Subscription(TimestampMixin, Base):
    """用户订阅状态：每月一次支付宝订单激活，30 天有效。"""

    __tablename__ = "subscriptions"
    __table_args__ = (Index("ix_subscriptions_user_status", "user_id", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="inactive", nullable=False)
    # active / inactive / expired
    alipay_trade_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    out_trade_no: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Post(TimestampMixin, Base):
    __tablename__ = "posts"
    __table_args__ = (
        Index("ix_posts_status_created", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tags_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    images_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    cover_image: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_query: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_doc_id: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    author_user_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="published", nullable=False)
    like_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    favorite_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    view_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    interactions: Mapped[list["PostInteraction"]] = relationship(back_populates="post")
    places: Mapped[list["Place"]] = relationship(back_populates="post")


class PostInteraction(TimestampMixin, Base):
    __tablename__ = "post_interactions"
    __table_args__ = (
        UniqueConstraint("post_id", "user_id", name="uq_post_user_interaction"),
        Index("ix_post_interactions_post_id", "post_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    liked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    favorited: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    post: Mapped[Post] = relationship(back_populates="interactions")


class GenerationRequest(TimestampMixin, Base):
    __tablename__ = "generation_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    location_text: Mapped[str | None] = mapped_column(String(120), nullable=True)
    location_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    location_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    time_context: Mapped[str | None] = mapped_column(String(80), nullable=True)
    companion_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    preference_tags_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    result_post_id: Mapped[int | None] = mapped_column(ForeignKey("posts.id"), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class GenerationLog(TimestampMixin, Base):
    __tablename__ = "generation_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    generation_request_id: Mapped[int | None] = mapped_column(ForeignKey("generation_requests.id"), nullable=True)
    stage: Mapped[str] = mapped_column(String(80), nullable=False)
    level: Mapped[str] = mapped_column(String(20), default="info", nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class Place(TimestampMixin, Base):
    __tablename__ = "places"
    __table_args__ = (
        Index("ix_places_post_id", "post_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    image_urls_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    amap_poi_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    step_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    method_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    method_title: Mapped[str | None] = mapped_column(String(200), nullable=True)

    post: Mapped[Post] = relationship(back_populates="places")


class AmapCacheEntry(TimestampMixin, Base):
    __tablename__ = "amap_cache_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cache_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    api_type: Mapped[str] = mapped_column(String(40), nullable=False)
    request_params_json: Mapped[str] = mapped_column(Text, nullable=False)
    response_data_json: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    hit_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_hit_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cache_status: Mapped[str] = mapped_column(String(24), default="valid", nullable=False)


class GeneratedPlayMethod(TimestampMixin, Base):
    __tablename__ = "generated_play_methods"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"), nullable=False)
    generation_request_id: Mapped[int | None] = mapped_column(ForeignKey("generation_requests.id"), nullable=True)
    method_json: Mapped[str] = mapped_column(Text, nullable=False)


class PolishedImage(TimestampMixin, Base):
    """记录每张原图对应的 AI 润色结果，便于回溯与复用，避免重复消耗润色次数。"""

    __tablename__ = "polished_images"
    __table_args__ = (Index("ix_polished_images_post_original", "post_id", "original_url"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[int | None] = mapped_column(ForeignKey("posts.id"), nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    original_url: Mapped[str] = mapped_column(Text, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    polished_url: Mapped[str] = mapped_column(Text, nullable=False)


class ImagePolishRequestRecord(TimestampMixin, Base):
    """记录单次图片润色任务，支持跨页面刷新查询进行中/失败/成功状态。"""

    __tablename__ = "image_polish_requests"
    __table_args__ = (
        Index("ix_image_polish_requests_lookup", "post_id", "original_url", "prompt", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[int | None] = mapped_column(ForeignKey("posts.id"), nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    original_url: Mapped[str] = mapped_column(Text, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    polished_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class SearchLog(TimestampMixin, Base):
    """记录用户搜索查询，便于后续追踪热门搜索词和用户兴趣。"""

    __tablename__ = "search_logs"
    __table_args__ = (Index("ix_search_logs_created_at", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    result_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

