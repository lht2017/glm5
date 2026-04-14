# GLM Coding Plan Max 季卡抢购工具

> **仅供个人本地测试使用，请勿用于商业用途或分发给他人。**

## 项目简介

本地运行的准点抢购辅助工具，用于智谱AI (https://open.bigmodel.cn/glm-coding) 的自动抢购。基于 Python 实现，Flask Web 可视化配置，httpx HTTP/2 异步并发，NTP 毫秒级时间校准。

## 功能特性

- **双模式登录**：支持 Token 直填 + 账号密码两种鉴权方式
- **NTP 时间校准**：对接国内 NTP 服务器池，忙等待准点触发，误差 < 10ms
- **多协程并发下单**：基于 httpx AsyncClient HTTP/2，支持 1-32 并发
- **连接预热**：准点前自动建立 TCP/TLS 长连接，消除握手延迟
- **库存高频轮询**：准点前 30 秒启动轮询，最低 1ms 间隔
- **Web 可视化界面**：极简配置面板，实时日志，一键启停
- **自动探测接口**：内置接口路径探测功能，自动识别可用 API
- **配置持久化**：本地保存配置，支持导入导出

## 项目结构

```
glm5/
├── app.py                 # Flask Web 主程序（入口）
├── config.py              # 配置管理模块
├── config.example.json    # 配置文件模板
├── auth.py                # 鉴权与会话管理
├── ntp_sync.py            # NTP 时间同步
├── poller.py              # 库存轮询与连接预热
├── seckill.py             # 准点抢购核心引擎
├── logger.py              # 日志模块
├── requirements.txt       # Python 依赖
├── run.sh                 # 一键启动脚本
├── .gitignore
├── templates/
│   └── index.html         # Web UI
└── logs/                  # 运行日志（自动生成，不提交）
```

## 快速开始

### 1. 安装依赖

```bash
cd glm5
pip install -r requirements.txt
```

依赖会自动安装：Flask、httpx[http2]、ntplib

### 2. 启动服务

```bash
python app.py
# 或
bash run.sh
```

### 3. 打开 Web 界面

浏览器访问 `http://127.0.0.1:5000`

### 4. 配置凭据

在 Web 界面填写以下信息（**首次使用必须配置**）：

#### 获取 Token（推荐方式）

1. 打开 https://open.bigmodel.cn 并登录
2. 按 `F12` 打开开发者工具
3. 切到 `Application` → `Local Storage` → `https://open.bigmodel.cn`
4. 找到 `token` 字段，复制值填入配置页面

#### 获取商品ID和下单参数

1. `F12` → `Network` 标签
2. 在页面上点击 Max 套餐的"购买"按钮
3. 找到请求 `/api/tokenAccounts/purchase`
4. 查看 `Payload` 中的 `product_id` 等参数，填入配置页面

### 5. 测试运行

点击 **"测试运行"** 验证登录和接口连通性。

### 6. 正式抢购

配置好后在抢购时间前点击 **"启动抢购"**，工具会自动完成预热→轮询→准点触发→并发下单全流程。

## 接口路径说明

以下路径从智谱前端源码中提取确认：

| 用途 | 路径 |
|------|------|
| 登录 | `/api/auth/login` |
| 用户信息 | `/api/biz/customer/getCustomerInfo` |
| 限购检查 | `/api/biz/tokenAccounts/isLimitBuy` |
| 购买下单 | `/api/tokenAccounts/purchase` |

> 如果接口变更，可使用 Web 界面的"自动探测接口路径"按钮自动扫描，或手动通过 F12 抓包更新。

## 安全说明

- `config.json` 包含个人凭据，已在 `.gitignore` 中排除，**不会提交到仓库**
- Web 服务仅绑定 `127.0.0.1`，不对外暴露
- 所有凭据仅存储在本地，不会上传至任何第三方服务器

## 免责声明

本项目仅供个人学习和技术研究使用。使用者需自行承担使用风险，作者不对因使用本工具产生的任何后果负责。

## 许可证

仅供个人使用，禁止商业用途。
