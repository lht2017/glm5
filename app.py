"""
Flask Web应用 - GLM Coding Plan Max 季卡抢购工具
极简可视化配置界面 + 实时日志 + 一键启动/停止
"""
import os
import sys
import asyncio
import threading
import subprocess

from flask import Flask, render_template, request, jsonify
from logger import log, get_logs
from config import load_config, save_config, export_config, import_config

# 确保项目根目录在sys.path中
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

app = Flask(__name__, template_folder=os.path.join(BASE_DIR, "templates"))

# 后台事件循环（运行异步抢购任务）
_loop = None
_loop_thread = None


def _get_or_create_loop():
    """获取或创建后台事件循环"""
    global _loop, _loop_thread
    if _loop is None or not _loop.is_running():
        _loop = asyncio.new_event_loop()

        def _run_loop():
            asyncio.set_event_loop(_loop)
            _loop.run_forever()

        _loop_thread = threading.Thread(target=_run_loop, daemon=True)
        _loop_thread.start()
    return _loop


def _run_async(coro):
    """在后台事件循环中运行异步协程"""
    loop = _get_or_create_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future


# ========== 路由 ==========

@app.route("/")
def index():
    """主页"""
    return render_template("index.html")


@app.route("/api/config", methods=["GET"])
def get_config():
    """获取当前配置"""
    return jsonify(load_config())


@app.route("/api/config", methods=["POST"])
def update_config():
    """更新配置"""
    data = request.get_json()
    cfg = load_config()
    cfg.update(data)
    save_config(cfg)
    return jsonify({"ok": True, "msg": "配置已保存"})


@app.route("/api/config/export", methods=["GET"])
def do_export():
    """导出配置"""
    return jsonify({"ok": True, "data": export_config()})


@app.route("/api/config/import", methods=["POST"])
def do_import():
    """导入配置"""
    data = request.get_json()
    json_str = data.get("config", "")
    try:
        cfg = import_config(json_str)
        return jsonify({"ok": True, "msg": "导入成功", "data": cfg})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)})


@app.route("/api/start", methods=["POST"])
def start_task():
    """启动抢购任务"""
    from seckill import is_running
    if is_running():
        return jsonify({"ok": False, "msg": "任务已在运行中"})

    # 先保存最新配置
    data = request.get_json() or {}
    if data:
        cfg = load_config()
        cfg.update(data)
        save_config(cfg)

    from seckill import run_seckill
    _run_async(run_seckill())
    return jsonify({"ok": True, "msg": "抢购任务已启动"})


@app.route("/api/stop", methods=["POST"])
def stop_task():
    """停止抢购任务"""
    from seckill import stop_seckill
    stop_seckill()
    return jsonify({"ok": True, "msg": "任务停止指令已发送"})


@app.route("/api/test", methods=["POST"])
def test_task():
    """测试模式"""
    from seckill import is_running
    if is_running():
        return jsonify({"ok": False, "msg": "任务已在运行中"})

    from seckill import run_test
    _run_async(run_test())
    return jsonify({"ok": True, "msg": "测试模式已启动"})


@app.route("/api/status", methods=["GET"])
def get_status():
    """获取当前状态"""
    from seckill import is_running, is_success, get_stats
    from ntp_sync import get_accurate_time

    stats = get_stats()
    stats["running"] = is_running()
    stats["success"] = is_success()
    stats["current_time"] = str(get_accurate_time().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3])
    return jsonify(stats)


@app.route("/api/logs", methods=["GET"])
def get_log_content():
    """获取日志内容"""
    lines = request.args.get("lines", 200, type=int)
    return jsonify({"ok": True, "logs": get_logs(lines)})


@app.route("/api/ntp/sync", methods=["POST"])
def manual_ntp_sync():
    """手动触发NTP同步"""
    from ntp_sync import sync_time
    offset = sync_time()
    return jsonify({"ok": True, "offset_ms": round(offset, 2)})


@app.route("/api/probe", methods=["POST"])
def probe_apis():
    """自动探测API接口路径"""
    from seckill import is_running
    if is_running():
        return jsonify({"ok": False, "msg": "任务运行中，无法探测"})

    from auth import probe_api_endpoints
    future = _run_async(probe_api_endpoints())
    try:
        results = future.result(timeout=30)
        return jsonify({"ok": True, "results": results})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)})


def check_and_install_deps():
    """启动时自动检查并安装依赖"""
    deps = {
        "flask": "flask",
        "httpx": "httpx[http2]",
        "ntplib": "ntplib",
    }
    missing = []
    for module, pkg in deps.items():
        try:
            __import__(module)
        except ImportError:
            missing.append(pkg)

    if missing:
        log.info(f"[INIT] 检测到缺少依赖: {missing}，正在自动安装...")
        for pkg in missing:
            try:
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", pkg, "-q"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                log.info(f"[INIT] 已安装: {pkg}")
            except subprocess.CalledProcessError:
                log.error(f"[INIT] 安装失败: {pkg}，请手动执行: pip install {pkg}")
        log.info("[INIT] 依赖安装完成")
    else:
        log.info("[INIT] 所有依赖已就绪")


if __name__ == "__main__":
    # 自动检查依赖
    check_and_install_deps()

    # 启动时同步一次NTP
    from ntp_sync import sync_time
    sync_time()

    log.info("=" * 60)
    log.info("GLM Coding Plan Max 季卡抢购工具 已启动")
    log.info("Web界面: http://127.0.0.1:5000")
    log.info("=" * 60)

    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)
