import json

from sqlalchemy import inspect

from app.agent_models import POICategory, AgentState, PathNode, PlayPlan
from app.database import create_sqlite_engine, init_db, session_scope
from app.models import AmapCacheEntry, GeneratedPlayMethod, Post


def test_agent_state_tracks_nodes_and_debug_logs():
    state = AgentState(user_query="上海周末拍照")
    node = PathNode()
    node.pending_plans.append(
        PlayPlan(
            title="静安寺拍照路线",
            description="适合周末晚上轻松拍照",
            keywords=["静安寺", "拍照"],
            category=POICategory.CULTURE,
        )
    )

    node_id = state.add_node(node)
    state.active_node_ids.append(node_id)
    state.add_debug_log("created")

    assert state.get_node(node_id) is node
    assert state.active_node_ids == [node_id]
    assert "created" in state.debug_logs[0]


def test_init_db_creates_agent_support_tables(tmp_path):
    engine = create_sqlite_engine(tmp_path / "test.db")

    init_db(engine)

    table_names = set(inspect(engine).get_table_names())
    assert {"amap_cache_entries", "generated_play_methods"}.issubset(table_names)


def test_generated_play_method_can_reference_post(tmp_path):
    engine = create_sqlite_engine(tmp_path / "test.db")
    init_db(engine)

    with session_scope(engine) as session:
        post = Post(
            title="上海玩法",
            content="正文",
            tags_json="[]",
            images_json="[]",
            source_type="user_generated",
            status="published",
        )
        session.add(post)
        session.flush()
        session.add(
            GeneratedPlayMethod(
                post_id=post.id,
                generation_request_id=None,
                method_json=json.dumps({"title": "路线一"}, ensure_ascii=False),
            )
        )
        session.add(
            AmapCacheEntry(
                cache_key="cache-key",
                api_type="poi_search",
                request_params_json="{}",
                response_data_json="{}",
                cache_status="valid",
            )
        )

    with session_scope(engine) as session:
        assert session.query(GeneratedPlayMethod).count() == 1
        assert session.query(AmapCacheEntry).count() == 1

