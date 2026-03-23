"""
预测报告生成模块
生成每日、每周、每月报告
"""

import json
from pathlib import Path
from datetime import datetime, timedelta
import pytz
from typing import Dict, Optional, Any

from src.logger_config import get_module_logger
from src.prediction_evaluator import evaluate_predictions

logger = get_module_logger(__name__)

# 报告存储路径
REPORTS_DIR = Path("data/prediction_reports")


def generate_daily_report(
    date: str,
    config: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    生成每日报告
    
    Args:
        date: 日期（YYYYMMDD）
        config: 系统配置
    
    Returns:
        dict: 每日报告数据
    """
    try:
        # 评估当日预测
        evaluation = evaluate_predictions(date, date, prediction_type=None, source=None)
        
        if evaluation.get('error'):
            logger.warning(f"生成每日报告失败: {evaluation.get('error')}")
            return evaluation
        
        # 提取核心指标
        core_metrics = evaluation.get('core_metrics', {})
        coverage = core_metrics.get('coverage_rate', {})
        width = core_metrics.get('average_width', {})
        calibration = core_metrics.get('calibration', {})
        
        # 提取辅助指标
        auxiliary_metrics = evaluation.get('auxiliary_metrics', {})
        method_performance = auxiliary_metrics.get('method_performance', {})
        calibration_effectiveness = auxiliary_metrics.get('calibration_effectiveness', {})
        
        # 构建报告
        report = {
            'date': date,
            'report_type': 'daily',
            'total_predictions': evaluation.get('total_predictions', 0),
            'summary': {
                'coverage_rate': coverage.get('coverage_rate'),
                'average_width': width.get('avg_width'),
                'calibration_score': calibration.get('calibration_score'),
                'total_hits': coverage.get('hits', 0),
                'total_misses': coverage.get('misses', 0)
            },
            'method_performance': method_performance,
            'calibration_effectiveness': calibration_effectiveness,
            'generated_at': datetime.now(pytz.timezone('Asia/Shanghai')).isoformat()
        }
        
        # 保存报告
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        report_file = REPORTS_DIR / f"daily_report_{date}.json"
        
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        
        logger.info(f"每日报告已生成: {date}")
        return report
        
    except Exception as e:
        logger.error(f"生成每日报告失败: {e}", exc_info=True)
        return {'error': str(e), 'date': date}


def generate_weekly_report(
    week_start_date: str,
    config: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    生成每周报告
    
    Args:
        week_start_date: 周开始日期（YYYYMMDD）
        config: 系统配置
    
    Returns:
        dict: 每周报告数据
    """
    try:
        # 计算周结束日期（7天后）
        start = datetime.strptime(week_start_date, '%Y%m%d')
        end = start + timedelta(days=6)
        end_date = end.strftime('%Y%m%d')
        
        # 评估本周预测
        evaluation = evaluate_predictions(week_start_date, end_date, prediction_type=None, source=None)
        
        # 数据不足/无记录：仍然返回“标准报告结构”，避免上层/测试因缺字段失败
        if evaluation.get('error'):
            err = evaluation.get('error')
            logger.warning(f"生成每周报告失败: {err}")
            report = {
                'week_start_date': week_start_date,
                'week_end_date': end_date,
                'report_type': 'weekly',
                'total_predictions': evaluation.get('total', 0) or evaluation.get('total_predictions', 0) or 0,
                'summary': {
                    'avg_coverage_rate': None,
                    'avg_width': None,
                    'calibration_score': None
                },
                'method_performance': {},
                'weight_changes': {},
                'garch_optimization': {},
                'insufficient_data': True,
                'error': err,
                'generated_at': datetime.now(pytz.timezone('Asia/Shanghai')).isoformat()
            }
            REPORTS_DIR.mkdir(parents=True, exist_ok=True)
            report_file = REPORTS_DIR / f"weekly_report_{week_start_date}.json"
            with open(report_file, 'w', encoding='utf-8') as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            return report
        
        # 提取指标
        core_metrics = evaluation.get('core_metrics', {})
        coverage = core_metrics.get('coverage_rate', {})
        width = core_metrics.get('average_width', {})
        calibration = core_metrics.get('calibration', {})
        
        auxiliary_metrics = evaluation.get('auxiliary_metrics', {})
        method_performance = auxiliary_metrics.get('method_performance', {})
        
        # 计算权重变化（需要从权重历史中获取）
        # 这里简化处理，实际需要从权重缓存中读取
        
        # 构建报告
        report = {
            'week_start_date': week_start_date,
            'week_end_date': end_date,
            'report_type': 'weekly',
            'total_predictions': evaluation.get('total_predictions', 0),
            'summary': {
                'avg_coverage_rate': coverage.get('coverage_rate'),
                'avg_width': width.get('avg_width'),
                'calibration_score': calibration.get('calibration_score')
            },
            'method_performance': method_performance,
            'weight_changes': {},  # 需要从权重历史中获取
            'garch_optimization': {},  # 需要从GARCH参数缓存中获取
            'generated_at': datetime.now(pytz.timezone('Asia/Shanghai')).isoformat()
        }
        
        # 保存报告
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        report_file = REPORTS_DIR / f"weekly_report_{week_start_date}.json"
        
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        
        logger.info(f"每周报告已生成: {week_start_date} - {end_date}")
        return report
        
    except Exception as e:
        logger.error(f"生成每周报告失败: {e}", exc_info=True)
        return {'error': str(e), 'week_start_date': week_start_date}


def generate_monthly_report(
    month: str,
    config: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    生成每月报告
    
    Args:
        month: 月份（YYYYMM）
        config: 系统配置
    
    Returns:
        dict: 每月报告数据
    """
    try:
        # 计算月份的开始和结束日期
        start_date = f"{month}01"
        # 计算月末日期
        if month[4:6] in ['01', '03', '05', '07', '08', '10', '12']:
            end_day = '31'
        elif month[4:6] in ['04', '06', '09', '11']:
            end_day = '30'
        else:
            # 2月，需要判断闰年
            year = int(month[:4])
            end_day = '29' if (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0) else '28'
        
        end_date = f"{month}{end_day}"
        
        # 评估本月预测
        evaluation = evaluate_predictions(start_date, end_date, prediction_type=None, source=None)

        report: Dict[str, Any]
        # 数据不足/无记录：仍然返回“标准报告结构”，避免上层/测试因缺字段失败
        if evaluation.get('error'):
            err = evaluation.get('error')
            logger.warning(f"生成每月报告失败: {err}")
            report = {
                'month': month,
                'start_date': start_date,
                'end_date': end_date,
                'report_type': 'monthly',
                'total_predictions': evaluation.get('total', 0) or evaluation.get('total_predictions', 0) or 0,
                'summary': {
                    'avg_coverage_rate': None,
                    'avg_width': None,
                    'calibration_score': None
                },
                'method_ranking': [],
                'method_performance': {},
                'trends': {},
                'recommendations': [],
                'insufficient_data': True,
                'error': err,
                'generated_at': datetime.now(pytz.timezone('Asia/Shanghai')).isoformat()
            }
            REPORTS_DIR.mkdir(parents=True, exist_ok=True)
            report_file = REPORTS_DIR / f"monthly_report_{month}.json"
            with open(report_file, 'w', encoding='utf-8') as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            return report
        
        # 提取指标
        core_metrics = evaluation.get('core_metrics', {})
        coverage = core_metrics.get('coverage_rate', {})
        width = core_metrics.get('average_width', {})
        calibration = core_metrics.get('calibration', {})
        
        auxiliary_metrics = evaluation.get('auxiliary_metrics', {})
        method_performance = auxiliary_metrics.get('method_performance', {})
        
        # 计算月度趋势（需要对比上个月）
        # 这里简化处理
        
        # 方法表现排名
        method_ranking = []
        for method, perf in method_performance.items():
            if perf.get('coverage_rate') is not None:
                method_ranking.append({
                    'method': method,
                    'coverage_rate': perf.get('coverage_rate'),
                    'avg_width': perf.get('avg_width'),
                    'total': perf.get('total', 0)
                })
        
        method_ranking.sort(key=lambda x: x.get('coverage_rate', 0), reverse=True)
        
        # 构建报告
        report = {
            'month': month,
            'start_date': start_date,
            'end_date': end_date,
            'report_type': 'monthly',
            'total_predictions': evaluation.get('total_predictions', 0),
            'summary': {
                'avg_coverage_rate': coverage.get('coverage_rate'),
                'avg_width': width.get('avg_width'),
                'calibration_score': calibration.get('calibration_score')
            },
            'method_ranking': method_ranking,
            'method_performance': method_performance,
            'trends': {},  # 需要对比历史数据
            'recommendations': [],  # 优化建议
            'generated_at': datetime.now(pytz.timezone('Asia/Shanghai')).isoformat()
        }
        
        # 生成优化建议
        if coverage.get('coverage_rate') is not None:
            if coverage.get('coverage_rate') < 0.85:
                report['recommendations'].append('覆盖率低于目标（85%），建议扩大预测区间或优化预测方法')
            if width.get('avg_width') and width.get('avg_width') > 3.0:
                report['recommendations'].append('平均区间宽度较大，建议优化预测方法以缩小区间')
        
        # 保存报告
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        report_file = REPORTS_DIR / f"monthly_report_{month}.json"
        
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        
        logger.info(f"每月报告已生成: {month}")
        return report
        
    except Exception as e:
        logger.error(f"生成每月报告失败: {e}", exc_info=True)
        return {'error': str(e), 'month': month}


def format_daily_report_message(report: Dict[str, Any]) -> str:
    """格式化每日报告消息"""
    try:
        summary = report.get('summary', {})
        coverage_rate = summary.get('coverage_rate')
        avg_width = summary.get('average_width')
        calibration_score = summary.get('calibration_score')
        hits = summary.get('total_hits', 0)
        misses = summary.get('total_misses', 0)
        total = report.get('total_predictions', 0)
        
        message = f"""📊 预测准确性每日报告 - {report.get('date', 'N/A')}

📈 核心指标：
• 区间覆盖率: {coverage_rate*100:.1f}% (目标: >85%) {'✅' if coverage_rate and coverage_rate >= 0.85 else '⚠️'}
• 平均区间宽度: {avg_width:.2f}%
• 校准度得分: {calibration_score:.2f} (目标: >0.8) {'✅' if calibration_score and calibration_score >= 0.8 else '⚠️'}
• 命中/未命中: {hits}/{misses} (总计: {total})

📋 各方法表现："""
        
        method_perf = report.get('method_performance', {})
        for method, perf in method_perf.items():
            method_coverage = perf.get('coverage_rate')
            method_width = perf.get('avg_width')
            method_total = perf.get('total', 0)
            if method_coverage is not None:
                message += f"\n• {method}: 覆盖率={method_coverage*100:.1f}%, 宽度={method_width:.2f}%, 预测数={method_total}"
        
        calibration_eff = report.get('calibration_effectiveness', {})
        if calibration_eff.get('calibrated_count', 0) > 0:
            calibrated_cov = calibration_eff.get('calibrated_coverage')
            improvement = calibration_eff.get('improvement')
            message += "\n\n🔄 实时校准效果："
            message += f"\n• 校准后覆盖率: {calibrated_cov*100:.1f}%" if calibrated_cov else ""
            message += f"\n• 提升幅度: {improvement*100:.1f}%" if improvement else ""
            message += f"\n• 校准次数: {calibration_eff.get('calibrated_count', 0)}"
        
        return message
        
    except Exception as e:
        logger.error(f"格式化每日报告消息失败: {e}")
        return f"报告生成失败: {e}"


def format_weekly_report_message(report: Dict[str, Any]) -> str:
    """格式化每周报告消息"""
    try:
        summary = report.get('summary', {})
        avg_coverage = summary.get('avg_coverage_rate')
        avg_width = summary.get('avg_width')
        calibration_score = summary.get('calibration_score')
        
        message = f"""📊 预测准确性每周报告 - {report.get('week_start_date', 'N/A')} ~ {report.get('week_end_date', 'N/A')}

📈 本周平均指标：
• 平均覆盖率: {avg_coverage*100:.1f}% (目标: >85%) {'✅' if avg_coverage and avg_coverage >= 0.85 else '⚠️'}
• 平均区间宽度: {avg_width:.2f}%
• 校准度得分: {calibration_score:.2f}

📋 各方法表现："""
        
        method_perf = report.get('method_performance', {})
        for method, perf in method_perf.items():
            method_coverage = perf.get('coverage_rate')
            method_width = perf.get('avg_width')
            method_total = perf.get('total', 0)
            if method_coverage is not None:
                message += f"\n• {method}: 覆盖率={method_coverage*100:.1f}%, 宽度={method_width:.2f}%, 预测数={method_total}"
        
        return message
        
    except Exception as e:
        logger.error(f"格式化每周报告消息失败: {e}")
        return f"报告生成失败: {e}"


def format_monthly_report_message(report: Dict[str, Any]) -> str:
    """格式化每月报告消息"""
    try:
        summary = report.get('summary', {})
        avg_coverage = summary.get('avg_coverage_rate')
        avg_width = summary.get('avg_width')
        calibration_score = summary.get('calibration_score')
        
        message = f"""📊 预测准确性每月报告 - {report.get('month', 'N/A')}

📈 本月平均指标：
• 平均覆盖率: {avg_coverage*100:.1f}% (目标: >85%) {'✅' if avg_coverage and avg_coverage >= 0.85 else '⚠️'}
• 平均区间宽度: {avg_width:.2f}%
• 校准度得分: {calibration_score:.2f}

🏆 方法表现排名："""
        
        method_ranking = report.get('method_ranking', [])
        for i, method_data in enumerate(method_ranking[:5], 1):  # 前5名
            method = method_data.get('method')
            coverage = method_data.get('coverage_rate')
            width = method_data.get('avg_width')
            total = method_data.get('total', 0)
            if coverage is not None:
                message += f"\n{i}. {method}: 覆盖率={coverage*100:.1f}%, 宽度={width:.2f}%, 预测数={total}"
        
        recommendations = report.get('recommendations', [])
        if recommendations:
            message += "\n\n💡 优化建议："
            for rec in recommendations:
                message += f"\n• {rec}"
        
        return message
        
    except Exception as e:
        logger.error(f"格式化每月报告消息失败: {e}")
        return f"报告生成失败: {e}"
