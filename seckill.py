"""
准点抢购核心模块 - 最高优先级
基于NTP时间校准的忙等待触发 + httpx多协程并发下单
"""
import asyncio
import time
import httpx
from logger import log
from config import load_config
from auth import (
    get_client, get_session, pre_login,
    build_purchase_headers, build_purchase_payload, close
)
from poller import (
    warmup_connections, start_polling, stop_polling,
    is_stock_available, set_stock_available, dry_run_check
)
from ntp_sync import (
    sync_time, ms_to_target, busy_wait_until,
    get_accurate_timestamp, start_periodic_sync
)

# 全局状态
_task_running = False
_task_success = False
_task_stats = {
    "total_requests": 0,
    "success": False,
    "first_request_time": None,
    "success_time": None,
    "total_elapsed_ms": 0,
    "error_count": 0,
    "status_codes": {},
}


def get_stats() -> dict:
    """获取抢购统计"""
    return _task_stats.copy()


def is_running() -> bool:
    """任务是否在运行"""
    return _task_running


def is_success() -> bool:
    """是否抢购成功"""
    return _task_success


async def _send_purchase(client: httpx.AsyncClient, headers: dict,
                         payload: dict, attempt: int) -> dict:
    """
    发送单次下单请求
    预先生成headers和payload，此函数内无任何额外计算
    """
    global _task_stats
    cfg = load_config()
    url = cfg["api_base"] + cfg["purchase_url"]

    t0 = time.perf_counter()
    try:
        resp = await client.post(url, json=payload, headers=headers)
        elapsed = (time.perf_counter() - t0) * 1000
        _task_stats["total_requests"] += 1

        # 统计状态码
        code = resp.status_code
        _task_stats["status_codes"][code] = _task_stats["status_codes"].get(code, 0) + 1

        try:
            data = resp.json()
        except Exception:
            data = {"raw": resp.text[:300]}

        success = False
        if resp.status_code == 200:
            # 根据实际返回结构判断是否成功
            if isinstance(data, dict):
                success = data.get("success", data.get("code", -1) == 0 or
                          data.get("status") == "ok")
                if not success:
                    success = "order" in str(data).lower() or "success" in str(data).lower()

        log.info(f"[SECKILL] 第{attempt}次请求 | 状态码:{code} | 耗时:{elapsed:.0f}ms | "
                 f"成功:{success} | 响应:{str(data)[:150]}")

        return {
            "success": success,
            "status_code": code,
            "elapsed": elapsed,
            "data": data,
            "attempt": attempt,
        }

    except httpx.TimeoutException:
        _task_stats["error_count"] += 1
        _task_stats["total_requests"] += 1
        log.warning(f"[SECKILL] 第{attempt}次请求超时")
        return {"success": False, "status_code": 0, "elapsed": 0,
                "data": {"error": "timeout"}, "attempt": attempt}
    except Exception as e:
        _task_stats["error_count"] += 1
        _task_stats["total_requests"] += 1
        log.error(f"[SECKILL] 第{attempt}次请求异常: {e}")
        return {"success": False, "status_code": 0, "elapsed": 0,
                "data": {"error": str(e)}, "attempt": attempt}


async def _concurrent_fire(concurrency: int, max_retry: int):
    """
    多协程并发下单核心循环
    concurrency: 并发数
    max_retry: 最大重试次数（0=无限）
    """
    global _task_running, _task_success, _task_stats

    client = await get_client()
    headers = build_purchase_headers()
    payload = build_purchase_payload()

    _task_stats["first_request_time"] = get_accurate_timestamp()

    log.info(f"[SECKILL] 并发下单启动 | 并发数:{concurrency} | 最大重试:{max_retry or '无限'}")

    attempt = 0
    batch = 0

    while _task_running and not _task_success:
        attempt += 1
        batch += 1

        # 检查是否超过最大重试次数
        if max_retry > 0 and attempt > max_retry:
            log.info(f"[SECKILL] 达到最大重试次数 {max_retry}，停止")
            break

        # 并发发送多个请求
        tasks = []
        for i in range(concurrency):
            tasks.append(_send_purchase(client, headers, payload, attempt * concurrency + i))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 检查是否有成功的
        for result in results:
            if isinstance(result, Exception):
                continue
            if result.get("success"):
                _task_success = True
                _task_stats["success"] = True
                _task_stats["success_time"] = get_accurate_timestamp()
                _task_stats["total_elapsed_ms"] = (
                    _task_stats["success_time"] - _task_stats["first_request_time"]
                ) * 1000
                log.info(f"=" * 60)
                log.info(f"[SECKILL] 抢购成功！！！")
                log.info(f"[SECKILL] 总请求:{_task_stats['total_requests']} | "
                         f"总耗时:{_task_stats['total_elapsed_ms']:.0f}ms")
                log.info(f"[SECKILL] 响应数据: {result['data']}")
                log.info(f"=" * 60)
                _task_running = False
                return

        # 动态调整并发数（如果开启）
        cfg = load_config()
        if cfg.get("dynamic_concurrency"):
            # 根据错误率动态调整
            error_rate = _task_stats["error_count"] / max(_task_stats["total_requests"], 1)
            if error_rate > 0.5 and concurrency > 2:
                concurrency = max(2, concurrency - 1)
                log.debug(f"[SECKILL] 错误率过高，降低并发至 {concurrency}")
            elif error_rate < 0.1 and concurrency < 16:
                concurrency = min(16, concurrency + 1)

        # 无间隔，立即进入下一轮

    _task_running = False
    if not _task_success:
        log.info(f"[SECKILL] 抢购结束，未能抢到 | 总请求:{_task_stats['total_requests']}")


async def run_seckill():
    """
    抢购主流程：预登录 -> 连接预热 -> NTP同步 -> 忙等待 -> 轮询/并发下单
    """
    global _task_running, _task_success, _task_stats

    if _task_running:
        log.warning("[SECKILL] 任务已在运行中")
        return

    # 重置状态
    _task_running = True
    _task_success = False
    _task_stats = {
        "total_requests": 0, "success": False,
        "first_request_time": None, "success_time": None,
        "total_elapsed_ms": 0, "error_count": 0, "status_codes": {},
    }

    cfg = load_config()

    try:
        # ========== 阶段1: NTP时间同步 ==========
        log.info("=" * 60)
        log.info("[SECKILL] 阶段1: NTP时间同步")
        sync_time()
        start_periodic_sync(interval_seconds=120)

        # ========== 阶段2: 预登录 ==========
        log.info("[SECKILL] 阶段2: 预登录鉴权")
        if not await pre_login():
            log.error("[SECKILL] 登录失败，任务终止")
            _task_running = False
            return

        # ========== 阶段3: 连接预热 ==========
        remaining = ms_to_target(cfg["target_time"])
        warmup_ms = cfg["warmup_seconds"] * 1000

        if remaining > warmup_ms:
            log.info(f"[SECKILL] 等待连接预热时机（距目标 {remaining/1000:.0f}秒）...")
            wait_s = (remaining - warmup_ms) / 1000.0
            if wait_s > 5:
                log.info(f"[SECKILL] 距预热还有 {wait_s:.0f}秒，先等待...")
                await asyncio.sleep(min(wait_s, 60))
                # 再次检查
                remaining = ms_to_target(cfg["target_time"])

        log.info("[SECKILL] 阶段3: 连接预热")
        await warmup_connections()

        # ========== 阶段4: 库存轮询 ==========
        remaining = ms_to_target(cfg["target_time"])
        poll_ms = cfg["prepare_seconds"] * 1000

        if remaining > poll_ms:
            wait_s = (remaining - poll_ms) / 1000.0
            log.info(f"[SECKILL] 距库存轮询还有 {wait_s:.0f}秒...")
            await asyncio.sleep(min(wait_s, 30))

        log.info("[SECKILL] 阶段4: 库存轮询启动")

        # 启动轮询（检测到库存会自动触发回调）
        poll_task = asyncio.create_task(
            start_polling(interval_ms=cfg["poll_interval_ms"])
        )

        # ========== 阶段5: 忙等待准点 ==========
        log.info("[SECKILL] 阶段5: 忙等待准点触发")
        fire_time = busy_wait_until(cfg["target_time"], early_ms=50)

        log.info(f"[SECKILL] 准点到达！触发时间: {fire_time}")

        # 停止轮询
        stop_polling()

        # ========== 阶段6: 并发下单 ==========
        log.info("[SECKILL] 阶段6: 并发下单（火力全开）")
        await _concurrent_fire(
            concurrency=cfg["concurrency"],
            max_retry=cfg["max_retry"],
        )

    except asyncio.CancelledError:
        log.info("[SECKILL] 任务被取消")
    except Exception as e:
        log.error(f"[SECKILL] 异常: {e}", exc_info=True)
    finally:
        _task_running = False
        log.info("[SECKILL] 任务结束")


async def run_test():
    """
    测试模式：不执行准点抢购，仅验证登录和接口连通性
    """
    global _task_running, _task_success
    _task_running = True
    _task_success = False

    try:
        log.info("=" * 60)
        log.info("[TEST] 测试模式启动")

        log.info("[TEST] 1. NTP时间同步...")
        offset = sync_time()

        log.info("[TEST] 2. 登录测试...")
        if not await pre_login():
            log.error("[TEST] 登录失败")
            return
        log.info("[TEST] 登录成功")

        log.info("[TEST] 3. 连接预热...")
        await warmup_connections()

        log.info("[TEST] 4. 库存查询测试...")
        result = await dry_run_check()
        log.info(f"[TEST] 库存查询结果: {result}")

        log.info("[TEST] 5. 模拟下单测试（测试模式不实际下单）...")
        client = await get_client()
        cfg = load_config()
        headers = build_purchase_headers()
        payload = build_purchase_payload()

        log.info(f"[TEST] 下单地址: {cfg['api_base'] + cfg['purchase_url']}")
        log.info(f"[TEST] 请求体: {payload}")
        log.info(f"[TEST] 请求头已生成，Token前20字符: {headers.get('Authorization', '')[:20]}...")

        if cfg.get("test_mode"):
            log.info("[TEST] 实际发送测试请求...")
            result = await _send_purchase(client, headers, payload, 1)
            log.info(f"[TEST] 下单测试结果: {result}")

        log.info("[TEST] 测试完成！所有模块运行正常")
    except Exception as e:
        log.error(f"[TEST] 测试异常: {e}", exc_info=True)
    finally:
        _task_running = False


def stop_seckill():
    """外部停止抢购任务"""
    global _task_running
    _task_running = False
    stop_polling()
    log.info("[SECKILL] 收到停止指令，任务终止中...")
