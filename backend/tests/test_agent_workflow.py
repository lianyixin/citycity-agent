import asyncio

import pytest

from app.agent_models import DiscoveryRequest
from app.amap_tool import AmapTool
from app.play_discovery_workflow import PlayDiscoveryWorkflow


class FakeAmapClient:
    def __init__(self):
        self.calls = []

    async def poi_search(self, keywords, location=None, city=None, radius=3000, limit=20, use_cache=True):
        self.calls.append({"keywords": keywords, "location": location})
        index = len(self.calls)
        return type(
            "Response",
            (),
            {
                "data": {
                    "pois": [
                        {
                            "id": f"poi-{index}",
                            "name": f"{keywords}好去处",
                            "address": f"上海市静安区测试路{index}号",
                            "location": f"121.4{index},31.2{index}",
                            "type": "风景名胜;公园广场",
                            "biz_ext": {"rating": "4.7", "cost": "88"},
                            "photos": [{"url": "https://example.com/poi.jpg"}],
                        }
                    ]
                }
            },
        )()


class FakeDeepSeekClient:
    async def chat_completion(self, prompt, system_message=None, temperature=0.8, max_tokens=2000):
        if "候选POI" in prompt:
            return '{"selected_poi_id":"poi-1","selected_poi_name":"","estimated_duration":60,"reasoning":"适合当前玩法。"}'
        return (
            '{"reasoning":"测试规划","plans":['
            '{"title":"静安寺拍照路线","description":"适合拍照","keywords":["拍照","地标","静安寺"],'
            '"category":"culture","priority":0.8,"suitable_start_time":"周末晚上","duration_minutes":60},'
            '{"title":"静安寺美食路线","description":"适合吃饭","keywords":["美食","餐厅","静安寺"],'
            '"category":"restaurant","priority":0.8,"suitable_start_time":"周末晚上","duration_minutes":90}'
            "]}"
        )


class SlowFakeAmapClient(FakeAmapClient):
    def __init__(self):
        super().__init__()
        self.active_calls = 0
        self.max_active_calls = 0

    async def poi_search(self, keywords, location=None, city=None, radius=3000, limit=20, use_cache=True):
        self.active_calls += 1
        self.max_active_calls = max(self.max_active_calls, self.active_calls)
        try:
            await asyncio.sleep(0.02)
            return await super().poi_search(keywords, location, city, radius, limit, use_cache)
        finally:
            self.active_calls -= 1


@pytest.mark.asyncio
async def test_workflow_generates_play_methods_with_poi():
    workflow = PlayDiscoveryWorkflow(amap_tool=AmapTool(FakeAmapClient()), deepseek_client=FakeDeepSeekClient())

    response = await workflow.run(
        DiscoveryRequest(
            query="周六晚上想在静安寺附近和朋友拍照吃饭",
            user_location={"lng": 121.45, "lat": 31.22},
            max_results=3,
            preferences={
                "location_text": "静安寺",
                "time_context": "周末晚上",
                "companion_type": "朋友",
                "preference_tags": ["拍照", "美食"],
            },
        )
    )

    assert response.success is True
    assert response.total_count >= 1
    method = response.play_methods[0]
    assert method.steps
    assert method.steps[0].poi.name
    assert method.steps[0].poi.amap_poi_id == "poi-1"


@pytest.mark.asyncio
async def test_workflow_expands_paths_across_multiple_rounds():
    fake_client = FakeAmapClient()
    workflow = PlayDiscoveryWorkflow(amap_tool=AmapTool(fake_client), deepseek_client=FakeDeepSeekClient(), max_rounds=2)

    response = await workflow.run(
        DiscoveryRequest(
            query="周六晚上想在静安寺附近和朋友拍照吃饭",
            user_location={"lng": 121.45, "lat": 31.22},
            max_results=2,
            max_depth=2,
            preferences={
                "location_text": "静安寺",
                "time_context": "周末晚上",
                "companion_type": "朋友",
                "preference_tags": ["拍照", "美食"],
            },
        )
    )

    assert response.success is True
    assert response.play_methods
    assert any(len(method.steps) >= 2 for method in response.play_methods)
    assert len(fake_client.calls) >= 2


@pytest.mark.asyncio
async def test_execute_agent_runs_route_branches_in_parallel():
    fake_client = SlowFakeAmapClient()
    workflow = PlayDiscoveryWorkflow(
        amap_tool=AmapTool(fake_client),
        deepseek_client=FakeDeepSeekClient(),
        max_rounds=1,
    )

    response = await workflow.run(
        DiscoveryRequest(
            query="周末想找拍照和美食路线",
            user_location={"lng": 121.45, "lat": 31.22},
            max_results=2,
            preferences={"location_text": "静安寺", "preference_tags": ["拍照", "美食"]},
        )
    )

    assert response.success is True
    assert fake_client.max_active_calls >= 2

