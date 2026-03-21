"""
飞书插件通知处理器
接收Coze插件发送的通知消息，从飞书云空间拉取数据文件并处理
"""

import json
import re
from typing import Dict, Optional, List, Any, Tuple
from datetime import datetime

from src.logger_config import get_module_logger
from src.config_loader import load_system_config
from src.feishu_api import FeishuAPI
from src.feishu_data_processor import (
    process_index_minute_data,
    process_etf_minute_data,
    process_option_greeks_data
)

logger = get_module_logger(__name__)


def normalize_tool_name(tool: str) -> str:
    """
    标准化工具名称，处理命名不一致问题
    
    Args:
        tool: 原始工具名称
    
    Returns:
        str: 标准化后的工具名称
    """
    if not tool:
        return tool
    # 兼容 greek_data (单数) 和 greeks_data (复数)
    if tool == "greek_data":
        return "greeks_data"
    return tool


def parse_plugin_notification(text: str) -> Optional[Dict[str, Any]]:
    """
    解析插件通知消息
    
    消息格式示例：
    工具: greeks_data
    时间: 20260203092215
    状态: success
    成功文件数: 1
    文件列表: GREEKS_2个合约
    错误数: 0
    
    Args:
        text: 消息文本
    
    Returns:
        dict: 解析后的通知信息，如果不是插件通知则返回None
        {
            "tool": "greeks_data",
            "timestamp": "20260203092215",
            "status": "success",
            "files_count": 1,
            "files": ["GREEKS_2个合约"],
            "errors_count": 0
        }
    """
    try:
        # 检查是否是插件通知消息（包含"工具:"）
        # 注意：消息标题可能包含"Coze行情插件通知"，但消息内容可能只有"工具:"等字段
        if "工具:" not in text:
            return None
        
        # 提取各个字段
        tool_match = re.search(r'工具:\s*(\w+)', text)
        timestamp_match = re.search(r'时间:\s*(\d+)', text)
        status_match = re.search(r'状态:\s*(\w+)', text)
        files_count_match = re.search(r'成功文件数:\s*(\d+)', text)
        files_match = re.search(r'文件列表:\s*(.+)', text)
        errors_match = re.search(r'错误数:\s*(\d+)', text)
        
        if not tool_match:
            return None
        
        tool = tool_match.group(1).strip()
        timestamp = timestamp_match.group(1).strip() if timestamp_match else ""
        status = status_match.group(1).strip() if status_match else "unknown"
        files_count = int(files_count_match.group(1)) if files_count_match else 0
        
        # 解析文件列表（支持格式：filename|file_token 或 filename）
        files = []  # 存储文件信息字典列表
        file_tokens = {}  # 文件名 -> token 映射
        
        if files_match:
            files_str = files_match.group(1).strip()
            # 文件列表可能是逗号分隔的，或者单个文件名
            if "," in files_str:
                file_items = [f.strip() for f in files_str.split(",")]
            else:
                file_items = [files_str] if files_str else []
            
            for item in file_items:
                # 检查是否包含文件token（格式：filename|file_token）
                if "|" in item:
                    parts = item.split("|", 1)
                    filename = parts[0].strip()
                    file_token = parts[1].strip()
                    files.append(filename)
                    file_tokens[filename] = file_token
                    logger.info(f"解析到文件token: {filename} -> {file_token[:20]}...")
                else:
                    # 只有文件名，没有token
                    filename = item
                    files.append(filename)
        
        # 标准化工具名称（兼容 greek_data 和 greeks_data）
        tool = normalize_tool_name(tool)
        
        # 如果文件列表是描述性文本（如"GREEKS_2个合约"），根据工具类型和时间戳生成实际文件名
        if files and tool == "greeks_data":
            # 检查是否是描述性文本
            if "个合约" in files[0] or not files[0].endswith(".json"):
                # 根据时间戳生成实际文件名
                if timestamp:
                    files = [f"GREEKS_{timestamp}.json"]
        elif files and tool in ["index_minute_data", "etf_minute_data"]:
            # 对于指数和ETF，如果文件名不完整，可能需要根据时间戳和模式生成
            # 但这里暂时保持原样，因为它们的文件名格式更复杂
            pass
        
        errors_count = int(errors_match.group(1)) if errors_match else 0
        
        return {
            "tool": tool,
            "timestamp": timestamp,
            "status": status,
            "files_count": files_count,
            "files": files,
            "file_tokens": file_tokens,  # 文件名 -> token 映射
            "errors_count": errors_count
        }
    except Exception as e:
        logger.error(f"解析插件通知消息失败: {e}", exc_info=True)
        return None


def get_folder_token_for_tool(tool: str, config: Dict) -> Optional[str]:
    """
    根据工具名称获取对应的文件夹token
    
    Args:
        tool: 工具名称（greeks_data, index_minute_data, etf_minute_data）
        config: 系统配置
    
    Returns:
        str: 文件夹token，如果未找到返回None
    """
    try:
        # 工具名称到文件夹名称的映射
        tool_to_folder = {
            "greeks_data": "option_greeks",
            "index_minute_data": "index_minute",
            "etf_minute_data": "etf_minute"
        }
        
        folder_name = tool_to_folder.get(tool)
        if not folder_name:
            logger.warning(f"未知的工具名称: {tool}")
            return None
        
        # 尝试从多个配置位置获取文件夹token
        # 1. 从 feishu_cloud.subfolders 获取
        feishu_cloud_config = config.get('feishu_cloud', {})
        subfolders = feishu_cloud_config.get('subfolders', {})
        
        # 如果 subfolders 是字符串（JSON），先解析
        if isinstance(subfolders, str):
            try:
                subfolders = json.loads(subfolders)
            except json.JSONDecodeError:
                logger.debug(f"无法解析 feishu_cloud.subfolders JSON: {subfolders}")
                subfolders = {}
        
        folder_token = subfolders.get(folder_name)
        
        # 2. 如果还没有找到，尝试从 notification.feishu_app 获取
        if not folder_token:
            notification_config = config.get('notification', {})
            feishu_app_config = notification_config.get('feishu_app', {})
            subfolders = feishu_app_config.get('subfolders', {})
            
            if isinstance(subfolders, str):
                try:
                    subfolders = json.loads(subfolders)
                except json.JSONDecodeError:
                    subfolders = {}
            
            folder_token = subfolders.get(folder_name)
        
        # 3. 如果还没有找到，尝试从环境变量获取（作为后备）
        if not folder_token:
            import os
            env_key = f"FEISHU_FOLDER_{folder_name.upper()}"
            folder_token = os.environ.get(env_key)
            if folder_token:
                logger.info(f"从环境变量获取文件夹token: {env_key}")
        
        if not folder_token:
            logger.warning(
                f"未找到工具 {tool} 对应的文件夹token (folder_name={folder_name})\n"
                f"请确保配置文件中包含以下配置之一：\n"
                f"  1. feishu_cloud.subfolders.{folder_name}\n"
                f"  2. notification.feishu_app.subfolders.{folder_name}\n"
                f"  3. 环境变量 FEISHU_FOLDER_{folder_name.upper()}"
            )
        
        return folder_token
    except Exception as e:
        logger.error(f"获取文件夹token失败: {e}", exc_info=True)
        return None


def find_files_by_pattern(files: List[Dict], pattern: str, timestamp: str) -> List[Dict]:
    """
    根据文件名模式和时间戳查找文件
    
    Args:
        files: 文件列表（从 list_files 返回）
        pattern: 文件名模式（如 "GREEKS_"）
        timestamp: 时间戳（如 "20260203092215"）
    
    Returns:
        List[Dict]: 匹配的文件列表
    """
    matched_files = []
    
    # 构建文件名模式
    # 例如：GREEKS_20260203092215.json 或 GREEKS_2个合约
    # 优先匹配精确时间戳，如果没有则匹配包含模式的文件
    pattern_lower = pattern.lower()
    
    for file in files:
        # 兼容异常数据：仅处理字典类型的文件信息
        if not isinstance(file, dict):
            continue

        file_name = file.get('name', '').lower()
        file_token = file.get('token', '')
        
        if not file_name or not file_token:
            continue
        
        # 优先匹配包含时间戳的文件
        if timestamp and timestamp in file_name and pattern_lower in file_name:
            matched_files.append(file)
        # 如果没有时间戳匹配，则匹配包含模式的文件
        elif pattern_lower in file_name:
            matched_files.append(file)
    
    return matched_files


def delete_file_from_feishu(feishu_api: FeishuAPI, file_token: str) -> Tuple[bool, str]:
    """
    从飞书云空间删除文件
    
    根据飞书API文档，尝试多种删除方法：
    1. 使用 drive/v1/files/{file_token} (标准方法)
    2. 使用 drive/explorer/v2/file/{file_token} (explorer方法)
    3. 使用 POST 方法 + type 参数
    
    Args:
        feishu_api: FeishuAPI 实例
        file_token: 文件token
    
    Returns:
        tuple[bool, str]: (删除是否成功, 错误信息)
    """
    try:
        token = feishu_api.get_tenant_token()
        if not token:
            error_msg = "获取飞书访问token失败，无法删除文件"
            logger.error(error_msg)
            return False, error_msg
        
        import requests
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        # 方法1: 使用 drive/v1/files/{file_token} (DELETE) + type参数
        # 根据飞书API文档，删除文件需要必填参数 type
        # 尝试两种方式：URL参数和请求体
        url1 = f"https://open.feishu.cn/open-apis/drive/v1/files/{file_token}"
        resp1 = None
        try:
            # 方式1: 使用URL查询参数
            resp1 = requests.delete(f"{url1}?type=file", headers=headers, timeout=10)
            if resp1.status_code == 200:
                try:
                    data = resp1.json()
                    if data.get("code") == 0:
                        logger.info(f"删除文件成功（方法1-URL参数）: {file_token[:20]}...")
                        return True, ""
                    else:
                        # HTTP 200 但 code != 0，记录错误但继续尝试其他方法
                        error_code = data.get("code", "未知")
                        error_msg = data.get("msg", "未知错误")
                        logger.debug(f"方法1-URL参数失败: code={error_code}, msg={error_msg}")
                except json.JSONDecodeError:
                    # 响应不是JSON，可能删除成功（某些情况下飞书可能返回空响应）
                    logger.info(f"删除文件成功（方法1-URL参数，空响应）: {file_token[:20]}...")
                    return True, ""
            
            # 如果URL参数方式失败，尝试使用请求体
            # 检查是否需要尝试请求体方式：如果第一次请求失败（非200）或返回200但code!=0
            need_try_body = False
            if resp1.status_code != 200:
                need_try_body = True
            else:
                try:
                    data_check = resp1.json()
                    if data_check.get("code") != 0:
                        need_try_body = True
                except json.JSONDecodeError:
                    # 如果第一次请求返回空响应，可能已经成功，不需要再试
                    pass
            
            if need_try_body:
                data1 = {"type": "file"}
                resp1 = requests.delete(url1, headers=headers, json=data1, timeout=10)
                if resp1.status_code == 200:
                    try:
                        data = resp1.json()
                        if data.get("code") == 0:
                            logger.info(f"删除文件成功（方法1-请求体）: {file_token[:20]}...")
                            return True, ""
                        else:
                            error_code = data.get("code", "未知")
                            error_msg = data.get("msg", "未知错误")
                            logger.debug(f"方法1-请求体失败: code={error_code}, msg={error_msg}")
                    except json.JSONDecodeError:
                        logger.info(f"删除文件成功（方法1-请求体，空响应）: {file_token[:20]}...")
                        return True, ""
        except Exception as e:
            logger.debug(f"方法1异常: {e}")
        
        # 方法2: 使用 drive/explorer/v2/file/{file_token} (DELETE) + type参数
        url2 = f"https://open.feishu.cn/open-apis/drive/explorer/v2/file/{file_token}?type=file"
        resp2 = None
        try:
            resp2 = requests.delete(url2, headers=headers, timeout=10)
            if resp2.status_code == 200:
                try:
                    data = resp2.json()
                    if data.get("code") == 0:
                        logger.info(f"删除文件成功（方法2）: {file_token[:20]}...")
                        return True, ""
                    else:
                        error_code = data.get("code", "未知")
                        error_msg = data.get("msg", "未知错误")
                        logger.debug(f"方法2失败: code={error_code}, msg={error_msg}")
                except json.JSONDecodeError:
                    logger.info(f"删除文件成功（方法2，空响应）: {file_token[:20]}...")
                    return True, ""
        except Exception as e:
            logger.debug(f"方法2异常: {e}")
        
        # 方法3: 使用批量删除接口（单个文件）+ type参数
        url3 = "https://open.feishu.cn/open-apis/drive/v1/files/batch_delete"
        resp3 = None
        try:
            # 批量删除接口，即使只有一个文件也可以使用
            # 根据飞书API文档，需要指定type参数
            data3 = {
                "file_tokens": [file_token],
                "type": "file"
            }
            resp3 = requests.post(url3, headers=headers, json=data3, timeout=10)
            if resp3.status_code == 200:
                try:
                    result = resp3.json()
                    if result.get("code") == 0:
                        logger.info(f"删除文件成功（方法3-批量删除）: {file_token[:20]}...")
                        return True, ""
                    else:
                        error_code = result.get("code", "未知")
                        error_msg = result.get("msg", "未知错误")
                        logger.debug(f"方法3失败: code={error_code}, msg={error_msg}")
                except json.JSONDecodeError:
                    logger.debug(f"方法3响应不是JSON格式")
        except Exception as e:
            logger.debug(f"方法3异常: {e}")
        
        # 如果所有方法都失败，记录详细错误信息
        # 使用最后一次尝试的响应
        last_resp = resp1 if 'resp1' in locals() and resp1 is not None else (resp2 if 'resp2' in locals() and resp2 is not None else (resp3 if 'resp3' in locals() and resp3 is not None else None))
        error_detail = "所有删除方法均失败"
        if last_resp:
            try:
                error_data = last_resp.json()
                error_msg = error_data.get('msg', '未知错误')
                error_code = error_data.get('code', '未知')
                error_detail = f"HTTP {last_resp.status_code}, code={error_code}, msg={error_msg}"
                logger.warning(f"删除文件失败: {error_detail}")
                
                # 如果是权限问题
                if last_resp.status_code == 400:
                    if "validation" in error_msg.lower() or "field" in error_msg.lower():
                        logger.warning(f"API格式验证失败，可能是端点或参数不正确: {file_token[:20]}...")
                    else:
                        logger.warning(f"可能是权限问题，文件已处理但未删除: {file_token[:20]}...")
                elif last_resp.status_code == 403:
                    logger.warning(f"权限不足，文件已处理但未删除: {file_token[:20]}...")
                    logger.warning(f"建议：申请 drive:drive 权限以支持删除文件功能")
            except:
                error_detail = f"HTTP {last_resp.status_code}, 响应文本: {last_resp.text[:200]}"
                logger.warning(f"删除文件失败: {error_detail}")
        else:
            error_detail = "未获取到任何响应"
            logger.warning(f"删除文件失败: {error_detail}")
        
        return False, error_detail
    except Exception as e:
        error_msg = f"删除文件异常: {e}"
        logger.error(error_msg, exc_info=True)
        return False, error_msg


def process_plugin_notification(notification: Dict[str, Any], config: Optional[Dict] = None) -> Dict[str, Any]:
    """
    处理插件通知：从飞书云空间拉取文件、处理、删除
    
    Args:
        notification: 解析后的通知信息
        config: 系统配置，如果为None则自动加载
    
    Returns:
        dict: 处理结果
        {
            "success": bool,
            "tool": str,
            "files_processed": int,
            "files_failed": int,
            "files_deleted": int,
            "errors": List[str]
        }
    """
    if config is None:
        config = load_system_config()
    
    # 标准化工具名称（兼容 greek_data 和 greeks_data）
    tool = normalize_tool_name(notification.get("tool"))
    timestamp = notification.get("timestamp", "")
    status = notification.get("status", "")
    files = notification.get("files", [])
    file_tokens = notification.get("file_tokens", {})  # 文件名 -> token 映射
    
    result = {
        "success": False,
        "tool": tool,
        "files_processed": 0,
        "files_failed": 0,
        "files_deleted": 0,
        "errors": []
    }
    
    # 如果状态不是success，不处理
    if status != "success":
        result["errors"].append(f"通知状态不是success: {status}")
        logger.warning(f"插件通知状态不是success，跳过处理: {status}")
        return result
    
    # 初始化FeishuAPI
    feishu_config = config.get('notification', {}).get('feishu_app', {})
    app_id = feishu_config.get('app_id')
    app_secret = feishu_config.get('app_secret')
    
    if not app_id or not app_secret:
        result["errors"].append("飞书应用凭证未配置")
        logger.error("飞书应用凭证未配置")
        return result
    
    feishu_api = FeishuAPI(app_id, app_secret)
    
    # 优先方法：对于 index_minute_data 和 etf_minute_data，参考 greeks_data 的处理方式
    # 先列出目录中的文件，然后匹配文件名，使用列表中的 token（更可靠）
    matched_files = []
    
    # 对于其他工具（如非 greeks_data），如果通知消息中包含文件token，直接使用token下载文件（跳过列出/搜索步骤）
    if tool != "greeks_data" and tool not in ["index_minute_data", "etf_minute_data"] and file_tokens and files:
        logger.info(f"通知消息中包含文件token，直接使用token下载文件（跳过列出/搜索步骤）")
        for filename in files:
            file_token = file_tokens.get(filename)
            if file_token:
                matched_files.append({
                    "name": filename,
                    "token": file_token
                })
                logger.info(f"使用文件token: {filename} -> {file_token[:20]}...")
            else:
                logger.warning(f"文件 {filename} 没有对应的token")
    
    # greeks_data：每次回调都按目录批量拉取，将 option_greeks 目录下所有 GREEKS_*.json 下载处理并删除
    # 参考 greeks_data 的处理方式，etf_minute_data 和 index_minute_data 也按目录批量拉取
    if tool == "greeks_data" or tool in ["index_minute_data", "etf_minute_data"]:
        try:
            folder_token = get_folder_token_for_tool(tool, config)
            if folder_token:
                logger.info(f"{tool}：全量列出目录下所有匹配文件: {folder_token}")
                all_files = feishu_api.list_files(folder_token)
                
                # 根据工具类型确定文件名模式
                if tool == "greeks_data":
                    matched_files = [
                        {"name": str(f.get("name", "")), "token": f.get("token", "")}
                        for f in (all_files or [])
                        if isinstance(f, dict)
                        and f.get("token")
                        and str(f.get("name", "")).upper().startswith("GREEKS_")
                        and str(f.get("name", "")).lower().endswith(".json")
                    ]
                elif tool == "index_minute_data":
                    matched_files = [
                        {"name": str(f.get("name", "")), "token": f.get("token", "")}
                        for f in (all_files or [])
                        if isinstance(f, dict)
                        and f.get("token")
                        and str(f.get("name", "")).lower().startswith("index_")
                        and str(f.get("name", "")).lower().endswith(".json")
                    ]
                elif tool == "etf_minute_data":
                    matched_files = [
                        {"name": str(f.get("name", "")), "token": f.get("token", "")}
                        for f in (all_files or [])
                        if isinstance(f, dict)
                        and f.get("token")
                        and str(f.get("name", "")).lower().startswith("etf_")
                        and str(f.get("name", "")).lower().endswith(".json")
                    ]
                
                logger.info(f"{tool}：目录扫描，共匹配到 {len(matched_files)} 个文件")
            else:
                logger.warning(f"{tool}：未找到对应的文件夹token，无法按目录批量拉取")
        except Exception as e:
            logger.warning(f"{tool}：按目录批量拉取失败，将回退原逻辑: {e}", exc_info=True)
    
    # greeks_data：按目录批量拉取（不依赖通知里的"文件列表"）
    # 需求：接收到 "GREEKS数据采集" 通知后，将 option_greeks 目录下的 GREEKS_*.json 全部下载处理并删除
    # 注意：如果通知中已经带有 file_tokens（例如通过 HTTP 回调传入），优先使用 file_tokens，不再强制按目录全量拉取
    if tool == "greeks_data" and not matched_files:
        try:
            folder_token = get_folder_token_for_tool(tool, config)
            if folder_token:
                logger.info(f"greeks_data：按目录批量拉取，列出文件夹: {folder_token}")
                all_files = feishu_api.list_files(folder_token)
                matched_files = [
                    {"name": f.get("name", ""), "token": f.get("token", "")}
                    for f in (all_files or [])
                    if isinstance(f, dict)
                    and f.get("token")
                    and str(f.get("name", "")).upper().startswith("GREEKS_")
                    and str(f.get("name", "")).lower().endswith(".json")
                ]
                logger.info(f"greeks_data：目录匹配到 {len(matched_files)} 个 GREEKS 文件")
            else:
                logger.warning("greeks_data：未找到 option_greeks 文件夹token，无法按目录批量拉取")
        except Exception as e:
            logger.warning(f"greeks_data：按目录批量拉取失败，将回退原逻辑: {e}", exc_info=True)
    
    # 备用方法：如果没有文件token，尝试列出或搜索文件
    if not matched_files:
        # 对 greeks_data 优先使用通知中自带的 file_token，避免依赖搜索接口（drive 搜索很多场景需要更高权限或不同 token 类型）
        if tool == "greeks_data" and file_tokens and files:
            logger.info("greeks_data：目录中未找到文件，使用通知中的 file_token 直接下载处理")
            for filename in files:
                file_token = file_tokens.get(filename)
                if file_token:
                    matched_files.append({
                        "name": filename,
                        "token": file_token
                    })
                    logger.info(f"使用通知中的 file_token: {filename} -> {file_token[:20]}...")
            
            # 如果通过 file_tokens 找到了文件，这里就不再继续走“列出/搜索”逻辑
            if matched_files:
                logger.info(f"greeks_data：通过通知中的 file_token 找到 {len(matched_files)} 个文件")
        # 如果依然没有 matched_files，才继续使用“列出 + 搜索”的兜底逻辑
        if not matched_files:
            # 获取文件夹token
            folder_token = get_folder_token_for_tool(tool, config)
            if not folder_token:
                result["errors"].append(f"未找到工具 {tool} 对应的文件夹token")
                logger.error(f"未找到工具 {tool} 对应的文件夹token")
                return result
            
            # 尝试列出文件夹中的所有文件
            logger.info(f"列出文件夹文件: {folder_token}")
            all_files = feishu_api.list_files(folder_token)
            
            if all_files:
                # 方法1: 如果能列出文件，使用文件列表匹配
                # 根据工具类型确定文件名模式
                tool_patterns = {
                    "greeks_data": "GREEKS_",
                    "index_minute_data": "index_",
                    "etf_minute_data": "etf_"
                }
                
                pattern = tool_patterns.get(tool, "")
                if pattern:
                    matched_files = find_files_by_pattern(all_files, pattern, timestamp)
                    logger.info(f"从文件列表中找到 {len(matched_files)} 个匹配的文件")
            
            # 方法2: 如果无法列出文件（权限问题）或未找到匹配文件，根据通知消息中的文件名直接搜索
            if not matched_files and files:
                logger.info(f"无法列出文件或未找到匹配文件，尝试根据通知消息中的文件名直接搜索")
                for filename in files:
                    # 如果文件名是描述性文本（如"GREEKS_2个合约"），根据工具类型和时间戳生成实际文件名
                    if tool == "greeks_data" and ("个合约" in filename or not filename.endswith(".json")):
                        if timestamp:
                            filename = f"GREEKS_{timestamp}.json"
                            logger.info(f"根据时间戳生成文件名: {filename}")
                    
                    # 使用文件搜索API查找文件
                    file_meta = feishu_api.get_file_meta_by_name(folder_token, filename)
                    if file_meta:
                        matched_files.append(file_meta)
                        logger.info(f"通过搜索找到文件: {filename}")
                    else:
                        logger.warning(f"无法找到文件: {filename}")
    
    if not matched_files:
        error_msg = f"未找到匹配的文件"
        if files:
            error_msg += f" (通知中的文件: {', '.join(files)})"
        if timestamp:
            error_msg += f" (时间戳: {timestamp})"
        result["errors"].append(error_msg)
        logger.warning(error_msg)
        return result
    
    logger.info(f"最终找到 {len(matched_files)} 个匹配的文件")
    
    # 处理每个文件
    processed_files = []
    failed_files = []
    
    for file_info in matched_files:
        file_name = file_info.get('name', '')
        file_token = file_info.get('token', '')
        
        if not file_token:
            continue
        
        try:
            logger.info(f"处理文件: {file_name} (token: {file_token[:20]}...)")
            
            # 下载文件
            file_content = feishu_api.download_file(file_token)
            if not file_content:
                logger.error(f"下载文件失败: {file_name}")
                failed_files.append(file_name)
                result["files_failed"] += 1
                continue
            
            # 解析JSON内容
            try:
                content_dict = json.loads(file_content.decode('utf-8'))
            except json.JSONDecodeError as e:
                logger.error(f"解析JSON失败: {file_name}, 错误: {e}")
                failed_files.append(file_name)
                result["files_failed"] += 1
                continue
            
            # 根据工具类型调用对应的处理函数
            process_success = False
            process_error = None
            try:
                if tool == "greeks_data":
                    process_success = process_option_greeks_data(content_dict, file_name)
                elif tool == "index_minute_data":
                    process_success = process_index_minute_data(content_dict, file_name)
                elif tool == "etf_minute_data":
                    process_success = process_etf_minute_data(content_dict, file_name)
                else:
                    logger.warning(f"未知的工具类型: {tool}, 文件: {file_name}")
                    process_error = f"未知的工具类型: {tool}"
            except Exception as e:
                process_error = f"处理函数异常: {type(e).__name__}: {str(e)}"
                logger.error(f"调用处理函数异常: {file_name}, 工具={tool}, 错误={process_error}", exc_info=True)
            
            if process_success:
                logger.info(f"文件处理成功: {file_name}")
                processed_files.append(file_info)
                result["files_processed"] += 1
                
                # 删除已处理的文件
                delete_success, delete_error = delete_file_from_feishu(feishu_api, file_token)
                if delete_success:
                    result["files_deleted"] += 1
                    logger.info(f"文件已删除: {file_name}")
                else:
                    logger.warning(f"文件删除失败: {file_name}, 错误: {delete_error}")
            else:
                error_msg = f"文件处理失败: {file_name}"
                if process_error:
                    error_msg += f", 原因: {process_error}"
                else:
                    error_msg += f", 工具={tool}, 处理函数返回False"
                logger.error(error_msg)
                failed_files.append(file_name)
                result["files_failed"] += 1
                if process_error:
                    result["errors"].append(f"{file_name}: {process_error}")
                
        except Exception as e:
            logger.error(f"处理文件异常: {file_name}, {e}", exc_info=True)
            failed_files.append(file_name)
            result["files_failed"] += 1
            result["errors"].append(f"{file_name}: {str(e)}")
    
    result["success"] = result["files_processed"] > 0
    
    logger.info(
        f"插件通知处理完成: 工具={tool}, "
        f"处理成功={result['files_processed']}, "
        f"处理失败={result['files_failed']}, "
        f"删除={result['files_deleted']}"
    )
    
    return result


def handle_plugin_notification_message(message_data: Dict[str, Any]) -> Optional[str]:
    """
    处理插件通知消息（用于注册到 FeishuAppBot）
    
    Args:
        message_data: 飞书消息数据
    
    Returns:
        str: 回复消息，如果无法处理返回None
    """
    try:
        # 提取消息内容
        event = message_data.get('event', {})
        message = event.get('message', {})
        
        # 处理content字段
        content_raw = message.get('content', '{}')
        if isinstance(content_raw, str):
            try:
                content = json.loads(content_raw)
            except json.JSONDecodeError:
                content = {}
        elif isinstance(content_raw, dict):
            content = content_raw
        else:
            content = {}
        
        text = content.get('text', '').strip()
        
        # 解析插件通知
        notification = parse_plugin_notification(text)
        if not notification:
            return None  # 不是插件通知，返回None让其他处理器处理
        
        logger.info(f"收到插件通知: 工具={notification['tool']}, 状态={notification['status']}")
        
        # 处理通知
        result = process_plugin_notification(notification)
        
        # 生成回复消息
        if result["success"]:
            reply = (
                f"✅ 插件通知处理成功\n"
                f"工具: {result['tool']}\n"
                f"处理成功: {result['files_processed']} 个文件\n"
                f"处理失败: {result['files_failed']} 个文件\n"
                f"已删除: {result['files_deleted']} 个文件"
            )
        else:
            errors_str = "\n".join(result["errors"][:3])  # 只显示前3个错误
            reply = (
                f"❌ 插件通知处理失败\n"
                f"工具: {result['tool']}\n"
                f"错误: {errors_str}"
            )
        
        return reply
        
    except Exception as e:
        logger.error(f"处理插件通知消息失败: {e}", exc_info=True)
        return f"处理插件通知时出错: {str(e)}"
