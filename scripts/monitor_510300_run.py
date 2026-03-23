#!/usr/bin/env python3
"""
510300 实盘监控 - 执行逻辑 + webhook 推送
支持钉钉/飞书，通过 MONITOR_WEBHOOK_URL 或 alert_webhook.json 配置
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# 项目根目录（openclaw workspace）
ROOT = Path(__file__).resolve().parent.parent
# 工具项目目录（含 tool_runner、plugins）
ETF_PROJECT = Path(os.environ.get("ETF_OPTIONS_PROJECT", str(ROOT)))
if not ETF_PROJECT.exists():
    ETF_PROJECT = ROOT


def _run_tool(tool_name: str, args: str = "{}") -> str:
    """通过 tool_runner 调用工具"""
    runner = ETF_PROJECT / "tool_runner.py"
    if not runner.exists():
        return f"(tool_runner 未找到: {runner})"
    try:
        r = subprocess.run(
            [sys.executable, str(runner), tool_name, args],
            capture_output=True,
            text=True,
            cwd=str(ETF_PROJECT),
            timeout=15,
        )
        out = (r.stdout or "").strip() or (r.stderr or "").strip()
        return out or f"(exit {r.returncode})"
    except Exception as e:
        return f"(调用失败: {e})"


def _get_webhook_url() -> str | None:
    """MONITOR_WEBHOOK_URL > alert_webhook.json > None（不推送）"""
    url = os.environ.get("MONITOR_WEBHOOK_URL") or os.environ.get("ALERT_WEBHOOK_URL")
    if url and str(url).strip():
        return str(url).strip()
    cfg_path = Path(__file__).resolve().parent.parent.parent / "shared" / "alert_webhook.json"
    if cfg_path.exists():
        try:
            with open(cfg_path, encoding="utf-8") as f:
                cfg = json.load(f)
            url = cfg.get("url") or cfg.get("webhook_url")
            if url and str(url).strip():
                return str(url).strip()
        except Exception:
            pass
    return None


def _get_dingtalk_keyword() -> str | None:
    """
    钉钉自定义机器人可配置“关键词”安全校验：
    - 机器人后台启用后，发送内容必须包含该关键词，否则会返回“关键词不匹配”。
    - 这里支持通过 env 或 alert_webhook.json 配置 keyword，并在发送时自动补齐。
    """
    kw = os.environ.get("DINGTALK_KEYWORD") or os.environ.get("MONITOR_DINGTALK_KEYWORD")
    if kw and str(kw).strip():
        return str(kw).strip()

    cfg_path = Path(__file__).resolve().parent.parent.parent / "shared" / "alert_webhook.json"
    if cfg_path.exists():
        try:
            with open(cfg_path, encoding="utf-8") as f:
                cfg = json.load(f)
            kw = cfg.get("keyword") or cfg.get("dingtalk_keyword")
            if kw and str(kw).strip():
                return str(kw).strip()
        except Exception:
            pass
    return None


def _send_webhook(url: str, text: str) -> dict:
    """发送到 webhook，自动识别钉钉/飞书"""
    import urllib.error
    import urllib.request

    url_lower = url.lower()
    if "oapi.dingtalk.com" in url_lower:
        # 钉钉文本通常有长度限制；过长会被拒绝或截断
        keyword = _get_dingtalk_keyword()
        if keyword and keyword not in text:
            text = f"{keyword}\n{text}"
        safe_text = text if len(text) <= 1800 else (text[:1800] + "\n...(truncated)")
        payload = {"msgtype": "text", "text": {"content": safe_text}}
    else:
        # 飞书文本也做一次安全截断（避免极端长消息）
        safe_text = text if len(text) <= 3500 else (text[:3500] + "\n...(truncated)")
        payload = {"msg_type": "text", "content": {"text": safe_text}}

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8") or "{}"
            try:
                parsed = json.loads(body)
            except json.JSONDecodeError:
                parsed = {"raw": body}
            # 钉钉成功返回：{"errcode":0,"errmsg":"ok"}
            if "oapi.dingtalk.com" in url_lower and isinstance(parsed, dict):
                err = parsed.get("errcode")
                if err is not None and err != 0:
                    return {"success": False, "error": f"dingtalk errcode={err} errmsg={parsed.get('errmsg')}", "response": parsed}
            # 飞书成功返回通常为 {"code":0,"msg":"success"}（也有 StatusCode/StatusMessage 变体）
            if "oapi.dingtalk.com" not in url_lower and isinstance(parsed, dict):
                code = parsed.get("code")
                if code is not None and code != 0:
                    return {"success": False, "error": f"feishu code={code} msg={parsed.get('msg')}", "response": parsed}
                status_code = parsed.get("StatusCode")
                if status_code is not None and status_code != 0:
                    return {"success": False, "error": f"feishu StatusCode={status_code} StatusMessage={parsed.get('StatusMessage')}", "response": parsed}
            return {"success": True, "response": parsed}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8") if e.fp else ""
        return {"success": False, "error": str(e), "response": body}
    except Exception as e:
        return {"success": False, "error": str(e)}


def run() -> str:
    lines: list[str] = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines.append("=========================================")
    lines.append(f"510300 实盘监控 - {now}")
    lines.append("=========================================")

    # 1. 交易状态
    result = _run_tool("tool_check_trading_status")
    lines.append("")
    lines.append("检查交易状态:")
    lines.append(result)

    # 2. 实时行情
    result = _run_tool("tool_fetch_etf_realtime", json.dumps({"etf_code": "510300"}))
    lines.append("")
    lines.append("510300 实时行情:")
    lines.append(result)

    # 3. 30分钟布林带 + 信号
    lines.append("")
    lines.append("30分钟布林带:")
    try:
        import pandas as pd

        cache_dir = ROOT / "data" / "cache" / "etf_minute" / "510300" / "30"
        if not cache_dir.exists():
            cache_dir = ETF_PROJECT / "data" / "cache" / "etf_minute" / "510300" / "30"
        files = sorted(cache_dir.glob("*.parquet"))[-5:] if cache_dir.exists() else []
        if not files:
            lines.append("  无30分钟缓存数据")
        else:
            dfs = [pd.read_parquet(f) for f in files]
            df = pd.concat(dfs, ignore_index=True).drop_duplicates(subset=["时间"]).sort_values("时间")
            df["BOLL_MID"] = df["收盘"].rolling(20).mean()
            df["BOLL_STD"] = df["收盘"].rolling(20).std()
            df["BOLL_UPPER"] = df["BOLL_MID"] + 2 * df["BOLL_STD"]
            df["BOLL_LOWER"] = df["BOLL_MID"] - 2 * df["BOLL_STD"]
            delta = df["收盘"].diff()
            gain = delta.where(delta > 0, 0).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss
            df["RSI14"] = 100 - (100 / (1 + rs))
            # 取最后一行有效值（rolling 前若干行为 NaN）
            valid = df[["收盘", "BOLL_MID", "BOLL_UPPER", "BOLL_LOWER", "RSI14"]].dropna(how="any")
            if valid.empty:
                lines.append("  数据不足，无法计算布林带（需至少20根K线）")
            else:
                last = valid.iloc[-1]
                price = float(last["收盘"])
                upper = float(last["BOLL_UPPER"])
                mid = float(last["BOLL_MID"])
                lower = float(last["BOLL_LOWER"])
                rsi = float(last["RSI14"])
                shares_6k = int(6000 / price) if price > 0 else 0
                stop_loss = round(lower * 0.98, 2)

                lines.append(f"  当前价格: {price:.3f}")
                lines.append(f"  布林上轨: {upper:.3f}")
                lines.append(f"  布林中轨: {mid:.3f}")
                lines.append(f"  布林下轨: {lower:.3f}")
                lines.append(f"  RSI14: {rsi:.1f}")
                lines.append("")

                if last["收盘"] <= last["BOLL_LOWER"]:
                    lines.append("*** 买入信号: 价格触及布林下轨 ***")
                    lines.append("  建议动作:")
                    lines.append(f"    首仓: 6000元 (约{shares_6k}股)")
                    lines.append("    分批: 跌破下轨买50%, 企稳加50%")
                    lines.append(f"    止损: 跌破 {stop_loss} 无条件砍")
                    lines.append(f"    止盈: 回到中轨 {mid:.2f} 止盈50%, 到上轨 {upper:.2f} 全部止盈")
                    if rsi < 35:
                        lines.append("  [RSI超卖, 信号增强]")
                elif last["收盘"] >= last["BOLL_UPPER"]:
                    lines.append("*** 卖出信号: 价格触及布林上轨 ***")
                    lines.append("  建议动作:")
                    lines.append("    减仓: 突破上轨减50%持仓")
                    lines.append("    清仓: 连续2根K线收阴则清仓")
                    if rsi > 65:
                        lines.append("  [RSI超买, 信号增强]")
                elif rsi < 35:
                    lines.append("*** 关注: RSI超卖, 接近下轨可考虑买入 ***")
                elif rsi > 65:
                    lines.append("*** 关注: RSI超买, 接近上轨可考虑减仓 ***")
                else:
                    lines.append("状态: 观望, 价格在布林带中部")
    except Exception as e:
        lines.append(f"  布林带计算失败: {e}")

    lines.append("")
    lines.append("=========================================")
    lines.append(f"监控完成 - {now}")
    lines.append("=========================================")

    return "\n".join(lines)


def main() -> None:
    report = run()
    print(report)

    url = _get_webhook_url()
    if url:
        result = _send_webhook(url, report)
        if result.get("success"):
            print("\n[已推送至钉钉/飞书]")
        else:
            print(f"\n[推送失败: {result.get('error', 'unknown')}]")


if __name__ == "__main__":
    main()
