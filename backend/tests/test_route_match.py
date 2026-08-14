from app.route_match import (
    match_routes_to_content,
    parse_content_sections,
    poi_mentioned_in_text,
    sort_places_by_section_text,
)


POST_72_CONTENT = """打工人的工作日午后，是不是总想溜出来透透气？🌿 这次我在衡山路/复兴西路附近实测了3条适合上班族摸鱼半日游的路线，有放空的、有文艺的、有热闹的，总有一条适合你。

**【路线一：天台写生+梧桐骑行】适合想安静放空、顺便打卡的上班族**
行程顺序：LAGOM Cafe&Bar(静安星座店)（P1、P2） -> 集雅GATHERING咖啡(武康路店)（P3、P4）
下午2点半先冲到LAGOM的天台（P1、P2），俯瞰梧桐树冠，带个本子写生或发呆都超治愈，人均¥105，待2小时。然后骑车2公里到武康路的集雅（P3、P4），中式美学空间里喝杯咖啡（人均¥38），歇半小时再回去，完美衔接下班。

**【路线二：漫步历史+梧桐光影】适合想慢慢逛、感受法租界氛围的上班族**
行程顺序：柯灵故居（P5、P6） -> 集雅GATHERING咖啡(武康路店)（P3、P4）
下午2点从复兴西路的柯灵故居（P5、P6）开始，40分钟逛完老洋房名人故居，感受历史底蕴。然后走500米到集雅（P3、P4），坐在梧桐光影里喝下午茶，人均¥38，45分钟就能满血复活。

**【路线三：艺术画廊+街巷漫步】适合想轻松遛弯、拍拍照的上班族**
行程顺序：大美术馆 BigGallery(武康大楼店)（P7、P8） -> 武康路历史文化名街（P9）
下午2点先到武康大楼里的大美术馆（P7、P8），看个迷你展览（45分钟），然后溜达到武康路（P9）随便走走，1小时逛完老洋房街区，全程不累，适合下班前透口气。

这三条路线都不超过3小时，工作日下午溜出来完全来得及。想放空选路线一，想文化选路线二，想轻松选路线三。觉得有用的话，记得点左上角头像关注我，解锁更多上海有趣玩法！
"""

POST_72_PLACES = [
    {"name": "JZ Club(上海店)", "lat": 31.2, "lng": 121.4, "method_order": 1, "method_title": "Entertainment主题体验"},
    {"name": "大美术馆 BigGallery(武康大楼店)", "lat": 31.2, "lng": 121.4, "method_order": 2, "method_title": "Tourism+Culture组合体验"},
    {"name": "武康路历史文化名街", "lat": 31.2, "lng": 121.4, "method_order": 2, "method_title": "Tourism+Culture组合体验"},
    {"name": "LAGOM Cafe&Bar(静安星座店)", "lat": 31.2, "lng": 121.4, "method_order": 3, "method_title": "Restaurant+Shopping组合体验"},
    {"name": "集雅GATHERING咖啡(武康路店)", "lat": 31.2, "lng": 121.4, "method_order": 3, "method_title": "Restaurant+Shopping组合体验"},
    {"name": "柯灵故居", "lat": 31.2, "lng": 121.4, "method_order": 4, "method_title": "Shopping+Other组合体验"},
    {"name": "集雅GATHERING咖啡(武康路店)", "lat": 31.2, "lng": 121.4, "method_order": 4, "method_title": "Shopping+Other组合体验"},
]


def test_parse_content_sections_post_72():
    sections = parse_content_sections(POST_72_CONTENT)
    assert len(sections) == 3
    assert sections[0].label == "路线一"
    assert sections[0].title == "天台写生+梧桐骑行"
    assert sections[2].label == "路线三"
    assert "大美术馆" in sections[2].text


def test_poi_mentioned_in_text_handles_parentheses():
    text = "行程顺序：LAGOM Cafe&Bar(静安星座店)（P1、P2）"
    assert poi_mentioned_in_text("LAGOM Cafe&Bar(静安星座店)", text)


def test_match_routes_filters_extra_methods_and_aligns_order():
    groups = match_routes_to_content(POST_72_CONTENT, POST_72_PLACES)
    assert len(groups) == 3
    assert groups[0].section_label == "路线一"
    assert groups[0].title == "天台写生+梧桐骑行"
    assert {p["name"] for p in groups[0].places} == {
        "LAGOM Cafe&Bar(静安星座店)",
        "集雅GATHERING咖啡(武康路店)",
    }
    assert groups[1].section_label == "路线二"
    assert "柯灵故居" in {p["name"] for p in groups[1].places}
    assert groups[2].section_label == "路线三"
    assert "大美术馆 BigGallery(武康大楼店)" in {p["name"] for p in groups[2].places}
    assert all("JZ Club" not in p["name"] for g in groups for p in g.places)


def test_match_routes_plan_bracket_title():
    content = "【方案一】鱼塘公园发呆放空🐟\n先去鱼塘公园坐坐。\n\n【方案二】某某菜场小吃猎奇🥟\n去菜场逛逛。"
    places = [
        {"name": "鱼塘公园", "lat": 1.0, "lng": 1.0, "method_order": 1, "method_title": "Tourism主题体验"},
        {"name": "某某菜场", "lat": 1.0, "lng": 1.0, "method_order": 2, "method_title": "Restaurant主题体验"},
    ]
    groups = match_routes_to_content(content, places)
    assert len(groups) == 2
    assert groups[0].title == "鱼塘公园发呆放空"
    assert groups[1].title == "某某菜场小吃猎奇"


def test_sort_places_by_section_text_follows_numbered_markers():
    section_text = "1️⃣宋庆龄故居（P1-P2）+2️⃣衡山公园（P3-P4）"
    places = [
        {"name": "衡山公园", "step_order": 2},
        {"name": "上海宋庆龄故居纪念馆", "step_order": 1},
    ]
    ordered = sort_places_by_section_text(places, section_text)
    assert [p["name"] for p in ordered] == ["上海宋庆龄故居纪念馆", "衡山公园"]


def test_sort_places_by_section_text_follows_content_order():
    section_text = (
        "行程顺序：柯灵故居（P5、P6） -> 集雅GATHERING咖啡(武康路店)（P3、P4）\n"
        "下午2点从复兴西路的柯灵故居开始。"
    )
    places = [
        {"name": "集雅GATHERING咖啡(武康路店)", "step_order": 2},
        {"name": "柯灵故居", "step_order": 1},
    ]
    ordered = sort_places_by_section_text(places, section_text)
    assert [p["name"] for p in ordered] == ["柯灵故居", "集雅GATHERING咖啡(武康路店)"]


def test_match_routes_reorders_places_within_section():
    content = """**【路线一：A到B】**
行程顺序：大美术馆 BigGallery(武康大楼店)（P7、P8） -> 武康路历史文化名街（P9）
P9 武康路历史文化名街

**【路线二：B到A】**
行程顺序：柯灵故居（P5、P6） -> 集雅GATHERING咖啡(武康路店)（P3、P4）"""
    places = [
        {"name": "武康路历史文化名街", "lat": 1.0, "lng": 1.0, "method_order": 1, "step_order": 2},
        {"name": "大美术馆 BigGallery(武康大楼店)", "lat": 1.0, "lng": 1.0, "method_order": 1, "step_order": 1},
        {"name": "集雅GATHERING咖啡(武康路店)", "lat": 1.0, "lng": 1.0, "method_order": 2, "step_order": 2},
        {"name": "柯灵故居", "lat": 1.0, "lng": 1.0, "method_order": 2, "step_order": 1},
    ]
    groups = match_routes_to_content(content, places)
    assert [p["name"] for p in groups[0].places] == [
        "大美术馆 BigGallery(武康大楼店)",
        "武康路历史文化名街",
    ]
    assert [p["name"] for p in groups[1].places] == [
        "柯灵故居",
        "集雅GATHERING咖啡(武康路店)",
    ]


def test_match_routes_heyday_alias():
    content = """**🎵 玩法一：爵士乐+夜游武康路**
P1-P2 Heyday Jazz Bar
P3-P4 武康路历史文化名街

**🍶 玩法二：纯享爵士乐之夜**
P1-P2 Heyday Jazz Bar

**🍱 玩法三：爵士乐+深夜居酒屋**
P1-P2 Heyday Jazz Bar
P5-P6 Akada赤田居酒屋"""
    places = [
        {"name": "Heyday Jazz Bar", "lat": 1.0, "lng": 1.0, "method_order": 1, "method_title": "x"},
        {"name": "武康路历史文化名街", "lat": 1.0, "lng": 1.0, "method_order": 1, "method_title": "x"},
        {"name": "Heyday Jazz Bar", "lat": 1.0, "lng": 1.0, "method_order": 2, "method_title": "x"},
        {"name": "Heyday Jazz Bar", "lat": 1.0, "lng": 1.0, "method_order": 3, "method_title": "x"},
        {"name": "Akada赤田居酒屋", "lat": 1.0, "lng": 1.0, "method_order": 3, "method_title": "x"},
    ]
    groups = match_routes_to_content(content, places)
    assert len(groups) == 3
    assert groups[1].title == "纯享爵士乐之夜"
    assert len(groups[1].places) == 1


def test_match_routes_uses_section_poi_mentions_not_raw_method_groups():
    content = """☕️【方案1】深夜咖啡时光（2小时）
P1-P2 老麦咖啡馆
📍武康路439号（交大地铁站步行410米）

🍽️🎵【方案2】浪漫晚餐+爵士微醺（4小时15分）
P3-P4 Coffee Tree
📍武康路376号武康庭1层

P5-P6 Heyday Jazz Bar
📍泰安路50号（步行2分钟）

📸🍸【方案3】街拍+现场爵士（4小时15分）
P7-P8 武康路历史文化名街
📍武康路与湖南路交叉口

P9 JZ Club
📍衡山路8号（步行8分钟）"""
    places = [
        {"name": "武康路历史文化名街", "lat": 1.0, "lng": 1.0, "method_order": 1, "step_order": 1},
        {"name": "JZ Club(上海店)", "lat": 1.0, "lng": 1.0, "method_order": 1, "step_order": 2},
        {"name": "Coffee Tree(武康路店)", "lat": 1.0, "lng": 1.0, "method_order": 2, "step_order": 1},
        {"name": "Heyday Jazz Bar", "lat": 1.0, "lng": 1.0, "method_order": 2, "step_order": 2},
        {"name": "老麦咖啡馆(武康路店)", "lat": 1.0, "lng": 1.0, "method_order": 3, "step_order": 1},
    ]

    groups = match_routes_to_content(content, places)

    assert [p["name"] for p in groups[0].places] == ["老麦咖啡馆(武康路店)"]
    assert [p["name"] for p in groups[1].places] == [
        "Coffee Tree(武康路店)",
        "Heyday Jazz Bar",
    ]
    assert [p["name"] for p in groups[2].places] == [
        "武康路历史文化名街",
        "JZ Club(上海店)",
    ]


def test_match_routes_ignores_places_after_tips_marker():
    content = """【方案一】咖啡放空
P1 老麦咖啡馆
📍武康路439号

💡小贴士：如果时间还多，可以顺路看看武康路历史文化名街和JZ Club。"""
    places = [
        {"name": "老麦咖啡馆(武康路店)", "lat": 1.0, "lng": 1.0, "method_order": 1},
        {"name": "武康路历史文化名街", "lat": 1.0, "lng": 1.0, "method_order": 2},
        {"name": "JZ Club(上海店)", "lat": 1.0, "lng": 1.0, "method_order": 3},
    ]

    groups = match_routes_to_content(content, places)

    assert len(groups) == 1
    assert [p["name"] for p in groups[0].places] == ["老麦咖啡馆(武康路店)"]


def test_match_routes_detects_short_brand_name_in_section():
    content = """🍽️ 方案一：纯享美食路线（1.5h）
懒人福音！直接冲【渔市小神鲜海鲜餐厅】（P1-P2）

🛍️ 方案二：美食+文艺半日游（2.75h）
10:30-12:00 渔市小神鲜吃早午餐（P1-P2）
12:30-13:30 步行181米到大隐书局（P3-P4）"""
    places = [
        {"name": "渔市小神鲜海鲜餐厅(创智天地广场店)", "lat": 1.0, "lng": 1.0, "method_order": 1},
        {"name": "大隐书局(大学路店)", "lat": 1.0, "lng": 1.0, "method_order": 2},
    ]

    groups = match_routes_to_content(content, places)

    assert [p["name"] for p in groups[1].places] == [
        "渔市小神鲜海鲜餐厅(创智天地广场店)",
        "大隐书局(大学路店)",
    ]


def test_match_routes_extracts_poi_from_pin_address_lines():
    content = """【方案一：老洋房探索】
📍上海宋庆龄故居纪念馆（P1-P2）

【方案三：纯自然体验】
📍衡山公园（P3-P4）"""
    places = [
        {"name": "上海宋庆龄故居纪念馆", "lat": 1.0, "lng": 1.0, "amap_poi_id": "a"},
        {"name": "衡山公园", "lat": 1.0, "lng": 1.0, "amap_poi_id": "b"},
    ]

    groups = match_routes_to_content(content, places)

    assert [p["name"] for p in groups[0].places] == ["上海宋庆龄故居纪念馆"]
    assert [p["name"] for p in groups[1].places] == ["衡山公园"]


def test_match_routes_ikea_short_name_before_p_marker():
    content = """【玩法一：温馨家居共创】
适合想一起构想未来、喜欢慢节奏的情侣。
直接去宜家徐汇商场（P1,P2）！别只当它是卖场。

【玩法二：轻松解谜+文艺淘碟】
路线：屋有岛密室（P5,P6） → BOOCUP唱片店（P7,P8）"""
    places = [
        {"name": "IKEA宜家家居(上海徐汇商场)", "lat": 1.0, "lng": 1.0, "amap_poi_id": "1"},
        {"name": "屋有岛沉浸游戏体验馆(徐家汇旗舰店)", "lat": 1.0, "lng": 1.0, "amap_poi_id": "2"},
        {"name": "BOOCUP浣熊唱片店", "lat": 1.0, "lng": 1.0, "amap_poi_id": "3"},
    ]

    groups = match_routes_to_content(content, places)

    assert groups[0].section_label == "玩法一"
    assert [p["name"] for p in groups[0].places] == ["IKEA宜家家居(上海徐汇商场)"]
    assert {p["name"] for p in groups[1].places} == {
        "屋有岛沉浸游戏体验馆(徐家汇旗舰店)",
        "BOOCUP浣熊唱片店",
    }


def test_match_routes_fuji_xspace_short_name_with_slash_p_markers():
    content = """✨ 玩法二：文艺慢拍，逛吃拍照两不误
适合爱拍照、喜欢胶片复古感的情侣
路线：富士影像空间（P5/P6）→ 一尺花园（P7/P8）。"""
    places = [
        {"name": "富士胶片影像空间X-SPACE", "lat": 1.0, "lng": 1.0, "amap_poi_id": "fuji"},
        {"name": "一尺花园(静安花房店)", "lat": 1.0, "lng": 1.0, "amap_poi_id": "yichi"},
    ]

    groups = match_routes_to_content(content, places)

    assert len(groups) == 1
    assert groups[0].section_label == "玩法二"
    assert [p["name"] for p in groups[0].places] == [
        "富士胶片影像空间X-SPACE",
        "一尺花园(静安花房店)",
    ]


def test_match_routes_uses_section_title_for_p_brand_names():
    content = """**🎨 方案一：乐玩陶艺DIY**
P1-P2这家陶艺工坊在中山公园附近，从静安过去超方便！
📍定西路1277号长峰大厦13层
💡推荐理由：2小时沉浸式手作体验，团队一起做陶艺超治愈！

**🥗 方案二：GREEN & SAFE早午餐**
P3-P4这家有机西餐厅在古北高岛屋，环境绝绝子！
📍虹桥路2436号高岛屋4F
💡推荐理由：4.4分有机餐厅，早午餐选择超多！

**🍵 方案三：隐溪茶馆茶道体验**
P5-P6这家日式茶馆在黄金城道，评分高达4.7！
📍黄金城道668号
💡推荐理由：古北必打卡茶馆！团队一起体验茶道文化。"""
    places = [
        {"name": "乐玩陶艺(中山公园店)", "lat": 1.0, "lng": 1.0, "amap_poi_id": "1"},
        {"name": "GREEN & SAFE(上海高岛屋百货店)", "lat": 1.0, "lng": 1.0, "amap_poi_id": "2"},
        {"name": "隐溪茶馆(黄金城道)", "lat": 1.0, "lng": 1.0, "amap_poi_id": "3"},
    ]

    groups = match_routes_to_content(content, places)

    assert len(groups) == 3
    assert [p["name"] for p in groups[0].places] == ["乐玩陶艺(中山公园店)"]
    assert [p["name"] for p in groups[1].places] == ["GREEN & SAFE(上海高岛屋百货店)"]
    assert [p["name"] for p in groups[2].places] == ["隐溪茶馆(黄金城道)"]


def test_match_routes_single_p_marker_with_time_prefix():
    content = """**方案三：公园写生**
9点半去徐家汇公园（P9）写生，人少景美，还有黑天鹅！带个本子就能度过悠闲上午～
📍徐家汇公园：肇嘉浜路986号"""
    places = [
        {"name": "徐家汇公园", "lat": 1.0, "lng": 1.0, "amap_poi_id": "park"},
        {"name": "柯灵故居", "lat": 1.0, "lng": 1.0, "amap_poi_id": "other"},
    ]

    groups = match_routes_to_content(content, places)

    assert len(groups) == 1
    assert groups[0].section_label == "方案三"
    assert [p["name"] for p in groups[0].places] == ["徐家汇公园"]
