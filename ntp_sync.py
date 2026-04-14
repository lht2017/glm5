"""
NTP时间同步模块 - 对齐北京时间，毫秒级精度
使用国内NTP服务器池，消除本地时钟误差
"""
import time
import ntplib
import threading
from datetime import datetime, timezone, timedelta

# 北京时间 UTC+8
BJ_TZ = timezone(timedelta(hours=8))

# 国内NTP服务器池（按优先级排序）
NTP_SERVERS = [
    "ntp.aliyun.com",         # 阿里云NTP
    "ntp.tencent.com",        # 腾讯云NTP
    "ntp1.aliyun.com",
    "ntp2.aliyun.com",
    "time.cloudflare.com",
    "cn.ntp.org.cn",
]

# 全局时间偏移量（本地时间 + offset = 准确的北京时间）
_time_offset_ms = 0.0
_last_sync_time = 0.0
_sync_lock = threading.Lock()


def _query_ntp(server: str, timeout: float = 2.0) -> float:
    """查询单个NTP服务器，返回偏移量（秒）"""
    client = ntplib.NTPClient()
    try:
        response = client.request(server, version=3, timeout=timeout)
        return response.offset  # 本地时间与NTP时间的差值（秒）
    except (ntplib.NTPException, OSError):
        return None


def sync_time() -> float:
    """
    同步时间：向多个NTP服务器查询，取中位数作为偏移量
    返回偏移量（毫秒）
    """
    global _time_offset_ms, _last_sync_time

    offsets = []
    for server in NTP_SERVERS:
        offset = _query_ntp(server, timeout=3.0)
        if offset is not None:
            offsets.append(offset)

    if not offsets:
        print("[NTP] 所有NTP服务器查询失败，使用上次偏移量")
        return _time_offset_ms

    # 取中位数，避免极端值干扰
    offsets.sort()
    median_offset = offsets[len(offsets) // 2]
    _time_offset_ms = median_offset * 1000  # 转毫秒
    _last_sync_time = time.time()

    print(f"[NTP] 时间同步完成 | 偏移量: {_time_offset_ms:.2f}ms | "
          f"有效服务器: {len(offsets)}/{len(NTP_SERVERS)}")
    return _time_offset_ms


def get_accurate_time() -> datetime:
    """获取校准后的北京时间"""
    corrected_ts = time.time() + (_time_offset_ms / 1000.0)
    return datetime.fromtimestamp(corrected_ts, tz=BJ_TZ)


def get_accurate_timestamp() -> float:
    """获取校准后的UTC时间戳（秒）"""
    return time.time() + (_time_offset_ms / 1000.0)


def ms_to_target(target_time_str: str) -> float:
    """
    计算距离目标时间的精确毫秒数
    target_time_str: "HH:MM:SS" 格式，如 "10:00:00"
    返回：距离目标时间还有多少毫秒（负数表示已过）
    """
    now = get_accurate_time()
    h, m, s = map(int, target_time_str.split(":"))

    # 构造今天的北京时间目标时刻
    target = now.replace(hour=h, minute=m, second=s, microsecond=0)

    # 如果目标时间已过，指向明天
    if now >= target:
        from datetime import timedelta as td
        target += td(days=1)

    delta = (target - now).total_seconds() * 1000
    return delta


def busy_wait_until(target_time_str: str, early_ms: float = 100):
    """
    忙等待直到目标时间
    early_ms: 在目标时间前多少毫秒进入忙等待（忙等待期间不释放CPU）
    """
    # 第一阶段：普通sleep，距目标还有 early_ms+1000 毫秒以上时使用
    remaining = ms_to_target(target_time_str) - early_ms - 1000
    if remaining > 0:
        time.sleep(remaining / 1000.0)

    # 第二阶段：短sleep循环，距目标还有 early_ms 毫秒以上时使用
    while True:
        remaining = ms_to_target(target_time_str) - early_ms
        if remaining <= 0:
            break
        time.sleep(remaining / 2000.0)  # 每 half 间隔检查一次

    # 第三阶段：忙等待（CPU自旋），不释放CPU，最高精度
    while ms_to_target(target_time_str) > 0:
        pass  # 纯CPU自旋，精度取决于系统时钟

    return get_accurate_timestamp()


def start_periodic_sync(interval_seconds: int = 300):
    """
    启动定时同步线程，每interval_seconds秒重新同步一次NTP
    """
    def _sync_loop():
        while True:
            sync_time()
            time.sleep(interval_seconds)

    t = threading.Thread(target=_sync_loop, daemon=True)
    t.start()
    print(f"[NTP] 定时同步线程已启动，间隔 {interval_seconds}秒")
