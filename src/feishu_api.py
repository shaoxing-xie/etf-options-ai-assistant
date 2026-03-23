"""
飞书API工具模块
提供飞书云文档的上传、下载、列表等操作
"""

import requests
import json
from typing import Optional, Dict, List
from datetime import datetime
from src.logger_config import get_module_logger

logger = get_module_logger(__name__)


class FeishuAPI:
    """飞书API封装类"""
    
    def __init__(self, app_id: str, app_secret: str):
        """
        初始化飞书API客户端
        
        Args:
            app_id: 飞书应用ID
            app_secret: 飞书应用密钥
        """
        self.app_id = app_id
        self.app_secret = app_secret
        self.tenant_token = None
        self.token_expire_time = None
    
    def get_tenant_token(self, force_refresh: bool = False) -> Optional[str]:
        """
        获取飞书访问token（带缓存）
        
        Args:
            force_refresh: 是否强制刷新token
        
        Returns:
            str: 访问token，失败返回None
        """
        # 如果token未过期且不强制刷新，直接返回
        if not force_refresh and self.tenant_token and self.token_expire_time:
            # token_expire_time 是 timestamp (float)，需要与 datetime.now().timestamp() 比较
            if datetime.now().timestamp() < self.token_expire_time:
                return self.tenant_token
        
        try:
            url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
            
            # 尝试强制使用 IPv4（解决 DNS 解析但连接失败的问题）
            import socket
            import urllib3
            from urllib3.util.connection import create_connection
            
            # 保存原始的 create_connection
            original_create_connection = create_connection
            
            def patched_create_connection(address, *args, **kwargs):
                """强制使用 IPv4"""
                host, port = address
                try:
                    # 强制使用 IPv4
                    family = socket.AF_INET
                    return original_create_connection((host, port), *args, family=family, **kwargs)
                except Exception:
                    # 如果失败，使用原始方法
                    return original_create_connection(address, *args, **kwargs)
            
            # 临时替换 create_connection
            urllib3.util.connection.create_connection = patched_create_connection
            
            try:
                resp = requests.post(url, json={
                    "app_id": self.app_id,
                    "app_secret": self.app_secret
                }, timeout=10)
            finally:
                # 恢复原始的 create_connection
                urllib3.util.connection.create_connection = original_create_connection
            
            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == 0:
                    self.tenant_token = data.get("tenant_access_token")
                    # token有效期2小时，提前5分钟刷新
                    expire_seconds = data.get("expire", 7200) - 300
                    self.token_expire_time = datetime.now().timestamp() + expire_seconds
                    logger.debug("飞书访问token获取成功")
                    return self.tenant_token
                else:
                    logger.error(f"获取飞书token失败: {data.get('msg', '未知错误')}")
            else:
                logger.error(f"获取飞书token失败: HTTP {resp.status_code}")
            return None
        except Exception as e:
            logger.error(f"获取飞书token异常: {e}", exc_info=True)
            return None
    
    def list_files(self, folder_token: str) -> List[Dict]:
        """
        列出文件夹中的文件
        
        Args:
            folder_token: 文件夹token
        
        Returns:
            List[Dict]: 文件列表，每个元素包含name、token、modified_time等信息
        """
        token = self.get_tenant_token()
        if not token:
            return []
        
        try:
            # 使用 drive/v1/files 接口获取文件夹中的文件清单
            # 官方文档：https://go.feishu.cn/s/6aCQJ_55A0s
            url = "https://open.feishu.cn/open-apis/drive/v1/files"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=utf-8",
            }
            params = {
                # 目标文件夹 token（必填）
                "folder_token": folder_token,
                # 单页返回数量（官方最大 200，这里取 100 做折中）
                "page_size": 100,
            }

            all_files: List[Dict] = []
            page_token: Optional[str] = None

            while True:
                if page_token:
                    params["page_token"] = page_token

                resp = requests.get(url, headers=headers, params=params, timeout=10)

                if resp.status_code != 200:
                    # HTTP 层面失败，尽量打印出飞书返回的详细错误，方便排查权限/参数问题
                    try:
                        error_data = resp.json()
                        logger.error(
                            f"列出文件失败: HTTP {resp.status_code}, "
                            f"folder_token={folder_token}, "
                            f"响应={json.dumps(error_data, ensure_ascii=False)[:500]}"
                        )
                    except Exception:
                        logger.error(
                            f"列出文件失败: HTTP {resp.status_code}, "
                            f"folder_token={folder_token}, "
                            f"响应文本={resp.text[:500]}"
                        )
                    break

                try:
                    data = resp.json()
                except Exception:
                    logger.error(
                        f"列出文件失败：响应非JSON格式, folder_token={folder_token}, 文本={resp.text[:300]}"
                    )
                    break

                if data.get("code") != 0:
                    error_msg = data.get("msg", "未知错误")
                    error_code = data.get("code", "未知")
                    logger.error(
                        f"列出文件失败: code={error_code}, msg={error_msg}, "
                        f"folder_token={folder_token}, 响应={json.dumps(data, ensure_ascii=False)[:500]}"
                    )
                    break

                files = data.get("data", {}).get("files", [])
                all_files.extend(files)

                has_more = data.get("data", {}).get("has_more", False)
                if not has_more:
                    break

                page_token = data.get("data", {}).get("next_page_token")
                if not page_token:
                    break

            logger.info(f"列出文件完成: folder_token={folder_token}, 共 {len(all_files)} 个条目")
            return all_files

        except Exception as e:
            logger.error(f"列出文件异常: {e}", exc_info=True)
            return []
    
    def get_file_meta_by_name(self, folder_token: str, filename: str) -> Optional[Dict]:
        """
        根据文件名获取文件元数据（通过搜索API）

        注意：
        - 当前实现使用云文档搜索接口按文件名全局搜索，不强制限定在某个文件夹下；
        - folder_token 目前仅用于日志，后续若需要限定目录，可根据飞书最新文档补充相应字段。
        
        Args:
            folder_token: 文件夹token（可选，用于日志和未来扩展）
            filename: 文件名
        
        Returns:
            Dict: 文件元数据，包含token、name等信息，失败返回None
        """
        token = self.get_tenant_token()
        if not token:
            return None
        
        try:
            # 使用文件搜索API（按最新文档字段命名：query / page_size 等）
            # 参考：云文档搜索接口 drive/v1/files/search
            url = "https://open.feishu.cn/open-apis/drive/v1/files/search"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
            data = {
                # 搜索关键词 —— 使用完整文件名，后续再做精确匹配
                "query": filename,
                # 每页数量
                "page_size": 10
                # 如需按目录限定搜索范围，可根据最新文档补充：ancestor_token / parent_folder_token 等字段
            }
            
            logger.info(
                f"搜索文件元数据: filename='{filename}', folder_token='{folder_token}'"
            )
            
            resp = requests.post(url, headers=headers, json=data, timeout=10)
            
            if resp.status_code == 200:
                try:
                    result = resp.json()
                except Exception:
                    logger.error(f"搜索文件失败：响应非JSON格式，文本={resp.text[:300]}")
                    return None

                if result.get("code") == 0:
                    files = result.get("data", {}).get("files", [])
                    # 查找完全匹配的文件名
                    for file_info in files:
                        if file_info.get("name") == filename:
                            logger.debug(
                                f"找到文件: {filename}, token: {file_info.get('token', '')[:20]}..."
                            )
                            return file_info
                    logger.warning(f"未在搜索结果中找到完全匹配的文件: {filename}")
                else:
                    error_msg = result.get("msg", "未知错误")
                    error_code = result.get("code", "未知")
                    logger.error(
                        f"搜索文件失败: code={error_code}, msg={error_msg}, "
                        f"filename='{filename}', folder_token='{folder_token}'"
                    )
            else:
                # 非 200 时尽量打印出飞书返回的具体错误信息，便于排查 400/403 等问题
                try:
                    error_body = resp.json()
                    error_msg = error_body.get("msg", "未知错误")
                    error_code = error_body.get("code", "未知")
                    logger.error(
                        f"搜索文件失败: HTTP {resp.status_code}, "
                        f"code={error_code}, msg={error_msg}, "
                        f"filename='{filename}', folder_token='{folder_token}', "
                        f"响应={json.dumps(error_body, ensure_ascii=False)[:500]}"
                    )
                except Exception:
                    logger.error(
                        f"搜索文件失败: HTTP {resp.status_code}, "
                        f"filename='{filename}', folder_token='{folder_token}', "
                        f"响应文本={resp.text[:500]}"
                    )
            return None
        except Exception as e:
            logger.error(f"搜索文件异常: {e}", exc_info=True)
            return None
    
    def download_file(self, file_token: str) -> Optional[bytes]:
        """
        下载文件内容
        
        Args:
            file_token: 文件token
        
        Returns:
            bytes: 文件内容，失败返回None
        """
        token = self.get_tenant_token()
        if not token:
            return None
        
        try:
            url = f"https://open.feishu.cn/open-apis/drive/v1/files/{file_token}/download"
            headers = {
                "Authorization": f"Bearer {token}"
            }
            
            resp = requests.get(url, headers=headers, timeout=30)
            
            if resp.status_code == 200:
                # 飞书下载接口可能返回两种格式：
                # 1. 包含 download_url 的重定向响应（code=0）
                # 2. 直接返回文件内容（JSON格式）
                try:
                    data = resp.json()
                except Exception as e:
                    # 如果不是JSON，可能是二进制文件，直接返回内容
                    logger.debug("响应不是JSON，直接返回二进制内容")
                    logger.debug(f"响应 JSON 解析失败: {e}", exc_info=True)
                    return resp.content
                
                # 检查是否是标准的飞书API响应格式（包含code字段）
                if "code" in data:
                    if data.get("code") == 0:
                        # 标准格式：包含download_url
                        download_url = data.get("data", {}).get("download_url")
                        if download_url:
                            # 使用重定向URL下载实际文件
                            file_resp = requests.get(download_url, timeout=30)
                            if file_resp.status_code == 200:
                                logger.debug(f"下载文件成功: {file_token}")
                                return file_resp.content
                            else:
                                logger.error(f"使用下载URL下载文件失败: HTTP {file_resp.status_code}, URL: {download_url[:100]}...")
                        else:
                            logger.error(f"下载URL为空，响应数据: {json.dumps(data, ensure_ascii=False)}")
                    else:
                        error_msg = data.get('msg', '未知错误')
                        error_code = data.get('code', '未知')
                        logger.error(f"获取下载URL失败: code={error_code}, msg={error_msg}, 响应={json.dumps(data, ensure_ascii=False)}")
                else:
                    # 直接返回文件内容（JSON格式），没有code字段
                    # 将JSON内容编码为bytes返回
                    logger.debug("API直接返回文件内容（JSON格式），无需重定向")
                    file_content = json.dumps(data, ensure_ascii=False).encode('utf-8')
                    return file_content
            else:
                try:
                    error_data = resp.json()
                    error_msg = error_data.get('msg', '未知错误')
                    error_code = error_data.get('code', '未知')
                    logger.error(f"下载文件失败: HTTP {resp.status_code}, code={error_code}, msg={error_msg}, 响应={json.dumps(error_data, ensure_ascii=False)}")
                    
                    # 如果是404，可能是文件不存在或token无效
                    if resp.status_code == 404:
                        logger.error(f"文件可能不存在或token无效: file_token={file_token[:20]}...")
                        logger.error("请检查：1) 文件是否已被删除 2) 文件token是否正确 3) 应用是否有访问该文件的权限")
                except Exception as e:
                    logger.error(f"下载文件失败: HTTP {resp.status_code}, 响应文本: {resp.text[:500]}; 解析错误: {e}")
                    if resp.status_code == 404:
                        logger.error(f"文件可能不存在或token无效: file_token={file_token[:20]}...")
            return None
            
        except Exception as e:
            logger.error(f"下载文件异常: {e}", exc_info=True)
            return None
    
    def upload_file(self, folder_token: str, filename: str, content: Dict) -> Dict:
        """
        上传文件到飞书云文档
        
        Args:
            folder_token: 文件夹token
            filename: 文件名
            content: 文件内容（字典）
        
        Returns:
            Dict: 上传结果 {"success": bool, "file_token": str, "message": str}
        """
        token = self.get_tenant_token()
        if not token:
            return {"success": False, "message": "获取访问token失败"}
        
        try:
            url = "https://open.feishu.cn/open-apis/drive/v1/files/upload_all"
            
            headers = {
                "Authorization": f"Bearer {token}"
            }
            
            # 将内容转换为JSON字符串
            json_content = json.dumps(content, ensure_ascii=False, indent=2)
            file_content = json_content.encode('utf-8')
            file_size = len(file_content)  # 计算文件大小（字节）
            
            # 根据飞书文档要求，构建multipart/form-data请求
            # 注意：Content-Type 必须是 multipart/form-data（requests会自动处理）
            files = {
                "file": (filename, file_content, "application/json")
            }
            
            # 必填参数（根据飞书文档和AI解决方案）
            # 注意：根据飞书文档，云空间上传应使用 "explorer"
            # 如果 "explorer" 返回 403，再尝试 "drive"（企业版）
            data = {
                "file_name": filename,  # 文件名（字符串）
                "parent_type": "explorer",  # 云空间使用 "explorer"，企业版使用 "drive"
                "parent_node": folder_token,  # 目标文件夹token（字符串）
                "size": file_size  # 文件大小（int类型，单位字节），必填！不能为0，不能有空格
            }
            
            # 验证 size 参数（确保是正整数）
            if file_size <= 0:
                logger.error(f"文件大小无效: {file_size}，必须大于0")
                return {"success": False, "message": f"文件大小无效: {file_size}"}
            
            # 记录请求参数（用于调试）
            logger.info("上传文件参数详情:")
            logger.info(f"  file_name: '{filename}' (type: {type(filename).__name__})")
            logger.info(f"  parent_type: '{data['parent_type']}' (type: {type(data['parent_type']).__name__})")
            logger.info(f"  parent_node: '{folder_token}' (type: {type(folder_token).__name__}, length: {len(folder_token)})")
            logger.info(f"  size: {file_size} (type: {type(file_size).__name__})")
            logger.info(f"  file_content: {len(file_content)} bytes (type: {type(file_content).__name__})")
            
            resp = requests.post(url, headers=headers, files=files, data=data, timeout=30)
            
            if resp.status_code == 200:
                result = resp.json()
                if result.get("code") == 0:
                    file_token = result.get("data", {}).get("file_token")
                    logger.info(f"上传文件成功: {filename} -> {file_token}")
                    return {"success": True, "file_token": file_token}
                else:
                    msg = result.get("msg", "上传失败")
                    logger.error(f"上传文件失败: {filename}, {msg}")
                    return {"success": False, "message": msg}
            else:
                # 记录完整的响应体，便于调试
                try:
                    error_body = resp.text
                    logger.error(f"上传文件失败: {filename}, HTTP {resp.status_code}, 响应: {error_body}")
                    # 尝试解析错误JSON
                    try:
                        error_json = resp.json()
                        error_msg = error_json.get("msg", "上传失败")
                        error_code = error_json.get("code", "")
                        return {"success": False, "message": f"HTTP {resp.status_code}: {error_msg} (code={error_code})"}
                    except Exception as e:
                        logger.debug(f"响应 JSON 解析失败: {e}", exc_info=True)
                        return {"success": False, "message": f"HTTP {resp.status_code}: {error_body[:200]}"}
                except Exception as e:
                    logger.debug(f"读取响应失败: {e}", exc_info=True)
                    return {"success": False, "message": f"HTTP {resp.status_code}"}
                
        except Exception as e:
            logger.error(f"上传文件异常: {filename}, {e}", exc_info=True)
            return {"success": False, "message": str(e)}
    
    def read_contract_list(self, file_path: str) -> Optional[Dict]:
        """
        从飞书云文档读取期权合约清单
        
        Args:
            file_path: 文件路径（如 "/行情数据/配置文件/期权合约清单.json"）
        
        Returns:
            Dict: 合约清单数据，失败返回None
        """
        # 这里需要先根据路径找到文件token，然后下载
        # 简化实现：假设file_path是文件token或需要先解析路径
        # 实际使用时，可能需要先列出文件夹找到对应文件
        logger.warning("read_contract_list功能需要根据实际路径解析实现")
        return None
