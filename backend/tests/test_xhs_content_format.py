from app.xhs_content_format import format_xhs_content, is_section_title_line


def test_is_section_title_line_detects_common_patterns():
    assert is_section_title_line("🏯 玩法一：传统文化沉浸游")
    assert is_section_title_line("✨路线一：声音漫步治愈系")
    assert is_section_title_line("【路线一：皮划艇放风局】")
    assert is_section_title_line("【路线一】Sports硬核工业风1小时速拍")
    assert is_section_title_line("🏛️ 玩法二：沉浸古典建筑夜景")
    assert is_section_title_line("🕊️ 玩法三：广场休闲半日游")
    assert is_section_title_line("🏃\u200d♂️ 玩法一：夜跑+观景双享受")
    assert is_section_title_line("☕️ 路线二：石库门咖啡馆氛围感")
    assert is_section_title_line("💡【玩法一：只想安静吃顿好的】")
    assert is_section_title_line("【方案一：老洋房探索】")
    assert is_section_title_line("【方案1】24小时健身房撸铁")
    assert is_section_title_line("方案一：商场橱窗夜拍（P1、P2）")
    assert is_section_title_line("方案A：和平饭店爵士酒吧")
    assert is_section_title_line("🐟【方案一】鱼塘边发呆放空")


def test_is_section_title_line_skips_plan_word_in_body_text():
    assert not is_section_title_line(
        "工作日请了半天假，和对象约在港汇恒隆附近，想找个不累又有趣的下午约会方案。"
    )
    assert not is_section_title_line(
        "想轻松就选方案一或四，想有点烟火气选方案二，需要个安静空间就选方案三。"
    )
    assert not is_section_title_line(
        "我帮你实测了3条不同风格的夜游方案，总有一条适合你～"
    )


def test_is_section_title_line_skips_summary_and_existing_bold():
    assert not is_section_title_line("**路线一：江边治愈系**")
    assert not is_section_title_line("总结一下：想轻松动一动选玩法一")
    assert not is_section_title_line(
        "这三条路线各有侧重，想快速出片选路线一，想自由闲逛选路线二。"
    )


def test_format_xhs_content_bolds_section_titles():
    raw = "导语段落\n\n🏯 玩法一：传统文化沉浸游\n适合带娃\n\n✨路线二：手工体验"
    formatted = format_xhs_content(raw)
    assert "**🏯 玩法一：传统文化沉浸游**" in formatted
    assert "**✨路线二：手工体验**" in formatted
    assert "导语段落" in formatted


def test_format_xhs_content_normalizes_partial_bold():
    raw = "🎨 **路线二：艺术漫步+水上视角**"
    assert format_xhs_content(raw) == "**🎨 路线二：艺术漫步+水上视角**"
