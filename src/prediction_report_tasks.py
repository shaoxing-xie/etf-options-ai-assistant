"""
预测报告定时任务模块
每周和每月报告生成任务
"""

from datetime import datetime, timedelta
import pytz

from src.logger_config import get_module_logger
from src.prediction_reporter import (
    generate_weekly_report,
    generate_monthly_report,
    format_weekly_report_message,
    format_monthly_report_message
)
from src.notifier import send_feishu_notification  # type: ignore[import-not-found]
from src.config_loader import load_system_config

logger = get_module_logger(__name__)


def weekly_report_task():
    """每周报告任务（每周一生成上周的报告）"""
    try:
        tz_shanghai = pytz.timezone('Asia/Shanghai')
        now = datetime.now(tz_shanghai)
        
        # 计算上周的开始日期（上周一）
        days_since_monday = now.weekday()
        last_monday = now - timedelta(days=days_since_monday + 7)
        week_start_date = last_monday.strftime('%Y%m%d')
        
        logger.info("=" * 60)
        logger.info(f"开始生成每周预测准确性报告: {week_start_date}")
        logger.info("=" * 60)
        
        config = load_system_config()
        
        # 生成报告
        report = generate_weekly_report(week_start_date, config=config)
        
        if report and not report.get('error'):
            # 格式化并发送报告
            report_message = format_weekly_report_message(report)
            
            # 发送飞书通知
            try:
                send_feishu_notification(
                    message=report_message,
                    title="📊 预测准确性每周报告",
                    config=config
                )
                logger.info("每周预测准确性报告已发送")
            except Exception as e:
                logger.warning(f"发送每周报告通知失败: {e}")
        else:
            logger.warning(f"每周报告生成失败或数据不足: {report.get('error', '未知错误')}")
        
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"每周报告任务执行失败: {e}", exc_info=True)


def monthly_report_task():
    """每月报告任务（每月1日生成上月的报告）"""
    try:
        tz_shanghai = pytz.timezone('Asia/Shanghai')
        now = datetime.now(tz_shanghai)
        
        # 计算上月的月份
        if now.month == 1:
            last_month = 12
            last_year = now.year - 1
        else:
            last_month = now.month - 1
            last_year = now.year
        
        month_str = f"{last_year}{last_month:02d}"
        
        logger.info("=" * 60)
        logger.info(f"开始生成每月预测准确性报告: {month_str}")
        logger.info("=" * 60)
        
        config = load_system_config()
        
        # 生成报告
        report = generate_monthly_report(month_str, config=config)
        
        if report and not report.get('error'):
            # 格式化并发送报告
            report_message = format_monthly_report_message(report)
            
            # 发送飞书通知
            try:
                send_feishu_notification(
                    message=report_message,
                    title="📊 预测准确性每月报告",
                    config=config
                )
                logger.info("每月预测准确性报告已发送")
            except Exception as e:
                logger.warning(f"发送每月报告通知失败: {e}")
        else:
            logger.warning(f"每月报告生成失败或数据不足: {report.get('error', '未知错误')}")
        
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"每月报告任务执行失败: {e}", exc_info=True)
