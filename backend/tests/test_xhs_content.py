import json

import pytest

from app.agent_models import PlayMethod, PlayStep, POICategory, POIInfo
from app.xhs_content import XHSContentGenerator


class FakeDeepSeekClient:
    def __init__(self):
        self.prompts: list[str] = []
        self.call_count = 0

    async def chat_completion(self, prompt, system_message=None, temperature=0.8, max_tokens=2000):
        self.prompts.append(prompt)
        self.call_count += 1
        if self.call_count == 1:
            return json.dumps(
                {
                    "selected_method_indexes": [2],
                    "selected_routes": [{"method_index": 1, "poi_names": ["静安公园"]}],
                },
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "title": "静安寺夜拍攻略｜朋友聚会好去处",
                "content": "周末晚上想拍照吃饭，可以从静安公园（P1）开始。觉得有用的话，点左上角头像关注更多上海有趣玩法。",
                "tags": ["上海", "静安寺", "拍照", "美食"],
            },
            ensure_ascii=False,
        )


class FakeSingleDeepSeekClient:
    def __init__(self):
        self.last_prompt = ""

    async def chat_completion(self, prompt, system_message=None, temperature=0.8, max_tokens=2000):
        self.last_prompt = prompt
        return json.dumps(
            {
                "title": "静安寺夜拍攻略｜朋友聚会好去处",
                "content": "周末晚上想拍照吃饭，可以从静安寺附近开始。这里适合朋友慢慢逛，先拍照再吃饭，节奏不累。觉得有用的话，点左上角头像关注更多上海有趣玩法。",
                "tags": ["上海", "静安寺", "拍照", "美食"],
            },
            ensure_ascii=False,
        )


@pytest.mark.asyncio
async def test_xhs_generator_builds_content_from_play_methods():
    method = PlayMethod(
        title="静安寺拍照路线",
        description="包含1个地点",
        total_duration_minutes=75,
        rating=4.7,
        tags=["拍照"],
        steps=[
            PlayStep(
                step_number=1,
                poi=POIInfo(
                    name="静安公园",
                    address="南京西路",
                    latitude=31.22,
                    longitude=121.45,
                    category=POICategory.TOURISM,
                    rating=4.7,
                    photos=["https://example.com/a.jpg"],
                ),
                duration_minutes=75,
                description="拍照散步",
                recommendation_reason="高德评分较高",
            )
        ],
    )
    fake = FakeSingleDeepSeekClient()

    result = await XHSContentGenerator(fake).generate("静安寺附近拍照", [method], "静安寺")

    assert result["title"] == "静安寺夜拍攻略｜朋友聚会好去处"
    assert result["images"] == ["https://example.com/a.jpg"]
    assert "静安公园" in fake.last_prompt


@pytest.mark.asyncio
async def test_multi_route_note_uses_selected_images_numbering():
    def method(title: str, poi_name: str, photo: str):
        return PlayMethod(
            title=title,
            description="测试",
            total_duration_minutes=60,
            rating=4.7,
            tags=["拍照"],
            steps=[
                PlayStep(
                    step_number=1,
                    poi=POIInfo(
                        name=poi_name,
                        address="南京西路",
                        latitude=31.22,
                        longitude=121.45,
                        category=POICategory.TOURISM,
                        rating=4.7,
                        photos=[photo],
                    ),
                    duration_minutes=60,
                    description="散步",
                )
            ],
        )

    methods = [
        method("路线1", "地点1", "https://example.com/1.jpg"),
        method("路线2", "静安公园", "https://example.com/a.jpg"),
    ]
    fake = FakeDeepSeekClient()

    result = await XHSContentGenerator(fake).generate_multi_route_note("静安寺附近拍照", methods, "静安寺")

    assert fake.call_count == 2
    assert result["images"] == ["https://example.com/a.jpg"]
    assert "P1" in fake.prompts[1]
    assert "P2" not in fake.prompts[1]
    assert "P1" in result["content"]
    assert result["selected_method_indexes"] == [2]

