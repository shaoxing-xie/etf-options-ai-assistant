"""
LLM增强模块

负责：
- 读取 Prompt_config.yaml
- 根据 analysis_type 构建提示词
- 调用兼容 OpenAI 的 LLM 接口（如 DeepSeek / OpenAI / Grok 等）
- 返回 llm_summary（Markdown 文本）和 llm_meta（元信息）
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Tuple, Optional

import yaml

from src.logger_config import get_module_logger, log_error_with_context
from src.config_loader import load_system_config


logger = get_module_logger(__name__)


def _load_prompt_config(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    加载 Prompt 配置文件（YAML）

    优先从 config['llm_enhancer']['prompt_config_path'] 读取路径，默认 "Prompt_config.yaml"
    """
    try:
        if config is None:
            config = load_system_config(use_cache=True)

        llm_cfg = config.get("llm_enhancer", {}) if isinstance(config, dict) else {}
        prompt_path_str = llm_cfg.get("prompt_config_path", "Prompt_config.yaml")

        prompt_path = Path(prompt_path_str)
        if not prompt_path.is_absolute():
            # 相对路径：优先相对于当前工作目录（通常为项目根目录，如 openclaw_migration）
            cwd = Path.cwd()
            candidates = [cwd / prompt_path]

            # 兼容旧行为：也尝试 src 上级目录作为项目根目录
            src_root = Path(__file__).resolve().parents[1]
            if src_root not in candidates:
                candidates.append(src_root / prompt_path)

            # 选择第一个存在的路径；如果都不存在，就使用 cwd 下的默认路径用于日志提示
            resolved = None
            for candidate in candidates:
                if candidate.exists():
                    resolved = candidate
                    break
            prompt_path = resolved or candidates[0]

        if not prompt_path.exists():
            logger.warning(f"Prompt 配置文件不存在: {prompt_path}")
            return {}

        with open(prompt_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        if not isinstance(data, dict):
            logger.warning(f"Prompt 配置文件格式异常（应为字典）: {prompt_path}")
            return {}

        return data
    except Exception as e:
        log_error_with_context(
            logger,
            e,
            {"function": "_load_prompt_config"},
            "加载 Prompt 配置失败",
        )
        return {}


def _build_prompts(
    analysis_data: Dict[str, Any],
    analysis_type: str,
    prompt_config: Dict[str, Any],
    history_summaries: str = "",
) -> Tuple[str, str]:
    """
    根据 analysis_type 与 Prompt_config 构建 system_prompt 与 user_prompt
    """
    llm_prompts = prompt_config.get("llm_prompts", {}) if isinstance(prompt_config, dict) else {}

    # 优先使用对应类型，其次使用 default
    type_cfg = llm_prompts.get(analysis_type) or llm_prompts.get("default") or {}
    system_prompt = type_cfg.get("system") or "你是一名稳健的量化交易分析师。"
    user_template = type_cfg.get("user_template") or (
        "以下是分析结果的JSON：\n\n{analysis_json}\n\n请给出简要总结。"
    )

    try:
        analysis_json = json.dumps(analysis_data, ensure_ascii=False, indent=2)
    except Exception:
        # 回退：尽量保证不会因为 dumps 失败导致整体失败
        analysis_json = str(analysis_data)

    # 为避免格式化冲突，这里仅替换约定占位符，其它花括号保持原样
    user_prompt = user_template.replace("{analysis_json}", analysis_json)
    if "{history_summaries}" in user_template:
        # 如果模板中预留了历史摘要占位符，则注入当日累计摘要（可为空字符串）
        user_prompt = user_prompt.replace("{history_summaries}", history_summaries or "")

    return system_prompt, user_prompt


def enhance_with_llm(
    analysis_data: Dict[str, Any],
    analysis_type: str,
    config: Optional[Dict[str, Any]] = None,
) -> Tuple[str, Dict[str, Any]]:
    """
    使用 LLM 对分析结果进行自然语言增强

    Args:
        analysis_data: 原有分析结果 dict
        analysis_type: 分析类型（before_open / opening_market / after_close / intraday_summary 等）
        config: 系统配置

    Returns:
        (llm_summary, llm_meta)
    """
    try:
        if config is None:
            config = load_system_config(use_cache=True)

        llm_cfg = config.get("llm_enhancer", {}) if isinstance(config, dict) else {}
        if not llm_cfg.get("enabled", False):
            return "", {}

        enabled_types = llm_cfg.get("analysis_types") or []
        # 支持子类型匹配：volatility_prediction_underlying 和 volatility_prediction_option 都匹配 volatility_prediction
        is_enabled = analysis_type in enabled_types
        if not is_enabled and analysis_type.startswith("volatility_prediction_"):
            is_enabled = "volatility_prediction" in enabled_types
        
        if not is_enabled:
            # 未在白名单中的类型不调用LLM
            logger.debug(f"LLM增强：analysis_type={analysis_type} 不在启用列表中 {enabled_types}，跳过")
            return "", {}

        api_key = llm_cfg.get("api_key")
        if not api_key or api_key.startswith("sk-your-"):
            logger.warning(f"LLM增强已启用（analysis_type={analysis_type}），但未配置有效的 api_key，跳过调用")
            return "", {}

        api_base_url = llm_cfg.get("api_base_url") or "https://api.openai.com/v1"
        model = llm_cfg.get("model") or "gpt-4.1-mini"
        temperature = float(llm_cfg.get("temperature", 0.7))
        max_tokens = int(llm_cfg.get("max_tokens", 500)) if llm_cfg.get("max_tokens") else None
        timeout_seconds = int(llm_cfg.get("timeout_seconds", 30))  # 增加到30秒，因为盘后分析数据量大
        retry_attempts = int(llm_cfg.get("retry_attempts", 2))
        retry_delay = float(llm_cfg.get("retry_delay", 2.0))  # 重试延迟（秒）

        # 轻量连续记忆：加载当日摘要上下文（可选）
        history_summaries: str = ""
        context_path: Optional[Path] = None
        context_enabled = bool(llm_cfg.get("context_enabled", False))
        if context_enabled:
            try:
                context_file_str = llm_cfg.get("context_file", "data/cache/llm_context_today.json")
                context_path = Path(context_file_str)
                if not context_path.is_absolute():
                    base_dir = Path(__file__).resolve().parents[1]
                    context_path = base_dir / context_path
                context_path.parent.mkdir(parents=True, exist_ok=True)

                today = datetime.now().strftime("%Y%m%d")
                context_data: Dict[str, Any] = {"date": today, "summaries": []}
                if context_path.exists():
                    try:
                        with context_path.open("r", encoding="utf-8") as f:
                            loaded = json.load(f) or {}
                        if loaded.get("date") == today:
                            context_data = loaded
                    except Exception as e:
                        logger.debug(f"读取LLM上下文文件失败，将重置: {e}")
                # 如果日期不匹配或文件不存在，写入当日空结构
                if context_data.get("date") != today:
                    context_data = {"date": today, "summaries": []}
                    with context_path.open("w", encoding="utf-8") as f:
                        json.dump(context_data, f, ensure_ascii=False, indent=2)
                # 拼接历史摘要
                summaries = context_data.get("summaries") or []
                if isinstance(summaries, list):
                    history_summaries = "\n".join(str(s) for s in summaries)
            except Exception as e:
                logger.warning(f"初始化LLM连续记忆上下文失败（不影响主流程）: {e}")
                context_path = None

        # 加载 Prompt 配置并构建 prompts（支持 history_summaries 占位符）
        prompt_config = _load_prompt_config(config)
        system_prompt, user_prompt = _build_prompts(
            analysis_data,
            analysis_type,
            prompt_config,
            history_summaries=history_summaries,
        )

        try:
            # OpenAI 1.x 客户端（兼容 DeepSeek / Grok 的 OpenAI 风格接口）
            from openai import OpenAI
        except ImportError as e:
            logger.warning(f"未安装 openai 库，无法调用LLM增强: {e}")
            return "", {}

        client = OpenAI(api_key=api_key, base_url=api_base_url, timeout=timeout_seconds)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        last_error: Optional[Exception] = None
        import time
        start_time = None
        for attempt in range(retry_attempts + 1):
            try:
                # 记录开始时间
                start_time = time.time()
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                elapsed_time = time.time() - start_time
                choice = response.choices[0]
                content = (choice.message.content or "").strip()

                if not content:
                    logger.warning("LLM返回内容为空，跳过增强")
                    return "", {}

                usage = getattr(response, "usage", None)
                llm_meta: Dict[str, Any] = {
                    "provider": llm_cfg.get("provider", "openai"),
                    "model": model,
                    "analysis_type": analysis_type,
                    "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
                if usage is not None:
                    llm_meta["usage"] = {
                        "prompt_tokens": getattr(usage, "prompt_tokens", None),
                        "completion_tokens": getattr(usage, "completion_tokens", None),
                        "total_tokens": getattr(usage, "total_tokens", None),
                    }

                logger.info(
                    f"LLM增强完成: type={analysis_type}, model={model}, "
                    f"tokens={llm_meta.get('usage', {}).get('total_tokens')}, "
                    f"耗时={elapsed_time:.2f}秒"
                )

                # 调用成功后，记录简短摘要到本地上下文（仅在启用连续记忆时）
                if context_enabled and context_path is not None:
                    try:
                        today = datetime.now().strftime("%Y%m%d")
                        try:
                            with context_path.open("r", encoding="utf-8") as f:
                                ctx = json.load(f) or {}
                        except Exception:
                            ctx = {}
                        if ctx.get("date") != today:
                            ctx = {"date": today, "summaries": []}
                        summaries = ctx.get("summaries") or []
                        if not isinstance(summaries, list):
                            summaries = []
                        summary_text = f"{datetime.now().strftime('%H:%M')} {analysis_type}: {content[:200]}..."
                        summaries.append(summary_text)
                        max_items = int(llm_cfg.get("summary_max_items", 6))
                        ctx["summaries"] = summaries[-max_items:] if max_items > 0 else summaries
                        with context_path.open("w", encoding="utf-8") as f:
                            json.dump(ctx, f, ensure_ascii=False, indent=2)
                    except Exception as e:
                        logger.debug(f"写入LLM连续记忆摘要失败（不影响主流程）: {e}")

                return content, llm_meta
            except Exception as e:
                last_error = e
                elapsed_time = time.time() - start_time if start_time is not None else 0
                if attempt < retry_attempts:
                    logger.warning(
                        f"LLM调用失败（第{attempt + 1}次尝试，耗时={elapsed_time:.2f}秒），"
                        f"{retry_delay}秒后重试: {e}"
                    )
                    time.sleep(retry_delay)
                else:
                    logger.warning(f"LLM调用失败（第{attempt + 1}次尝试，耗时={elapsed_time:.2f}秒），已达最大重试次数: {e}")

        if last_error:
            log_error_with_context(
                logger,
                last_error,
                {"function": "enhance_with_llm", "analysis_type": analysis_type},
                "LLM调用失败，已回退到原有输出",
            )
        return "", {}

    except Exception as e:
        log_error_with_context(
            logger,
            e,
            {"function": "enhance_with_llm", "analysis_type": analysis_type},
            "LLM增强过程中发生异常",
        )
        return "", {}

