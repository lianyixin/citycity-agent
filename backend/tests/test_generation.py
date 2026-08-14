from fastapi.testclient import TestClient

from app.agent_models import PlayMethod, PlayStep, POICategory, POIInfo
from app.database import create_sqlite_engine, init_db, session_scope
from app.generation import (
    GenerationService,
    _discovery_debug_payload,
    _nearby_intent,
    _to_discovery_request,
    filter_candidate_methods_for_xhs,
)
from app.schemas import GenerateRequest
from app.main import create_app
from app.models import GenerationLog, GenerationRequest, GeneratedPlayMethod, Place, Post
from app.xhs_content import (
    _build_methods_info,
    _collect_candidate_images,
    _methods_by_declared_order,
    _normalize_title,
    _remap_content_p_numbers,
)


async def fake_resolve_location(self, request, generation_request_id):
    return request.model_copy(update={"location_lat": 31.22, "location_lng": 121.45})


async def fake_discover_play_methods(self, request, generation_request_id):
    poi_a = POIInfo(
        name="静安寺测试点",
        address="上海市静安区测试路1号",
        latitude=31.22,
        longitude=121.45,
        category=POICategory.CULTURE,
        rating=4.7,
        amap_poi_id="poi-1",
        photos=["https://example.com/poi.jpg"],
    )
    poi_b = POIInfo(
        name="静安公园测试点",
        address="上海市静安区测试路2号",
        latitude=31.221,
        longitude=121.451,
        category=POICategory.TOURISM,
        rating=4.6,
        amap_poi_id="poi-2",
        photos=["https://example.com/park.jpg"],
    )
    return [
        PlayMethod(
            title="静安寺拍照路线",
            description="包含1个地点的完整体验路线",
            steps=[
                PlayStep(
                    step_number=1,
                    poi=poi_a,
                    duration_minutes=60,
                    description="执行计划：静安寺拍照路线",
                    recommendation_reason="适合拍照。",
                )
            ],
            total_duration_minutes=60,
            tags=["culture"],
            rating=4.7,
        ),
        PlayMethod(
            title="静安公园散步路线",
            description="包含1个地点的完整体验路线",
            steps=[
                PlayStep(
                    step_number=1,
                    poi=poi_b,
                    duration_minutes=45,
                    description="执行计划：静安公园散步路线",
                    recommendation_reason="适合散步。",
                )
            ],
            total_duration_minutes=45,
            tags=["tourism"],
            rating=4.6,
        ),
    ]


async def fake_generate_xhs_card(self, request, methods, generation_request_id):
    return {
        "title": "静安寺玩法",
        "content": "玩法一：静安寺附近适合拍照。\n玩法二：朋友可以顺路吃饭。",
        "tags": ["上海", "静安寺"],
        "images": ["https://example.com/poi.jpg"],
    }


async def fake_build_generated_card_failure(self, generation_request_id, request):
    raise RuntimeError("未找到符合条件的候选路线，请换个关键词或出发地重试")


def test_generate_creates_request_and_user_generated_post(tmp_path):
    engine = create_sqlite_engine(tmp_path / "test.db")
    init_db(engine)
    GenerationService._resolve_location = fake_resolve_location
    GenerationService._discover_play_methods = fake_discover_play_methods
    GenerationService._generate_xhs_card = fake_generate_xhs_card
    client = TestClient(create_app(engine))

    response = client.post(
        "/api/generate",
        json={
            "user_id": "u1",
            "query": "周六晚上想在静安寺附近和朋友拍照吃饭",
            "location_text": "静安寺",
            "time_context": "周末晚上",
            "companion_type": "朋友",
            "preference_tags": ["拍照", "美食", "不累"],
        },
    )

    assert response.status_code == 202
    started = response.json()
    assert started["status"] == "running"
    assert started["generation_request_id"]

    status_resp = client.get(f"/api/generation-requests/{started['generation_request_id']}")
    assert status_resp.status_code == 200
    status_payload = status_resp.json()
    assert status_payload["status"] == "success"
    assert status_payload["post_id"]
    assert len(status_payload["logs"]) >= 1

    post_resp = client.get(f"/api/posts/{status_payload['post_id']}")
    assert post_resp.status_code == 200
    payload = post_resp.json()
    assert payload["source_type"] == "user_generated"
    assert "静安寺" in payload["title"] or "静安寺" in payload["content"]
    assert "上海" in payload["tags"]

    with session_scope(engine) as session:
        assert session.query(Post).count() == 1
        assert session.query(Place).count() >= 1
        assert session.query(GeneratedPlayMethod).count() >= 1
        assert session.query(GenerationLog).count() >= 1
        request = session.query(GenerationRequest).one()
        assert request.status == "success"
        assert request.result_post_id == payload["id"]


def test_generate_failure_marks_request_failed_without_persisting_fallback_post(tmp_path):
    engine = create_sqlite_engine(tmp_path / "test.db")
    init_db(engine)
    GenerationService._build_generated_card = fake_build_generated_card_failure
    service = GenerationService(engine)
    request = GenerateRequest(user_id="u1", query="今天晚上一个人出去玩")
    generation_request_id = service.create_generation_request(request)

    service.run_generation_job(generation_request_id, request)

    with session_scope(engine) as session:
        generation_request = session.get(GenerationRequest, generation_request_id)
        assert generation_request is not None
        assert generation_request.status == "failed"
        assert generation_request.result_post_id is None
        assert "未找到符合条件" in (generation_request.error_message or "")
        assert session.query(Post).count() == 0
        assert session.query(Place).count() == 0
        logs = session.query(GenerationLog).order_by(GenerationLog.id).all()
        assert [log.stage for log in logs] == ["error"]
        assert not any(log.stage == "persist" for log in logs)


def test_generate_rejects_blank_query(tmp_path):
    engine = create_sqlite_engine(tmp_path / "test.db")
    init_db(engine)
    client = TestClient(create_app(engine))

    response = client.post("/api/generate", json={"user_id": "u1", "query": " "})

    assert response.status_code == 400


def test_discovery_request_keeps_departure_location_out_of_query():
    request = GenerateRequest(
        user_id="u1",
        query="周日晚上出去玩，一个人，徐汇区",
        location_text="上海市浦东新区花木街道锦绣雍萃公寓",
        location_lat=31.196463281042615,
        location_lng=121.53178530504829,
    )

    discovery = _to_discovery_request(request)

    assert discovery.query == "周日晚上出去玩，一个人，徐汇区"
    assert "花木" not in discovery.query
    assert discovery.preferences["location_text"] == "上海市浦东新区花木街道锦绣雍萃公寓"
    assert discovery.preferences["target_area"] == "徐汇区"


def test_discovery_debug_payload_keeps_agent_boundary_evidence():
    class Discovery:
        success = True
        message = "玩法发现完成"
        total_count = 0
        processing_time = 1.2
        debug_info = {
            "debug_logs": [
                "PlannerAgent created 3 root plans",
                "ExecuteAgent searching: 上海 夜游, location=121.4737,31.2304, radius=5000",
                "ExecuteAgent no suitable POI for 上海夜游路线",
            ]
        }

    payload = _discovery_debug_payload(Discovery())

    assert payload["total_count"] == 0
    assert payload["debug_log_count"] == 3
    assert payload["debug_logs_tail"][-1] == "ExecuteAgent no suitable POI for 上海夜游路线"


def test_generation_logs_are_sanitized_before_persisting(tmp_path):
    engine = create_sqlite_engine(tmp_path / "test.db")
    init_db(engine)
    service = GenerationService(engine)

    service._log(
        None,
        "agent",
        "[20:38:56] ExecuteAgent searching: 思南公馆 思南书局 老洋房, location=121.53160240931751,31.196531503581, radius=5000",
    )
    service._log(None, "agent", "[20:38:56] workflow:round:1:execute")
    service._log(None, "workflow", "开始 Plan + Execute 玩法发现")
    service._log(None, "agent", "ExecuteAgent selected 思南公馆 for 思南公馆漫步")
    service._log(None, "agent", "PlannerAgent expanded from 思南公馆 to 复兴公园休闲散步")

    with session_scope(engine) as session:
        logs = session.query(GenerationLog).order_by(GenerationLog.id).all()
        assert len(logs) == 1
        assert logs[0].stage == "search"
        assert logs[0].message == "已找到地点：思南公馆（思南公馆漫步）"
        for log in logs:
            assert "ExecuteAgent" not in log.message
            assert "location=" not in log.message
            assert "radius=" not in log.message
            assert "Plan + Execute" not in log.message
            assert "延展出" not in log.message
            assert "正在查找" not in log.message
            assert "玩法发现" not in log.message
            assert "路线探索" not in log.message


def test_filter_candidate_methods_removes_unavailable_and_duplicates():
    def method(title: str, poi_name: str, rating: float, category: POICategory = POICategory.CULTURE):
        poi = POIInfo(
            name=poi_name,
            address="上海市测试路",
            latitude=31.2,
            longitude=121.4,
            category=category,
            rating=rating,
            amap_poi_id=poi_name,
        )
        return PlayMethod(
            title=title,
            description="测试路线",
            steps=[
                PlayStep(
                    step_number=1,
                    poi=poi,
                    duration_minutes=60,
                    description=f"执行计划：{title}",
                )
            ],
            total_duration_minutes=60,
            tags=[category.value],
            rating=rating,
        )

    candidates = [
        method("艺术路线", "刘海粟美术馆", 4.8),
        method("艺术路线", "刘海粟美术馆", 4.6),
        method("关闭路线", "上海儿童博物馆(暂停开放)", 4.9),
        method("低分路线", "普通小店", 3.2),
        method("美食路线", "长宁来福士", 4.7, POICategory.SHOPPING),
    ]

    result = filter_candidate_methods_for_xhs(candidates, limit=8, min_candidates=2)

    assert [item.title for item in result] == ["艺术路线", "美食路线"]


def test_filter_candidate_methods_backfills_when_strict_candidates_are_few():
    def method(title: str, rating: float):
        poi = POIInfo(
            name=title,
            address="上海市测试路",
            latitude=31.2,
            longitude=121.4,
            category=POICategory.CULTURE,
            rating=rating,
            amap_poi_id=title,
        )
        return PlayMethod(
            title=title,
            description="测试路线",
            steps=[
                PlayStep(
                    step_number=1,
                    poi=poi,
                    duration_minutes=60,
                    description=f"执行计划：{title}",
                )
            ],
            total_duration_minutes=60,
            tags=[POICategory.CULTURE.value],
            rating=rating,
        )

    candidates = [
        method("高分路线", 4.8),
        method("放宽路线A", 3.6),
        method("放宽路线B", 3.5),
        method("兜底路线", 3.2),
    ]

    result = filter_candidate_methods_for_xhs(candidates, limit=4, min_candidates=3)

    assert [item.title for item in result] == ["高分路线", "放宽路线A", "放宽路线B"]


def test_xhs_content_uses_two_images_per_place_and_hides_candidate_indexes():
    def poi(name: str, photos: list[str]):
        return POIInfo(
            name=name,
            address="上海市测试路",
            latitude=31.2,
            longitude=121.4,
            category=POICategory.CULTURE,
            rating=4.8,
            photos=photos,
            amap_poi_id=name,
        )

    method = PlayMethod(
        title="亲子路线（方案5）",
        description="适合亲子出游",
        steps=[
            PlayStep(
                step_number=1,
                poi=poi("上海动物园", ["zoo-1.jpg", "zoo-2.jpg", "zoo-3.jpg"]),
                duration_minutes=120,
                description="看动物",
                recommendation_reason="动物园互动丰富。",
            ),
            PlayStep(
                step_number=2,
                poi=poi("亲子乐园", ["play-1.jpg", "play-2.jpg"]),
                duration_minutes=90,
                description="室内玩耍",
            ),
        ],
        total_duration_minutes=210,
        tags=["restaurant", "culture", "tourism"],
        rating=4.8,
    )

    images = _collect_candidate_images([method])
    methods_info = _build_methods_info([method], images)
    assert images == ["zoo-1.jpg", "zoo-2.jpg", "play-1.jpg", "play-2.jpg"]
    assert "[图片P1/P2] 上海动物园" in methods_info
    assert "[图片P3/P4] 亲子乐园" in methods_info
    assert "restaurant" not in methods_info
    assert "culture" not in methods_info
    assert "类型:" not in methods_info


def test_declared_route_order_can_reorder_selected_method_steps():
    first = POIInfo(
        name="小菜园新徽菜",
        address="上海市测试路",
        latitude=31.2,
        longitude=121.4,
        category=POICategory.RESTAURANT,
    )
    second = POIInfo(
        name="meland club亲子乐园",
        address="上海市测试路",
        latitude=31.2,
        longitude=121.4,
        category=POICategory.ENTERTAINMENT,
    )
    method = PlayMethod(
        title="亲子室内玩法",
        description="自由文案",
        steps=[
            PlayStep(step_number=1, poi=first, duration_minutes=60, description="午餐"),
            PlayStep(step_number=2, poi=second, duration_minutes=90, description="玩耍"),
        ],
        total_duration_minutes=150,
    )

    selected = _methods_by_declared_order(
        [method],
        [{"method_index": 1, "poi_names": ["meland club亲子乐园", "小菜园新徽菜"]}],
    )

    assert [step.poi.name for step in selected[0].steps] == ["meland club亲子乐园", "小菜园新徽菜"]
    assert [step.step_number for step in selected[0].steps] == [1, 2]


def test_nearby_intent_detected_from_query():
    assert _nearby_intent("附近晚上好玩的")
    assert _nearby_intent("周边有什么好吃的")
    assert not _nearby_intent("明天去长宁玩")


def test_xhs_title_normalizer_rewrites_dull_short_titles():
    title = _normalize_title("交大好友一日游", "周末和好友去交大附近聚会")

    assert title != "交大好友一日游"
    assert "聚会攻略" in title


def test_selected_routes_renumber_images_from_p1():
    def poi(name: str, photos: list[str]):
        return POIInfo(
            name=name,
            address="上海市测试路",
            latitude=31.2,
            longitude=121.4,
            category=POICategory.CULTURE,
            rating=4.8,
            photos=photos,
            amap_poi_id=name,
        )

    def method(title: str, poi_name: str, photos: list[str]):
        return PlayMethod(
            title=title,
            description="测试路线",
            steps=[
                PlayStep(
                    step_number=1,
                    poi=poi(poi_name, photos),
                    duration_minutes=60,
                    description=f"执行计划：{title}",
                )
            ],
            total_duration_minutes=60,
            tags=[POICategory.CULTURE.value],
            rating=4.8,
        )

    all_methods = [
        method("路线1", "地点1", ["m1-a.jpg", "m1-b.jpg"]),
        method("路线2", "地点2", ["m2-a.jpg", "m2-b.jpg"]),
        method("路线3", "地点3", ["m3-a.jpg", "m3-b.jpg"]),
    ]
    all_images = _collect_candidate_images(all_methods)
    assert len(all_images) == 6
    assert _build_methods_info(all_methods, all_images).count("[图片P5/P6]") == 1

    selected = [all_methods[1], all_methods[2]]
    selected_images = _collect_candidate_images(selected)
    selected_info = _build_methods_info(selected, selected_images)

    assert selected_images == ["m2-a.jpg", "m2-b.jpg", "m3-a.jpg", "m3-b.jpg"]
    assert "[图片P1/P2] 地点2" in selected_info
    assert "[图片P3/P4] 地点3" in selected_info
    assert "P5" not in selected_info
    assert "P6" not in selected_info


def test_remap_content_p_numbers_maps_global_to_selected_order():
    all_images = [f"img-{index}.jpg" for index in range(1, 19)]
    selected_images = ["img-9.jpg", "img-10.jpg", "img-17.jpg", "img-18.jpg"]
    content = "先去海底捞（P9/P10），再去桌游吧（P17/P18）"

    remapped = _remap_content_p_numbers(content, all_images, selected_images)

    assert remapped == "先去海底捞（P1/P2），再去桌游吧（P3/P4）"
