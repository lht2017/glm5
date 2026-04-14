"""
日志模块 - 适配Claude Code IDE终端实时输出
支持同时输出到终端和日志文件
"""
import logging
import sys
import os
from datetime import datetime

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")


def setup_logger(name: str = "seckill") -> logging.Logger:
    """
    创建并配置logger
    - 终端输出：实时显示，适配Claude Code IDE
    - 文件输出：按日期归档到logs目录
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # 避免重复添加handler

    logger.setLevel(logging.DEBUG)

    # 日志格式
    fmt = logging.Formatter(
        "[%(asctime)s.%(msecs)03d] %(levelname)-5s | %(message)s",
        datefmt="%H:%M:%S"
    )

    # 终端handler（实时flush，适配IDE）
    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(logging.INFO)
    sh.setFormatter(fmt)
    sh.flush = lambda *args, **kwargs: sys.stdout.flush()
    logger.addHandler(sh)

    # 文件handler
    os.makedirs(LOG_DIR, exist_ok=True)
    log_file = os.path.join(
        LOG_DIR,
        f"seckill_{datetime.now().strftime('%Y%m%d')}.log"
    )
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    return logger


# 全局logger实例
log = setup_logger()


def get_logs(max_lines: int = 200) -> str:
    """读取最近的日志内容（供Web界面展示）"""
    log_file = os.path.join(
        LOG_DIR,
        f"seckill_{datetime.now().strftime('%Y%m%d')}.log"
    )
    if not os.path.exists(log_file):
        return "暂无日志"
    with open(log_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
    return "".join(lines[-max_lines:])
