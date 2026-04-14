"""
鉴权与会话管理模块
支持Token直填 + 账号密码双模式登录
自动维护Cookie/Token，预登录保活
"""
import asyncio
import httpx
from datetime import datetime
from logger import log
from config import load_config

# 预生成的浏览器请求头（Chrome最新版特征）
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "Origin": "https://open.bigmodel.cn",
    "Referer": "https://open.bigmodel.cn/",
}

# 内存中的会话状态
_session = {
    "token": None,
    "cookies": {},
    "headers": {},
    "logged_in": False,
    "login_time": None,
    "client": None,         # httpx.AsyncClient 长连接实例
    "ready": False,         # 预热就绪标志
}


def get_session():
    """获取当前会话状态"""
    return _session


async def get_client() -> httpx.AsyncClient:
    """
    获取或创建httpx异步客户端（HTTP/2长连接）
    全生命周期复用同一个client，避免重复建连
    """
    if _session["client"] is None or _session["client"].is_closed:
        _session["client"] = httpx.AsyncClient(
            http2=True,
            timeout=httpx.Timeout(
                connect=3.0,
                read=5.0,
                write=3.0,
                pool=3.0
            ),
            limits=httpx.Limits(
                max_connections=50,
                max_keepalive_connections=20,
                keepalive_expiry=120,
            ),
            headers=BROWSER_HEADERS.copy(),
            verify=False,  # 不验证SSL，减少握手耗时
        )
        log.info("[AUTH] HTTP/2 AsyncClient 已创建，连接池就绪")
    return _session["client"]


async def login_with_token(token: str) -> bool:
    """
    Token直填模式登录
    token: 从浏览器开发者工具 > Application > Local Storage 中获取的JWT Token
    """
    client = await get_client()
    cfg = load_config()

    _session["token"] = token
    headers = BROWSER_HEADERS.copy()
    headers["Authorization"] = f"Bearer {token}"
    _session["headers"] = headers

    # 用Token请求用户信息，验证Token有效性
    try:
        url = cfg["api_base"] + cfg["user_info_url"]
        resp = await client.get(url, headers=headers)

        if resp.status_code == 200:
            data = resp.json()
            _session["logged_in"] = True
            _session["login_time"] = datetime.now()
            _session["cookies"] = dict(resp.cookies)
            log.info(f"[AUTH] Token登录成功 | 用户: {data.get('data', {}).get('name', 'unknown')}")
            return True
        else:
            log.warning(f"[AUTH] Token验证失败 | 状态码: {resp.status_code} | 响应: {resp.text[:200]}")
            return False
    except Exception as e:
        log.error(f"[AUTH] Token登录异常: {e}")
        return False


async def login_with_password(username: str, password: str) -> bool:
    """
    账号密码模式登录
    智谱平台登录接口: POST /api/auth/login
    支持手机号+密码、邮箱+密码
    """
    client = await get_client()
    cfg = load_config()

    url = cfg["api_base"] + cfg["login_url"]
    payload = {
        "username": username,
        "password": password,
    }
    headers = BROWSER_HEADERS.copy()
    headers["Content-Type"] = "application/json"

    try:
        resp = await client.post(url, json=payload, headers=headers)
        data = resp.json()

        # 智谱平台登录成功后返回token
        # 可能的返回结构: {"data": {"token": "xxx"}} 或 {"token": "xxx"}
        token = None
        if resp.status_code == 200:
            if isinstance(data, dict):
                token = (data.get("data", {}) or {}).get("token") or data.get("token")

            # 也可能通过Set-Cookie返回
            if not token and resp.cookies:
                token = resp.cookies.get("token")

            if token:
                _session["token"] = token
                headers["Authorization"] = f"Bearer {token}"
                _session["headers"] = headers
                _session["logged_in"] = True
                _session["login_time"] = datetime.now()
                _session["cookies"] = dict(resp.cookies)
                log.info(f"[AUTH] 账号密码登录成功")
                return True

        log.warning(f"[AUTH] 登录失败 | 状态码:{resp.status_code} | 响应:{resp.text[:200]}")
        return False
    except Exception as e:
        log.error(f"[AUTH] 登录异常: {e}")
        return False


async def do_login() -> bool:
    """根据配置自动选择登录方式"""
    cfg = load_config()

    if cfg["auth_mode"] == "token" and cfg["token"]:
        return await login_with_token(cfg["token"])
    elif cfg["auth_mode"] == "password" and cfg["username"] and cfg["password"]:
        return await login_with_password(cfg["username"], cfg["password"])
    else:
        log.warning("[AUTH] 无可用登录凭据，请先在Web界面配置Token或账号密码")
        return False


async def refresh_session() -> bool:
    """刷新会话（保活），提前30分钟调用"""
    if not _session["logged_in"]:
        return await do_login()

    # 重新验证Token是否有效
    cfg = load_config()
    client = await get_client()
    try:
        url = cfg["api_base"] + cfg["user_info_url"]
        resp = await client.get(url, headers=_session["headers"])
        if resp.status_code == 200:
            _session["login_time"] = datetime.now()
            log.debug("[AUTH] 会话刷新成功，Token仍有效")
            return True
        else:
            log.warning("[AUTH] Token已失效，重新登录...")
            return await do_login()
    except Exception as e:
        log.error(f"[AUTH] 会话刷新异常: {e}")
        return False


async def pre_login():
    """
    预登录：提前30分钟自动登录并启动保活定时器
    """
    log.info("[AUTH] 开始预登录...")
    ok = await do_login()
    if ok:
        log.info("[AUTH] 预登录成功，会话已就绪")
        _session["ready"] = True
    else:
        log.error("[AUTH] 预登录失败！请检查Token/账号密码配置")
        _session["ready"] = False
    return ok


async def close():
    """关闭HTTP客户端"""
    if _session["client"] and not _session["client"].is_closed:
        await _session["client"].aclose()
        _session["client"] = None
        log.info("[AUTH] HTTP客户端已关闭")


def build_purchase_headers() -> dict:
    """
    构建下单请求头（预先生成，准点时直接使用）
    """
    headers = _session["headers"].copy()
    headers["Content-Type"] = "application/json"
    return headers


def build_purchase_payload() -> dict:
    """
    构建下单请求体（预先生成，准点时直接使用）
    """
    cfg = load_config()
    payload = {
        "product_id": cfg["product_id"],
    }
    # 合入用户配置的额外参数
    extra = cfg.get("purchase_extra_params", {})
    if extra:
        payload.update(extra)
    return payload


# ========== 自动探测接口路径 ==========
# 从智谱前端JS源码(app.5417d0d6.js)确认的真实路径模式
# baseURL="/api", 业务路径前缀="/biz/"
_API_PATTERNS = {
    "login": [
        "/api/auth/login",                          # 已确认: 源码中 "/auth/login"
        "/api/biz/customer/login",
        "/api/login",
    ],
    "stock": [
        "/api/biz/tokenAccounts/isLimitBuy",        # 已确认: 限购检查接口
        "/api/biz/coding-plan/stock",
        "/api/biz/subscribe/stock",
        "/api/biz/coding-plan/isLimitBuy",
    ],
    "purchase": [
        "/api/tokenAccounts/purchase",              # 已确认: 源码中 "/tokenAccounts/purchase"
        "/api/biz/coding-plan/buy",
        "/api/biz/subscribe/order",
        "/api/biz/coding-plan/subscribe",
        "/api/biz/subscribe/create-order",
        "/api/pay/bank/createBankOrder",             # 已确认: 银行支付接口
    ],
    "user_info": [
        "/api/biz/customer/getCustomerInfo",         # 已确认: 用户信息接口
        "/api/biz/customerService/authTokenForBootstrap",  # 已确认: auth token
    ],
}


async def probe_api_endpoints() -> dict:
    """
    自动探测可用的API接口路径
    逐一尝试常见路径，记录哪些返回了有效响应（非404）
    返回: {"login": "找到的路径", "stock": "...", ...}
    """
    client = await get_client()
    results = {}

    for category, paths in _API_PATTERNS.items():
        for path in paths:
            url = load_config()["api_base"] + path
            try:
                if category == "login":
                    resp = await client.post(url, json={}, timeout=3.0)
                else:
                    headers = _session["headers"] if _session["headers"] else BROWSER_HEADERS.copy()
                    resp = await client.get(url, headers=headers, timeout=3.0)

                status = resp.status_code
                # 非404/405说明路径存在（可能是401未授权，但路径是对的）
                if status not in (404, 405):
                    results[category] = path
                    log.info(f"[PROBE] {category} -> {path} (状态码:{status})")
                    break
                else:
                    log.debug(f"[PROBE] {path} -> {status} (跳过)")
            except Exception as e:
                log.debug(f"[PROBE] {path} -> 异常: {e}")

    return results
