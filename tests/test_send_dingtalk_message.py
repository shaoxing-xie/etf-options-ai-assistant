"""钉钉发送工具：分片与超长自动多条（无网络）。"""

from __future__ import annotations

from plugins.notification.send_dingtalk_message import (
    DEFAULT_DINGTALK_MAX_CHARS_HARD_CEILING,
    DINGTALK_CUSTOM_ROBOT_TEXT_SAFE_MAX,
    _dingtalk_max_chars_hard_ceiling,
    _resolve_max_chars_per_message,
    _rewind_cut_for_dangling_conjunction,
    _rewind_cut_for_incomplete_number,
    _soft_break_before,
    _split_markdown_for_dingtalk,
    _split_oversize_section,
    tool_send_dingtalk_message,
)


def test_split_markdown_respects_max_chars() -> None:
    body = "## A\n" + ("x\n" * 900)
    parts = _split_markdown_for_dingtalk(body, max_chars=400)
    assert len(parts) >= 2
    assert all(len(p) <= 450 for p in parts)


def test_long_body_auto_multipart_dry_run_without_split_flag() -> None:
    """超过安全长度时即使 split_markdown_sections=False 也应走 multipart dry-run。"""
    long_body = "监控\n" + ("行\n" * 1200)
    r = tool_send_dingtalk_message(
        message=long_body,
        title="标题",
        webhook_url="https://example.com/hook",
        mode="test",
        split_markdown_sections=False,
        max_chars_per_message=800,
    )
    assert r.get("success") is True
    data = r.get("data") or {}
    assert data.get("parts", 0) >= 2
    assert isinstance(data.get("part_lengths"), list)
    assert len(data.get("part_lengths") or []) == data.get("parts")
    assert data.get("auto_split") is True
    assert data.get("split_markdown_sections") is False


def test_short_body_single_dry_run() -> None:
    r = tool_send_dingtalk_message(
        message="短讯",
        webhook_url="https://example.com/hook",
        mode="test",
        split_markdown_sections=False,
    )
    assert r.get("success") is True
    data = r.get("data") or {}
    assert data.get("parts") == 1
    assert isinstance(data.get("part_lengths"), list)
    assert len(data.get("part_lengths") or []) == 1
    assert data.get("len") == 2


def test_explicit_split_flag_packs_short_sections_into_one() -> None:
    """多节 ## 较短时应合并为一条，减少刷屏。"""
    msg = "## 一\na\n## 二\nb\n"
    r = tool_send_dingtalk_message(
        message=msg,
        webhook_url="https://example.com/hook",
        mode="test",
        split_markdown_sections=True,
        max_chars_per_message=1750,
    )
    assert r.get("success") is True
    data = r.get("data") or {}
    assert data.get("parts") == 1
    pls = data.get("part_lengths") or []
    assert isinstance(pls, list) and len(pls) == 1 and int(pls[0]) >= len("## 一\na\n## 二\nb")
    assert data.get("auto_split") is False


def test_split_markdown_splits_on_h3_sections() -> None:
    """开盘/晨报多用 ### 小节：应按 ### 切节再合并；函数内单条下限 400 字符，用较大正文触发多分条。"""
    big = "x" * 220 + "\n"
    msg = "### 一、结论\n" + big + "### 二、要闻\n" + big + "### 三、隔夜\n" + big
    parts = _split_markdown_for_dingtalk(msg, max_chars=500)
    assert len(parts) >= 2
    assert any("一、结论" in p for p in parts)
    assert any("二、要闻" in p for p in parts)


def test_split_markdown_packs_until_max_then_splits() -> None:
    s1 = "## A\n" + "x" * 700
    s2 = "## B\n" + "y" * 700
    s3 = "## C\n" + "z" * 700
    parts = _split_markdown_for_dingtalk(f"{s1}\n\n{s2}\n\n{s3}", max_chars=1200)
    assert len(parts) >= 2
    assert all(len(p) <= 1200 for p in parts)


def test_soft_break_after_percent_comma() -> None:
    chunk = "填" * 40 + "指数涨0.4%，投资者观望情绪" + "填" * 120
    cut = _soft_break_before(chunk, min_keep=30)
    assert cut < len(chunk)
    assert "%，" in chunk[:cut]


def test_rewind_cut_when_trailing_digit_dot_before_percent_in_next_slice() -> None:
    """模拟分片窗口末端落在「0.」而「4%」在下一段，避免「上涨0.」腰斩。"""
    full = "日经225指数上涨0.4%，投资者谨慎"
    bad_cut = len("日经225指数上涨0.")
    rew = _rewind_cut_for_incomplete_number(full, bad_cut, min_keep=5)
    assert rew < bad_cut
    assert full[:rew].rstrip().endswith("涨")


def test_rewind_cut_when_trailing_decimal_then_percent_in_tail() -> None:
    """末端为「0.4」且后续正文以 % 开头时回退到小数点前。"""
    head = "道琼斯下跌0.4"
    full = head + "%，后续观望"
    rew = _rewind_cut_for_incomplete_number(full, len(head), min_keep=5)
    assert rew < len(head)
    assert full[:rew].rstrip().endswith("跌")


def test_rewind_cut_cn_coordinator_before_following_cjk() -> None:
    """功能字（与）后紧跟汉字时：回退到前面句读，与题材/专有名词无关。"""
    s = "绪" * 90 + "综上，左侧与右侧均值得关注"
    bad = s.index("右")
    rew = _rewind_cut_for_dangling_conjunction(s, bad, min_keep=20)
    assert rew < bad
    assert s[:rew].rstrip().endswith("，")


def test_soft_break_full_window_rewinds_trailing_digit_dot() -> None:
    """无更早软断点时整窗以「0.」收尾，应回退到小数点前。"""
    chunk = "宽" * 95 + "纳斯达克指数逆势上涨0."
    assert chunk.endswith("0.")
    cut = _soft_break_before(chunk, min_keep=40)
    head = chunk[:cut].rstrip()
    assert not head.endswith(".")
    assert head.endswith("涨")


def test_split_oversize_prefers_sentence_boundary() -> None:
    """长段以中文逗号串联时，在逗号处断开并带续接提示。"""
    body = "总述。" + ("分述内容，" * 120) + "结语。"
    parts = _split_oversize_section(body, max_chars=200)
    assert len(parts) >= 2
    assert "— 未完，见下一条 —" in parts[0]
    assert parts[1].startswith("（续）")


def test_split_oversize_full_window_still_gets_continuation_marker() -> None:
    """无软断点时整窗切满 max_chars，只要后文仍在 section 内，也应提示续条。"""
    body = "X" * 500 + "Y" * 500
    parts = _split_oversize_section(body, max_chars=300)
    assert len(parts) >= 2
    assert "— 未完，见下一条 —" in parts[0]
    assert parts[1].startswith("（续）")


def test_resolve_max_chars_explicit_respects_config_ceiling() -> None:
    cap = _dingtalk_max_chars_hard_ceiling()
    assert _resolve_max_chars_per_message(5000) == min(5000, cap)
    assert _resolve_max_chars_per_message(900) == 900
    assert _resolve_max_chars_per_message(None) >= 400
    assert _resolve_max_chars_per_message(None) <= cap


def test_safe_max_constant_matches_default_ceiling() -> None:
    assert DEFAULT_DINGTALK_MAX_CHARS_HARD_CEILING == 20000
    assert DINGTALK_CUSTOM_ROBOT_TEXT_SAFE_MAX == DEFAULT_DINGTALK_MAX_CHARS_HARD_CEILING
