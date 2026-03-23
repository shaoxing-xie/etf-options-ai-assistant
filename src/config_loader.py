"""
配置加载模块
支持多种配置方式：配置文件、环境变量、命令行参数、WEB界面
包含配置缓存机制，支持实时生效
"""

import os
import argparse
from pathlib import Path
from typing import Dict, Optional, Any, List
from datetime import datetime
from time import time
from copy import deepcopy

# 在解析 ${VAR} 或 os.getenv 之前加载项目根目录的 .env
try:
    from dotenv import load_dotenv  # type: ignore[import-not-found]
    _project_root = Path(__file__).resolve().parents[1]
    _env_file = _project_root / ".env"
    if _env_file.exists():
        load_dotenv(_env_file)
except ImportError:
    pass  # python-dotenv 未安装时，依赖父进程传入的 env

import yaml

from src.logger_config import get_module_logger

logger = get_module_logger(__name__)

# -------- env placeholder resolution --------
def _resolve_env_placeholders(obj: Any) -> Any:
    """
    Recursively resolve ${ENV_VAR} placeholders in config objects.

    - If a string equals "${FOO}", replace with os.getenv("FOO").
    - If env var is missing/empty, return None (so defaults/overrides can apply).
    """
    if isinstance(obj, dict):
        return {k: _resolve_env_placeholders(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_env_placeholders(v) for v in obj]
    if isinstance(obj, str):
        s = obj.strip()
        if s.startswith("${") and s.endswith("}") and len(s) > 3 and s.count("${") == 1:
            key = s[2:-1].strip()
            val = os.getenv(key, "").strip()
            return val if val else None
        return obj
    return obj

# 配置缓存（用于实时生效）
_config_cache: Optional[Dict] = None
_config_cache_time: Optional[float] = None
_config_cache_ttl: int = 60  # 缓存有效期60秒

# 系统配置缓存
_system_config_cache: Optional[Dict] = None
_system_config_cache_time: Optional[float] = None
_system_config_cache_ttl: int = 30  # 系统配置缓存有效期30秒


def get_default_config() -> Dict[str, Any]:
    """
    获取默认配置
    
    Returns:
        dict: 默认配置字典
    """
    return {
        'option_contracts': {
            'current_month': None,
            'underlying': '510300',
            'call_contract': {
                'contract_code': None,
                'strike_price': None,
                'expiry_date': None  # 新增：到期日期
            },
            'put_contract': {
                'contract_code': None,
                'strike_price': None,
                'expiry_date': None  # 新增：到期日期
            },
            'underlyings': []  # 默认空列表，用户配置会覆盖
        },
        'notification': {
            'feishu_webhook': None,
            'sms': {
                'enabled': False,
                'phone_numbers': []
            }
        },
        'logging': {
            'level': 'INFO',
            'console': True,
            'file': True
        },
        'trading_hours': {
            'morning_start': '09:30',
            'morning_end': '11:30',
            'afternoon_start': '13:00',
            'afternoon_end': '15:00'
        }
    }


def merge_config(default: Dict, user: Dict) -> Dict:
    """
    合并默认配置和用户配置
    
    Args:
        default: 默认配置
        user: 用户配置
    
    Returns:
        dict: 合并后的配置
    """
    result = default.copy()
    
    for key, value in user.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            # 递归合并字典
            # 特殊处理：如果合并 option_contracts，添加调试信息
            if key == 'option_contracts':
                logger.debug("merge_config: 合并 option_contracts")
                if 'underlyings' in result[key]:
                    logger.debug(f"merge_config: 默认配置 underlyings 长度: {len(result[key]['underlyings'])}")
                if 'underlyings' in value:
                    logger.debug(f"merge_config: 用户配置 underlyings 长度: {len(value['underlyings'])}")
            result[key] = merge_config(result[key], value)
            # 合并后检查
            if key == 'option_contracts' and 'underlyings' in result[key]:
                logger.debug(f"merge_config: 合并后 underlyings 长度: {len(result[key]['underlyings'])}")
        elif key in result and isinstance(result[key], list) and isinstance(value, list):
            # 列表类型：直接使用用户配置（不合并）
            # 特殊处理：如果合并 underlyings，添加调试信息
            if key == 'underlyings':
                logger.debug(f"merge_config: 合并 underlyings 列表，用户配置长度: {len(value)}")
            result[key] = value
        else:
            # 直接使用用户配置的值（包括列表、None等）
            result[key] = value
    
    return result


def load_system_config(config_path: str = "config.yaml", use_cache: bool = True) -> Dict[str, Any]:
    """
    加载完整系统配置（统一配置管理）
    
    Args:
        config_path: 配置文件路径
        use_cache: 是否使用缓存（默认True，减少频繁加载）
    
    Returns:
        dict: 系统配置字典
    """
    global _system_config_cache, _system_config_cache_time
    
    try:
        # 检查缓存（如果启用且缓存有效）
        if use_cache and _system_config_cache is not None and _system_config_cache_time is not None:
            if time() - _system_config_cache_time < _system_config_cache_ttl:
                logger.debug(f"使用缓存的系统配置（缓存时间: {int(time() - _system_config_cache_time)}秒）")
                # 使用深拷贝，确保返回的配置不会被修改
                return deepcopy(_system_config_cache)
        
        logger.debug(f"开始加载系统配置: {config_path}")
        
        # 获取默认配置
        default_config = get_default_config()
        
        # 从配置文件加载（如果存在）
        user_config: Dict[str, Any] = {}
        config_file = Path(config_path)
        
        # 如果配置文件不存在，尝试在项目根目录查找
        if not config_file.exists():
            # 尝试从当前文件位置向上查找项目根目录
            current_file = Path(__file__).resolve()
            # src/config_loader.py -> 项目根目录
            project_root = current_file.parents[1]
            config_file = project_root / config_path
            logger.debug(f"配置文件不存在于当前路径，尝试项目根目录: {config_file}")
        
        if config_file.exists():
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    user_config = yaml.safe_load(f) or {}
                # 解析 ${ENV_VAR} 占位符，避免真实密钥写入 config.yaml
                user_config = _resolve_env_placeholders(user_config) or {}
                logger.debug(f"成功加载配置文件: {config_path}")
                # 调试：检查 YAML 解析后的 underlyings
                if 'option_contracts' in user_config:
                    oc = user_config['option_contracts']
                    if 'underlyings' in oc:
                        ul = oc['underlyings']
                        logger.info(f"YAML 解析后: option_contracts.underlyings 类型={type(ul)}, 长度={len(ul) if isinstance(ul, list) else 'N/A'}")
                        if isinstance(ul, list) and ul:
                            for i, u in enumerate(ul, 1):
                                logger.info(f"YAML 解析后: 标的物 {i}/{len(ul)}: underlying={u.get('underlying', 'N/A')}, call={len(u.get('call_contracts', []))}, put={len(u.get('put_contracts', []))}")
                        elif isinstance(ul, list) and not ul:
                            logger.warning("YAML 解析后: option_contracts.underlyings 是空列表！")
            except Exception as e:
                logger.error(f"加载配置文件失败: {config_path} | 错误: {str(e)}", exc_info=True)
                logger.warning("使用默认配置")
        else:
            logger.warning(f"配置文件不存在: {config_path}，使用默认配置")
        
        # 合并配置
        config = merge_config(default_config, user_config)
        
        # 调试：检查 option_contracts.underlyings 是否正确加载
        if 'option_contracts' in config:
            oc = config['option_contracts']
            if 'underlyings' in oc:
                ul = oc['underlyings']
                logger.info(f"配置加载后: option_contracts.underlyings 类型={type(ul)}, 长度={len(ul) if isinstance(ul, list) else 'N/A'}")
                if isinstance(ul, list) and ul:
                    for i, u in enumerate(ul, 1):
                        logger.info(f"配置加载后: 标的物 {i}/{len(ul)}: underlying={u.get('underlying', 'N/A')}, call={len(u.get('call_contracts', []))}, put={len(u.get('put_contracts', []))}")
                elif isinstance(ul, list) and not ul:
                    logger.warning("配置加载后: option_contracts.underlyings 是空列表！检查原始配置...")
                    # 检查原始用户配置
                    if 'option_contracts' in user_config:
                        user_oc = user_config['option_contracts']
                        if 'underlyings' in user_oc:
                            user_ul = user_oc['underlyings']
                            logger.warning(f"原始用户配置中 underlyings 类型={type(user_ul)}, 长度={len(user_ul) if isinstance(user_ul, list) else 'N/A'}")
        
        # 更新缓存（使用深拷贝，确保缓存不会被修改）
        _system_config_cache = deepcopy(config)
        _system_config_cache_time = time()
        
        logger.debug("系统配置加载完成")
        # 返回深拷贝，确保调用者修改配置不会影响缓存
        return deepcopy(config)
        
    except Exception as e:
        logger.error(f"加载系统配置时发生错误: {str(e)}", exc_info=True)
        return get_default_config()


def get_trading_hours_config(config: Dict) -> Dict:
    """
    获取交易时间配置（优先 system.trading_hours，兼容顶层 trading_hours）
    """
    default = {
        'morning_start': '09:30',
        'morning_end': '11:30',
        'afternoon_start': '13:00',
        'afternoon_end': '15:00'
    }
    system_th = config.get('system', {}).get('trading_hours', {})
    if system_th:
        return {**default, **system_th}
    return config.get('trading_hours', default)


def get_holidays_config(config: Dict) -> set:
    """
    获取节假日配置（非交易日）
    
    Args:
        config: 系统配置字典
    
    Returns:
        set: 节假日日期集合（格式：YYYYMMDD字符串）
    """
    holidays_set = set()
    
    try:
        trading_hours = config.get('system', {}).get('trading_hours', {})
        holidays_config = trading_hours.get('holidays', {})
        
        # 支持按年份组织：holidays: {2026: [...]}
        if isinstance(holidays_config, dict):
            for year, dates in holidays_config.items():
                if isinstance(dates, list):
                    for date in dates:
                        if isinstance(date, str) and len(date) == 8 and date.isdigit():
                            holidays_set.add(date)
        
        # 也支持扁平列表：holidays: [...]
        elif isinstance(holidays_config, list):
            for date in holidays_config:
                if isinstance(date, str) and len(date) == 8 and date.isdigit():
                    holidays_set.add(date)
        
        logger.debug(f"从配置加载了 {len(holidays_set)} 个节假日")
        
    except Exception as e:
        logger.warning(f"读取节假日配置失败: {e}，使用空集合")
    
    return holidays_set


def get_data_storage_config(config: Dict) -> Dict:
    """
    获取数据存储配置
    
    Args:
        config: 系统配置字典
    
    Returns:
        dict: 数据存储配置
    """
    # 从system.data_storage获取，如果没有则使用默认值
    system_config = config.get('system', {})
    data_storage = system_config.get('data_storage', {})

    # 默认数据根目录：统一使用 etf-options-ai-assistant/data（新系统根目录）
    default_root = Path.home() / "etf-options-ai-assistant"
    DEFAULT_DATA_DIR = str((default_root / "data").resolve())

    # 如果data_storage为空，使用默认配置（基于 DEFAULT_DATA_DIR）
    if not data_storage:
        return {
            'data_dir': DEFAULT_DATA_DIR,
            'volatility_ranges': {
                'enabled': True,
                'dir': f'{DEFAULT_DATA_DIR}/volatility_ranges',
                'file_format': 'json'
            },
            'trend_analysis': {
                'enabled': True,
                'dir': f'{DEFAULT_DATA_DIR}/trend_analysis',
                'after_close_dir': f'{DEFAULT_DATA_DIR}/trend_analysis/after_close',
                'before_open_dir': f'{DEFAULT_DATA_DIR}/trend_analysis/before_open'
            },
            'signals': {
                'enabled': True,
                'dir': f'{DEFAULT_DATA_DIR}/signals'
            }
        }

    # 如果用户配置了相对 data_dir（例如 "data"），则解释为相对于 etf-options-ai-assistant 根目录
    merged = dict(data_storage)
    data_dir = str(merged.get('data_dir', DEFAULT_DATA_DIR))
    if not data_dir.startswith("/"):
        # 优先锚定到 etf-options-ai-assistant 根目录，保证根目录稳定
        base_dir = default_root if default_root.exists() else Path.cwd()
        data_dir = str((base_dir / data_dir).resolve())
    merged['data_dir'] = data_dir

    return merged


def get_scheduler_config(config: Dict) -> Dict:
    """
    获取定时任务配置
    
    Args:
        config: 系统配置字典
    
    Returns:
        dict: 定时任务配置
    """
    # 从system.scheduler获取，如果没有则使用默认值
    system_config = config.get('system', {})
    scheduler_config = system_config.get('scheduler', {})
    
    # 如果scheduler为空，使用默认配置
    if not scheduler_config:
        return {
            'after_close_analysis': {
                'enabled': True,
                'hour': 15,
                'minute': 30
            },
            'before_open_analysis': {
                'enabled': True,
                'hour': 9,
                'minute': 15
            },
            'first_intraday_analysis': {
                'enabled': True,
                'hour': 9,
                'minute': 28
            },
            'intraday_volatility_range': {
                'enabled': True,
                'interval_minutes': 15
            },
            'signal_generation': {
                'enabled': True,
                'interval_minutes': 5
            }
        }
    
    return scheduler_config


def load_contract_config(config_path: str = "config.yaml", use_cache: bool = True) -> Dict[str, Any]:
    """
    加载期权合约配置（支持多标的物）
    支持多种方式：配置文件、环境变量、命令行参数、WEB界面
    用户只需指定行权价，程序自动查找对应合约代码
    
    Args:
        config_path: 配置文件路径
        use_cache: 是否使用缓存（默认True，WEB界面更新后会自动清除缓存）
    
    Returns:
        dict: {
            'underlyings': [  # 多标的物配置（新格式）
                {
                    'underlying': str,  # 标的代码
                    'call_contracts': [...],
                    'put_contracts': [...]
                },
                ...
            ],
            'current_month': str,  # 当前月份 YYYYMM
            # 向后兼容字段（第一个标的物）
            'underlying': str,
            'call_contracts': [...],
            'put_contracts': [...]
        }
    """
    global _config_cache, _config_cache_time
    
    try:
        logger.debug(f"加载合约配置: config_path={config_path}, use_cache={use_cache}")
        
        # 检查缓存（如果启用且缓存有效）
        if use_cache and _config_cache is not None and _config_cache_time is not None:
            if time() - _config_cache_time < _config_cache_ttl:
                logger.debug("使用缓存的合约配置")
                return _config_cache.copy()
        
        config = {}
        
        # 1. 从配置文件加载（如果存在）
        config_file = Path(config_path)
        if config_file.exists():
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    file_config = yaml.safe_load(f)
                    if file_config and 'option_contracts' in file_config:
                        opt_config = file_config['option_contracts']
                        config['current_month'] = opt_config.get('current_month')
                        
                        # 支持多标的物配置（新格式）
                        underlyings_list = opt_config.get('underlyings', [])
                        
                        if underlyings_list:
                            # 新格式：多标的物配置
                            config['underlyings'] = underlyings_list
                            
                            # 向后兼容：保留第一个标的物的配置
                            if underlyings_list:
                                first_underlying = underlyings_list[0]
                                config['underlying'] = first_underlying.get('underlying', '510300')
                                config['call_contracts'] = first_underlying.get('call_contracts', [])
                                config['put_contracts'] = first_underlying.get('put_contracts', [])
                                
                                # 保留单个合约字段（向后兼容）
                                if config['call_contracts']:
                                    first_call = config['call_contracts'][0]
                                    config['call_contract_code'] = first_call.get('contract_code')
                                    config['call_strike_price'] = first_call.get('strike_price')
                                    config['call_expiry_date'] = first_call.get('expiry_date')
                                
                                if config['put_contracts']:
                                    first_put = config['put_contracts'][0]
                                    config['put_contract_code'] = first_put.get('contract_code')
                                    config['put_strike_price'] = first_put.get('strike_price')
                                    config['put_expiry_date'] = first_put.get('expiry_date')
                            
                            logger.info(f"从配置文件加载: {len(underlyings_list)} 个标的物")
                            for idx, underlying_config in enumerate(underlyings_list, 1):
                                underlying_code = underlying_config.get('underlying', 'N/A')
                                call_count = len(underlying_config.get('call_contracts', []))
                                put_count = len(underlying_config.get('put_contracts', []))
                                logger.info(f"  标的物 {idx}: {underlying_code}, Call合约: {call_count}, Put合约: {put_count}")
                        else:
                            # 旧格式：单个标的物配置（已废弃，但暂时支持）
                            config['underlying'] = opt_config.get('underlying', '510300')
                            
                            call_contracts_list = opt_config.get('call_contracts', [])
                            put_contracts_list = opt_config.get('put_contracts', [])
                            
                            if not call_contracts_list:
                                call_contract_single = opt_config.get('call_contract', {})
                                if call_contract_single:
                                    call_contracts_list = [call_contract_single]
                            
                            if not put_contracts_list:
                                put_contract_single = opt_config.get('put_contract', {})
                                if put_contract_single:
                                    put_contracts_list = [put_contract_single]
                            
                            config['call_contracts'] = call_contracts_list
                            config['put_contracts'] = put_contracts_list
                            
                            # 转换为新格式
                            config['underlyings'] = [{
                                'underlying': config['underlying'],
                                'call_contracts': call_contracts_list,
                                'put_contracts': put_contracts_list
                            }]
                            
                            logger.warning("检测到旧格式配置，已自动转换为新格式。建议使用 underlyings 列表格式。")
                            logger.debug(f"从配置文件加载: Call合约数={len(call_contracts_list)}, Put合约数={len(put_contracts_list)}")
            except Exception as e:
                logger.error(f"读取配置文件失败: {str(e)}", exc_info=True)
        
        # 2. 从环境变量加载（如果配置文件没有）
        call_strike_env = os.getenv('CALL_STRIKE_PRICE')
        if not config.get('call_strike_price') and call_strike_env:
            config['call_strike_price'] = float(call_strike_env)
        put_strike_env = os.getenv('PUT_STRIKE_PRICE')
        if not config.get('put_strike_price') and put_strike_env:
            config['put_strike_price'] = float(put_strike_env)
        
        # 3. 从命令行参数加载（如果环境变量没有）
        parser = argparse.ArgumentParser(description='期权交易助手')
        parser.add_argument('--call-strike', type=float, help='Call期权行权价')
        parser.add_argument('--put-strike', type=float, help='Put期权行权价')
        args, unknown = parser.parse_known_args()
        
        if args.call_strike and not config.get('call_strike_price'):
            config['call_strike_price'] = args.call_strike
        if args.put_strike and not config.get('put_strike_price'):
            config['put_strike_price'] = args.put_strike
        
        # 检查是否有合约代码（如果只有行权价，需要查找合约代码）
        call_has_code = config.get('call_contract_code')
        put_has_code = config.get('put_contract_code')
        
        if not call_has_code and config.get('call_strike_price'):
            logger.debug("Call期权未指定合约代码，需要根据行权价查找")
        elif call_has_code:
            logger.debug("Call期权已指定合约代码，跳过行权价输入")
        
        if not put_has_code and config.get('put_strike_price'):
            logger.debug("Put期权未指定合约代码，需要根据行权价查找")
        elif put_has_code:
            logger.debug("Put期权已指定合约代码，跳过行权价输入")
        
        # 验证配置完整性
        is_valid, validation_errors = validate_contract_config(config)
        if not is_valid:
            logger.warning(f"合约配置验证失败，发现 {len(validation_errors)} 个问题:")
            for error in validation_errors:
                logger.warning(f"  - {error}")
            logger.warning("系统将继续运行，但可能无法正常工作，请检查配置文件")
        else:
            logger.info("合约配置验证通过")
        
        # 更新缓存
        _config_cache = config.copy()
        _config_cache_time = time()
        
        logger.debug(f"合约配置加载完成: Call={config.get('call_strike_price')}, Put={config.get('put_strike_price')}")
        return config
        
    except Exception as e:
        logger.error(f"加载合约配置时发生错误: {str(e)}", exc_info=True)
        return {}


def save_config(config: Dict, config_path: str = "config.yaml") -> bool:
    """
    保存配置到文件
    
    Args:
        config: 配置字典
        config_path: 配置文件路径
    
    Returns:
        bool: 是否保存成功
    """
    try:
        import yaml
        
        # 确保目录存在
        config_file = Path(config_path)
        config_file.parent.mkdir(parents=True, exist_ok=True)
        
        # 保存配置
        with open(config_file, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        
        # 清除缓存，强制下次重新加载
        global _config_cache, _config_cache_time, _system_config_cache, _system_config_cache_time
        _config_cache = None
        _config_cache_time = None
        _system_config_cache = None
        _system_config_cache_time = None
        
        logger.info(f"配置已保存到: {config_path}")
        return True
        
    except Exception as e:
        logger.error(f"保存配置失败: {str(e)}", exc_info=True)
        return False


def reload_config_cache():
    """
    重新加载配置缓存（用于WEB界面更新后）
    """
    global _config_cache, _config_cache_time, _system_config_cache, _system_config_cache_time
    
    _config_cache = None
    _config_cache_time = None
    _system_config_cache = None
    _system_config_cache_time = None
    
    logger.info("配置缓存已清除，下次加载时将重新读取配置文件")


def get_contract_expiry_date(config: Dict, option_type: str = "call") -> Optional[datetime]:
    """
    从配置中获取期权到期日期
    
    Args:
        config: 配置字典
        option_type: "call" 或 "put"
    
    Returns:
        datetime: 到期日期，如果未配置返回None
    """
    try:
        contract_config_key = f"{option_type}_contract"
        contract_config = config.get('option_contracts', {}).get(contract_config_key, {})
        expiry_date_str = contract_config.get('expiry_date')
        
        if expiry_date_str:
            # 尝试解析日期字符串
            # 支持格式：YYYY-MM-DD, YYYYMMDD, YYYY/MM/DD
            if isinstance(expiry_date_str, str):
                expiry_date_str = expiry_date_str.strip()
                # 尝试不同的日期格式
                for fmt in ['%Y-%m-%d', '%Y%m%d', '%Y/%m/%d']:
                    try:
                        expiry_date = datetime.strptime(expiry_date_str, fmt)
                        logger.debug(f"从配置获取到期日期: {option_type} -> {expiry_date.strftime('%Y-%m-%d')}")
                        return expiry_date
                    except ValueError:
                        continue
                logger.warning(f"无法解析到期日期格式: {expiry_date_str}，支持的格式: YYYY-MM-DD, YYYYMMDD, YYYY/MM/DD")
            elif isinstance(expiry_date_str, datetime):
                return expiry_date_str
        
        return None
        
    except Exception as e:
        logger.warning(f"获取到期日期失败: {option_type}, 错误: {e}")
        return None


def verify_contract_strike_price(contract_code: str, expected_strike: float = 0.0) -> Optional[float]:
    """
    验证合约代码对应的行权价是否匹配，或仅获取行权价
    
    Args:
        contract_code: 合约代码
        expected_strike: 期望的行权价（如果为0.0，则只获取不验证）
    
    Returns:
        float: 实际行权价，如果无法获取返回None
    """
    try:
        import akshare as ak
        
        spot_data = ak.option_sse_spot_price_sina(symbol=contract_code)
        if spot_data is None or spot_data.empty:
            return None
        
        # 如果找不到价格字段，尝试从值列获取（option_sse_spot_price_sina返回格式：字段/值）
        if '值' in spot_data.columns and '字段' in spot_data.columns:
            try:
                for idx, row in spot_data.iterrows():
                    field_name = str(row.get('字段', ''))
                    field_value = row.get('值', '')
                    
                    if '行权价' in field_name or 'strike' in field_name.lower():
                        try:
                            actual_strike = float(field_value)
                            # 如果expected_strike为0.0，表示只获取不验证
                            if expected_strike == 0.0:
                                return actual_strike
                            # 否则验证是否匹配
                            return actual_strike
                        except (ValueError, TypeError):
                            continue
            except Exception as e:
                logger.debug(f"解析行权价失败: {e}")
        
        return None
        
    except Exception as e:
        logger.debug(f"验证行权价失败: {e}")
        return None


def find_contract_by_strike(
    underlying: str = "510300",
    option_type: str = "call",
    strike_price: Optional[float] = None,
    current_month: Optional[str] = None
) -> Optional[str]:
    """
    根据行权价查找合约代码（如果用户指定了行权价而非合约代码）
    
    Args:
        underlying: 标的代码
        option_type: "call" 或 "put"
        strike_price: 行权价
        current_month: 当前月份 YYYYMM
    
    Returns:
        str: 合约代码，如果未找到返回None
    """
    if strike_price is None:
        logger.warning("行权价为None，无法查找合约代码")
        return None
    
    try:
        import akshare as ak
        from datetime import datetime
        
        if current_month is None:
            current_month = datetime.now().strftime("%Y%m")
        
        option_type_cn = "看涨期权" if option_type == "call" else "看跌期权"
        logger.info(f"开始查找合约: underlying={underlying}, option_type={option_type_cn}, strike_price={strike_price}, current_month={current_month}")
        
        # 方法1：尝试使用 option_sse_codes_sina（仅支持上交所期权）
        # 注意：新浪接口仅支持上交所（SSE）期权，不支持深交所（SZSE）期权
        codes_df = None
        try:
            codes_df = ak.option_sse_codes_sina(
                symbol=option_type_cn,
                trade_date=current_month,
                underlying=underlying
            )
            if codes_df is not None and not codes_df.empty:
                logger.debug(f"使用 option_sse_codes_sina 获取到 {len(codes_df)} 个合约")
        except Exception as e:
            logger.warning(f"调用 option_sse_codes_sina 失败: {str(e)}，尝试备用方法")
            logger.debug("注意：新浪接口仅支持上交所（SSE）期权，深交所（SZSE）期权需要使用其他数据源")
            codes_df = None
        
        # 方法2：如果方法1失败，尝试使用其他备用方法
        if codes_df is None or codes_df.empty:
            logger.warning(f"无法获取{option_type_cn}代码列表，请手动在配置文件中指定合约代码")
            return None
        
        # 遍历所有合约，查找匹配的行权价
        for code in codes_df['期权代码']:
            try:
                spot_data = ak.option_sse_spot_price_sina(symbol=str(code))
                if spot_data is None or spot_data.empty:
                    continue
                
                for spot_idx, spot_row in spot_data.iterrows():
                    field = spot_row.get('字段', '')
                    if field == '行权价':
                        value = spot_row.get('值', '')
                        try:
                            contract_strike = float(value)
                            if abs(contract_strike - strike_price) < 0.01:  # 允许0.01的误差
                                logger.info(f"找到{option_type_cn}合约: {code}, 行权价: {contract_strike}")
                                return code
                        except (ValueError, TypeError) as e:
                            logger.debug(f"解析行权价失败: code={code}, value={value} | 错误: {str(e)}")
                            continue
                        
            except Exception as e:
                logger.debug(f"获取合约 {code} 数据失败: {str(e)}")
                continue
        
        logger.warning(f"未找到行权价为 {strike_price} 的{option_type_cn}合约")
        return None
        
    except Exception as e:
        logger.error(f"查找合约代码时发生错误: underlying={underlying}, option_type={option_type}, strike_price={strike_price} | 错误: {str(e)}", exc_info=True)
        return None


def validate_contract_config(config: Dict):
    """
    验证合约配置完整性
    
    该函数验证系统配置中的期权合约配置是否完整和正确，包括：
    - 标的物配置完整性（至少一个Call和Put合约）
    - 每个合约的必要字段（contract_code、strike_price、expiry_date）
    - 合约代码格式（8位数字）
    - 标的物代码格式（6位数字）
    - 行权价有效性（正数）
    - 到期日期格式（YYYY-MM-DD）
    
    Args:
        config: 系统配置字典，必须包含'option_contracts'字段
    
    Returns:
        tuple: (是否有效, 错误列表)
        - 如果配置有效，返回(True, [])
        - 如果配置无效，返回(False, [错误信息列表])
        错误信息格式: "标的物 {idx} ({underlying}): 具体错误描述"
    
    Example:
        ```python
        config = load_system_config()
        is_valid, errors = validate_contract_config(config)
        if not is_valid:
            for error in errors:
                print(f"配置错误: {error}")
        ```
    
    Note:
        - 验证失败不会抛出异常，只返回错误列表
        - 建议在系统启动时调用此函数，提前发现配置问题
        - 验证过程出错时，会返回(False, ["配置验证过程出错: 错误信息"])
    """
    errors = []
    
    try:
        option_contracts = config.get('option_contracts', {})
        underlyings_list = get_underlyings(option_contracts)
        
        if not underlyings_list:
            errors.append("未配置任何标的物")
            return False, errors
        
        # 验证每个标的物
        for idx, underlying_config in enumerate(underlyings_list, 1):
            underlying = underlying_config.get('underlying', '')
            if not underlying:
                errors.append(f"标的物 {idx}: 缺少underlying字段")
                continue
            
            # 验证标的物代码格式（6位数字）
            if not (isinstance(underlying, str) and underlying.isdigit() and len(underlying) == 6):
                errors.append(f"标的物 {idx} ({underlying}): underlying代码格式不正确（应为6位数字）")
            
            call_contracts = underlying_config.get('call_contracts', [])
            put_contracts = underlying_config.get('put_contracts', [])
            
            # 验证至少有一个Call和Put合约
            if not call_contracts:
                errors.append(f"标的物 {idx} ({underlying}): 缺少Call合约配置")
            if not put_contracts:
                errors.append(f"标的物 {idx} ({underlying}): 缺少Put合约配置")
            
            # 验证每个Call合约
            for call_idx, call_contract in enumerate(call_contracts, 1):
                if not isinstance(call_contract, dict):
                    errors.append(f"标的物 {idx} ({underlying}): Call合约 {call_idx} 配置格式错误（应为字典）")
                    continue
                
                contract_code = call_contract.get('contract_code')
                if not contract_code:
                    errors.append(f"标的物 {idx} ({underlying}): Call合约 {call_idx} 缺少contract_code")
                elif not (isinstance(contract_code, (str, int)) and str(contract_code).isdigit() and len(str(contract_code)) == 8):
                    errors.append(f"标的物 {idx} ({underlying}): Call合约 {call_idx} contract_code格式不正确（应为8位数字）")
                
                strike_price = call_contract.get('strike_price')
                if strike_price is None:
                    errors.append(f"标的物 {idx} ({underlying}): Call合约 {call_idx} ({contract_code}) 缺少strike_price")
                elif not isinstance(strike_price, (int, float)) or strike_price <= 0:
                    errors.append(f"标的物 {idx} ({underlying}): Call合约 {call_idx} ({contract_code}) strike_price无效（应为正数）")
                
                expiry_date = call_contract.get('expiry_date')
                if not expiry_date:
                    errors.append(f"标的物 {idx} ({underlying}): Call合约 {call_idx} ({contract_code}) 缺少expiry_date")
                elif not isinstance(expiry_date, str) or len(expiry_date) != 10:
                    errors.append(f"标的物 {idx} ({underlying}): Call合约 {call_idx} ({contract_code}) expiry_date格式不正确（应为YYYY-MM-DD）")
            
            # 验证每个Put合约
            for put_idx, put_contract in enumerate(put_contracts, 1):
                if not isinstance(put_contract, dict):
                    errors.append(f"标的物 {idx} ({underlying}): Put合约 {put_idx} 配置格式错误（应为字典）")
                    continue
                
                contract_code = put_contract.get('contract_code')
                if not contract_code:
                    errors.append(f"标的物 {idx} ({underlying}): Put合约 {put_idx} 缺少contract_code")
                elif not (isinstance(contract_code, (str, int)) and str(contract_code).isdigit() and len(str(contract_code)) == 8):
                    errors.append(f"标的物 {idx} ({underlying}): Put合约 {put_idx} contract_code格式不正确（应为8位数字）")
                
                strike_price = put_contract.get('strike_price')
                if strike_price is None:
                    errors.append(f"标的物 {idx} ({underlying}): Put合约 {put_idx} ({contract_code}) 缺少strike_price")
                elif not isinstance(strike_price, (int, float)) or strike_price <= 0:
                    errors.append(f"标的物 {idx} ({underlying}): Put合约 {put_idx} ({contract_code}) strike_price无效（应为正数）")
                
                expiry_date = put_contract.get('expiry_date')
                if not expiry_date:
                    errors.append(f"标的物 {idx} ({underlying}): Put合约 {put_idx} ({contract_code}) 缺少expiry_date")
                elif not isinstance(expiry_date, str) or len(expiry_date) != 10:
                    errors.append(f"标的物 {idx} ({underlying}): Put合约 {put_idx} ({contract_code}) expiry_date格式不正确（应为YYYY-MM-DD）")
        
        is_valid = len(errors) == 0
        return is_valid, errors
        
    except Exception as e:
        errors.append(f"配置验证过程出错: {str(e)}")
        return False, errors


def get_underlyings(config: Dict) -> List[Dict[str, Any]]:
    """
    获取所有标的物配置（支持多标的物）
    
    Args:
        config: 配置字典（可以是完整配置或 option_contracts 子配置）
    
    Returns:
        List[Dict]: 标的物配置列表，每个元素包含 underlying, call_contracts, put_contracts
    """
    # 如果传入的 config 本身就是 option_contracts 子配置（包含 underlyings 键）
    if 'underlyings' in config:
        underlyings_list = config.get('underlyings', [])
        logger.info(f"get_underlyings: 从 option_contracts 子配置中读取，找到 {len(underlyings_list)} 个标的物")
        logger.info(f"get_underlyings: underlyings_list 类型={type(underlyings_list)}, 长度={len(underlyings_list) if isinstance(underlyings_list, list) else 'N/A'}")
        if isinstance(underlyings_list, list) and len(underlyings_list) > 0:
            for i, ul in enumerate(underlyings_list):
                if isinstance(ul, dict):
                    original_underlying = ul.get('underlying')
                    # 统一转换为字符串格式（防止配置错误）
                    if original_underlying is not None:
                        ul['underlying'] = str(original_underlying)
                        if str(original_underlying) != original_underlying:
                            logger.info(f"get_underlyings: 标的物 {i+1}: underlying={original_underlying} (类型={type(original_underlying).__name__}) -> '{ul['underlying']}' (已转换为字符串)")
                        else:
                            logger.info(f"get_underlyings: 标的物 {i+1}: underlying={ul['underlying']}")
                else:
                    logger.info(f"get_underlyings: 标的物 {i+1}: underlying=N/A (不是字典)")
        logger.debug(f"get_underlyings: underlyings_list 内容: {underlyings_list}")
        logger.debug(f"get_underlyings: config keys: {list(config.keys())}")
        # 只有当列表非空时才返回，如果为空则继续查找
        if underlyings_list and len(underlyings_list) > 0:
            logger.info(f"get_underlyings: 返回 {len(underlyings_list)} 个标的物")
            return underlyings_list
        elif underlyings_list == []:
            # 如果是空列表，说明配置可能有问题，记录警告但继续查找
            logger.warning("get_underlyings: option_contracts 子配置中的 underlyings 是空列表，继续查找其他配置源")
    
    # 如果传入的是完整配置，从 option_contracts 中读取（新格式）
    option_contracts = config.get('option_contracts', {})
    if isinstance(option_contracts, dict) and 'underlyings' in option_contracts:
        underlyings_list = option_contracts.get('underlyings', [])
        logger.info(f"get_underlyings: 从完整配置的 option_contracts 中读取，找到 {len(underlyings_list)} 个标的物")
        if underlyings_list and len(underlyings_list) > 0:
            return underlyings_list
    
    # 如果 option_contracts 中没有，尝试从顶层读取（兼容旧格式）
    underlyings_list = config.get('underlyings', [])
    
    if not underlyings_list or len(underlyings_list) == 0:
        # 如果没有配置 underlyings，使用旧格式转换为新格式（向后兼容，但用户要求不再支持）
        # 为了安全，这里保留但不推荐使用
        underlying = config.get('underlying', '510300')
        call_contracts = config.get('call_contracts', [])
        put_contracts = config.get('put_contracts', [])
        
        if underlying:
            logger.warning(f"get_underlyings: 使用旧格式配置（不推荐），标的物: {underlying}")
            underlyings_list = [{
                'underlying': underlying,
                'call_contracts': call_contracts,
                'put_contracts': put_contracts
            }]
    
    logger.info(f"get_underlyings: 最终返回 {len(underlyings_list)} 个标的物配置")
    return underlyings_list if underlyings_list else []


def get_contract_codes(config: Dict, option_type: str = "call", verify_strike: bool = True, underlying: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    获取多个期权合约配置（支持多个合约，支持指定标的物）
    
    Args:
        config: 配置字典
        option_type: "call" 或 "put"
        verify_strike: 如果同时指定了合约代码和行权价，是否验证行权价匹配（默认True）
        underlying: 标的物代码（可选，如果指定则只返回该标的物的合约）
    
    Returns:
        List[Dict]: 合约配置列表，每个元素包含 contract_code, strike_price, expiry_date, name, underlying 等字段
    """
    result = []
    
    # 如果指定了标的物，只获取该标的物的合约
    if underlying:
        underlyings_list = get_underlyings(config)
        for underlying_config in underlyings_list:
            if underlying_config.get('underlying') == underlying:
                contracts_list = underlying_config.get(f"{option_type}_contracts", [])
                for contract_config in contracts_list:
                    if not isinstance(contract_config, dict):
                        continue
                    
                    # 创建临时配置用于获取合约代码
                    temp_config = config.copy()
                    temp_config['underlying'] = underlying
                    
                    contract_code = get_contract_code_from_config(contract_config, temp_config, option_type, verify_strike)
                    if contract_code:
                        result.append({
                            'contract_code': contract_code,
                            'strike_price': contract_config.get('strike_price'),
                            'expiry_date': contract_config.get('expiry_date'),
                            'name': contract_config.get('name', contract_code),
                            'underlying': underlying
                        })
                # 找到匹配的标的物后，直接返回结果
                logger.info(f"get_contract_codes: 标的物 {underlying} 返回 {len(result)} 个{option_type}合约")
                return result
        # underlying 指定但未找到匹配标的物：返回空列表（保证所有分支都有 return）
        logger.info(f"get_contract_codes: 未找到匹配标的物 {underlying}，返回空列表")
        return result
    else:
        # 获取所有标的物的所有合约
        underlyings_list = get_underlyings(config)
        logger.info(f"get_contract_codes: 找到 {len(underlyings_list)} 个标的物配置")
        logger.info(f"get_contract_codes: underlyings_list 内容: {underlyings_list}")
        
        for underlying_config in underlyings_list:
            logger.info(f"get_contract_codes: 处理标的物配置: {underlying_config}")
            underlying_code = underlying_config.get('underlying', '510300')
            contracts_list = underlying_config.get(f"{option_type}_contracts", [])
            logger.info(f"get_contract_codes: 标的物 {underlying_code} 有 {len(contracts_list)} 个{option_type}合约，列表内容: {contracts_list}")
            
            for contract_config in contracts_list:
                if not isinstance(contract_config, dict):
                    logger.warning(f"get_contract_codes: 跳过非字典类型的合约配置: {type(contract_config)}")
                    continue
                
                # 创建临时配置用于获取合约代码
                temp_config = config.copy()
                temp_config['underlying'] = underlying_code
                
                contract_code = get_contract_code_from_config(contract_config, temp_config, option_type, verify_strike)
                if contract_code:
                    logger.info(f"get_contract_codes: 成功获取{option_type}合约代码: {contract_code}")
                    result.append({
                        'contract_code': contract_code,
                        'strike_price': contract_config.get('strike_price'),
                        'expiry_date': contract_config.get('expiry_date'),
                        'name': contract_config.get('name', contract_code),
                        'underlying': underlying_code
                    })
                else:
                    logger.warning(f"get_contract_codes: 无法获取{option_type}合约代码，配置: {contract_config}")
        
        logger.info(f"get_contract_codes: 最终返回 {len(result)} 个{option_type}合约")
        return result


def get_contract_code_from_config(
    contract_config: Dict, 
    config: Dict, 
    option_type: str = "call", 
    verify_strike: bool = True
) -> Optional[str]:
    """
    从单个合约配置中获取合约代码（内部函数）
    
    Args:
        contract_config: 单个合约配置字典
        config: 系统配置字典（用于获取underlying等）
        option_type: "call" 或 "put"
        verify_strike: 是否验证行权价匹配（默认True）
    
    Returns:
        str: 合约代码，如果未找到返回None
    """
    try:
        # 检查是否有合约代码（需要处理 None、空字符串等情况）
        contract_code_raw = contract_config.get('contract_code')
        # 处理 YAML 中的 null 值（会被解析为 Python 的 None）
        if contract_code_raw is None:
            has_contract_code = False
        else:
            contract_code_str = str(contract_code_raw).strip()
            has_contract_code = contract_code_str != '' and contract_code_str.lower() not in ('null', 'none')
        
        has_strike_price = 'strike_price' in contract_config and contract_config['strike_price'] is not None
        
        logger.info(f"get_contract_code_from_config: {option_type}, has_contract_code={has_contract_code}, has_strike_price={has_strike_price}, contract_code_raw={contract_code_raw}, contract_config={contract_config}")

        contract_code: Optional[str] = None
        
        # 优先级1：如果直接指定了合约代码，直接使用
        if has_contract_code:
            contract_code = str(contract_code_raw).strip()
            # 过滤掉 'null', 'None', 空字符串等无效值
            if contract_code and contract_code.lower() not in ('null', 'none', ''):
                # 如果同时指定了行权价，可以选择性验证
                if has_strike_price and verify_strike:
                    strike_price = contract_config['strike_price']
                    # 验证合约代码对应的行权价是否匹配
                    actual_strike = verify_contract_strike_price(contract_code, strike_price)
                    if actual_strike is not None:
                        if abs(actual_strike - strike_price) < 0.01:  # 允许0.01的误差
                            logger.debug(f"{option_type}期权合约代码: {contract_code}, 行权价验证通过: {strike_price}")
                        else:
                            logger.warning(f"合约代码 {contract_code} 的行权价 ({actual_strike}) 与配置的行权价 ({strike_price}) 不匹配，但继续使用合约代码")
                    else:
                        logger.debug(f"无法验证合约代码 {contract_code} 的行权价，但继续使用合约代码")
                else:
                    # 如果没有配置行权价，尝试自动获取
                    if not has_strike_price:
                        actual_strike = verify_contract_strike_price(contract_code, 0.0)  # 传入0.0表示只获取，不验证
                        if actual_strike is not None:
                            logger.debug(f"{option_type}期权合约代码: {contract_code}, 自动获取行权价: {actual_strike}")
                        else:
                            logger.debug(f"{option_type}期权合约代码: {contract_code}（无法自动获取行权价）")
                return contract_code
        
        # 优先级2：如果指定了行权价，自动查找合约
        if has_strike_price:
            strike_price = contract_config['strike_price']
            contract_code = find_contract_by_strike(
                underlying=config.get('underlying', '510300'),
                option_type=option_type,
                strike_price=strike_price,
                current_month=config.get('current_month')
            )
            if contract_code:
                logger.debug(f"根据行权价找到{option_type}期权合约: {contract_code}, 行权价: {strike_price}")
                return contract_code
            else:
                logger.warning(f"未找到行权价为 {strike_price} 的{option_type}期权合约")
                return None
        
        logger.debug(f"未指定{option_type}期权的行权价或合约代码")
        return None
        
    except Exception as e:
        logger.error(f"获取合约代码时发生错误: option_type={option_type} | 错误: {str(e)}", exc_info=True)
        return None


def get_contract_code(config: Dict, option_type: str = "call", verify_strike: bool = True) -> Optional[str]:
    """
    根据行权价或直接指定的合约代码获取期权合约代码（统一入口，向后兼容）
    优先级：直接指定的合约代码 > 根据行权价自动查找
    
    如果同时指定了合约代码和行权价，会使用合约代码，并可选择性地验证行权价是否匹配
    
    注意：此函数返回第一个合约的代码（向后兼容），如需获取所有合约，请使用 get_contract_codes()
    
    Args:
        config: 配置字典（包含行权价或合约代码）
        option_type: "call" 或 "put"
        verify_strike: 如果同时指定了合约代码和行权价，是否验证行权价匹配（默认True）
    
    Returns:
        str: 合约代码（第一个合约），如果未找到返回None
    """
    # 优先使用新的多合约配置
    contracts_list = config.get(f"{option_type}_contracts", [])
    
    # 向后兼容：如果列表为空，尝试使用单个合约配置
    if not contracts_list:
        single_contract = config.get(f"{option_type}_contract", {})
        if single_contract:
            contracts_list = [single_contract]
    
    # 如果有多个合约，返回第一个启用的合约代码
    if contracts_list:
        for contract_config in contracts_list:
            if not isinstance(contract_config, dict):
                continue
            # 检查是否启用（默认启用）
            if contract_config.get('enabled', True) is False:
                continue
            contract_code = get_contract_code_from_config(contract_config, config, option_type, verify_strike)
            if contract_code:
                return contract_code
    
    # 如果新格式没有找到，使用旧的单个合约逻辑（向后兼容）
    contract_config = config.get(f"{option_type}_contract", {})
    if contract_config:
        contract_code = get_contract_code_from_config(contract_config, config, option_type, verify_strike)
        if contract_code:
            logger.info(f"使用配置文件中直接指定的{option_type}期权合约代码: {contract_code}（向后兼容模式）")
            return contract_code
    
    logger.warning(f"未找到{option_type}期权的合约配置")
    return None


def validate_strike_price(strike_price: Any) -> bool:
    """
    验证行权价是否有效
    
    Args:
        strike_price: 行权价
    
    Returns:
        bool: 是否有效
    """
    try:
        price = float(strike_price)
        return price > 0
    except (ValueError, TypeError):
        return False
