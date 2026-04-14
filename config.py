"""
配置管理模块 - GLM Coding Plan Max 季卡抢购工具
负责所有配置项的加载、保存、默认值管理
"""
import json
import os

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

# 默认配置
DEFAULT_CONFIG = {
    # === 鉴权配置 ===
    "auth_mode": "token",                # 登录模式: token / password
    "token": "",                          # API Token（从浏览器开发者工具获取）
    "username": "",                       # 账号（手机号/邮箱）
    "password": "",                       # 密码

    # === 抢购时间 ===
    "target_time": "10:00:00",            # 每日抢购目标时间（北京时间）
    "prepare_seconds": 30,                # 提前多少秒开始库存轮询
    "warmup_seconds": 60,                 # 提前多少秒预热连接

    # === 并发与重试 ===
    "concurrency": 8,                     # 并发下单协程数
    "max_retry": 0,                       # 最大重试次数（0=无限重试直到成功或库存耗尽）
    "poll_interval_ms": 10,               # 库存轮询间隔（毫秒），最低1ms

    # === 接口地址 ===
    # 从智谱前端JS源码中确认的真实路径 (baseURL="/api")
    "api_base": "https://open.bigmodel.cn",
    "login_url": "/api/auth/login",                            # 登录接口（已确认）
    "stock_check_url": "/api/biz/tokenAccounts/isLimitBuy",    # 限购/库存查询（已确认）
    "purchase_url": "/api/tokenAccounts/purchase",             # 购买下单接口（已确认）
    "user_info_url": "/api/biz/customer/getCustomerInfo",      # 用户信息接口（已确认）

    # === 商品ID ===
    # 套餐标识: 需抓包确认实际值
    # 可能是字符串(如"max_season", "coding_plan_max")或数字ID
    "product_id": "max",                  # GLM Coding Plan Max 季卡标识

    # === 高级配置 ===
    "timeout_seconds": 5,                 # 单次请求超时（秒）
    "dynamic_concurrency": True,          # 动态调整并发数
    "test_mode": False,                   # 测试模式（不实际下单）
    "auto_save_config": True,             # 自动保存配置

    # === 下单请求体模板（高级，需抓包后补充） ===
    # 根据实际抓到的下单请求参数填写，留空则只发product_id
    "purchase_extra_params": {},           # 额外参数，如 {"period": "season", "auto_renew": false}
}


def load_config():
    """加载配置，优先从config.json读取，不存在则使用默认值"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            # 合并：已保存的值覆盖默认值，新增的默认值保留
            merged = {**DEFAULT_CONFIG, **saved}
            return merged
        except (json.JSONDecodeError, IOError):
            pass
    return DEFAULT_CONFIG.copy()


def save_config(cfg):
    """保存配置到config.json"""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def update_config(updates: dict):
    """局部更新配置"""
    cfg = load_config()
    cfg.update(updates)
    save_config(cfg)
    return cfg


def export_config():
    """导出配置为JSON字符串"""
    return json.dumps(load_config(), ensure_ascii=False, indent=2)


def import_config(json_str: str):
    """从JSON字符串导入配置"""
    cfg = json.loads(json_str)
    save_config(cfg)
    return cfg
