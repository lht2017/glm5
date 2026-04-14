"""
库存轮询与连接预热模块
准点前高频轮询库存状态，TCP/HTTP2连接预建立
"""
import asyncio
import time
import httpx
from logger import log
from config import load_config
from auth import get_client, get_session, BROWSER_HEADERS

# 轮询状态
_polling = False
_stock_available = False


def is_stock_available() -> bool:
    """库存是否已释放"""
    return _stock_available


def set_stock_available(val: bool):
    """设置库存状态"""
    global _stock_available
    _stock_available = val


async def check_stock() -> dict:
    """
    查询库存状态
    返回: {"available": bool, "count": int, "raw": response}
    """
    cfg = load_config()
    client = await get_client()
    session = get_session()

    url = cfg["api_base"] + cfg["stock_check_url"]

    # 构建查询参数
    params = {}
    if cfg["product_id"]:
        params["product_id"] = cfg["product_id"]

    headers = session["headers"].copy() if session["headers"] else BROWSER_HEADERS.copy()

    try:
        t0 = time.perf_counter()
        resp = await client.get(url, params=params, headers=headers)
        elapsed = (time.perf_counter() - t0) * 1000

        if resp.status_code == 200:
            data = resp.json()
            # 根据实际接口返回结构判断库存，以下为通用逻辑
            available = False
            stock_count = 0

            # 尝试多种常见返回结构
            if isinstance(data, dict):
                d = data.get("data", data)
                if isinstance(d, dict):
                    available = d.get("available", d.get("in_stock", d.get("has_stock", False)))
                    stock_count = d.get("count", d.get("stock", d.get("remain", d.get("total", 0))))
                elif isinstance(d, bool):
                    available = d

            log.debug(f"[POLL] 库存查询 | 耗时:{elapsed:.0f}ms | 状态码:{resp.status_code} | "
                       f"可用:{available} | 数量:{stock_count}")
            return {"available": available, "count": stock_count, "raw": data, "elapsed": elapsed}
        else:
            log.debug(f"[POLL] 库存查询失败 | 耗时:{elapsed:.0f}ms | 状态码:{resp.status_code}")
            return {"available": False, "count": 0, "raw": resp.text[:200], "elapsed": elapsed}

    except Exception as e:
        log.debug(f"[POLL] 库存查询异常: {e}")
        return {"available": False, "count": 0, "raw": str(e), "elapsed": 0}


async def warmup_connections():
    """
    连接预热：提前与目标服务器建立HTTP/2长连接
    发送几个轻量级请求打通TCP+TLS链路
    """
    cfg = load_config()
    client = await get_client()

    urls = [
        cfg["api_base"],
        cfg["api_base"] + cfg["user_info_url"],
        cfg["api_base"] + cfg["stock_check_url"],
    ]

    log.info("[WARMUP] 开始连接预热...")
    for url in urls:
        try:
            t0 = time.perf_counter()
            resp = await client.get(url, headers=BROWSER_HEADERS.copy())
            elapsed = (time.perf_counter() - t0) * 1000
            log.info(f"[WARMUP] {url} | 状态码:{resp.status_code} | 耗时:{elapsed:.0f}ms")
        except Exception as e:
            log.warning(f"[WARMUP] {url} | 异常: {e}")

    log.info("[WARMUP] 连接预热完成，HTTP/2长连接已建立")


async def start_polling(interval_ms: int = 10, callback=None):
    """
    启动高频库存轮询
    interval_ms: 轮询间隔（毫秒）
    callback: 检测到库存时的回调函数
    """
    global _polling, _stock_available
    _polling = True
    _stock_available = False

    interval = interval_ms / 1000.0
    log.info(f"[POLL] 库存轮询启动 | 间隔:{interval_ms}ms")

    while _polling:
        result = await check_stock()

        if result["available"]:
            _stock_available = True
            log.info(f"[POLL] 检测到库存释放！数量:{result['count']} | 耗时:{result['elapsed']:.0f}ms")
            if callback:
                await callback(result)
            break

        await asyncio.sleep(interval)

    _polling = False
    log.info("[POLL] 库存轮询结束")


def stop_polling():
    """停止轮询"""
    global _polling
    _polling = False
    log.info("[POLL] 库存轮询已停止")


async def dry_run_check():
    """
    测试模式：执行一次完整的库存查询，验证接口连通性
    """
    log.info("[TEST] 测试模式 - 库存查询...")
    result = await check_stock()
    log.info(f"[TEST] 库存查询结果: {result}")
    return result
