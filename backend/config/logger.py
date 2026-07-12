"""
统一 Logger 工厂。

所有模块通过 get_logger(__name__) 获取 logger 实例：

    from config import get_logger
    logger = get_logger(__name__)
    logger.info("...")

特性：
  - Console 输出到 stdout（Railway / 本地终端可直接看到）
  - 文件输出：通过环境变量 LOG_FILE 指定路径，留空则不写文件
  - Debug 模式：通过环境变量 DEBUG=1 开启 DEBUG 级别
"""
import logging
import sys


def get_logger(name: str) -> logging.Logger:
    """返回已配置的 logger。同一 name 多次调用不会重复添加 handler。"""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    # 延迟导入 settings，避免循环依赖
    from config.settings import DEBUG, LOG_FILE

    level = logging.DEBUG if DEBUG else logging.INFO
    logger.setLevel(level)
    logger.propagate = False

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler（stdout，Railway 控制台可直接捕获，包括 [USAGE] 关键词搜索）
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(level)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # 文件 handler（可选）
    if LOG_FILE:
        try:
            fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
            fh.setLevel(level)
            fh.setFormatter(fmt)
            logger.addHandler(fh)
        except OSError:
            logger.warning(f"无法写入日志文件: {LOG_FILE}")

    return logger
