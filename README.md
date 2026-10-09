# 银龄伴

面向独居老人的情感陪伴与生活服务助手。项目提供对话、长期记忆、健康知识检索、提醒、天气、图像理解、语音能力和适老化交互等能力，并通过统一的 FastAPI 后端供浏览器端、桌面端或其他客户端接入。

仓库地址：<https://github.com/bo117/yinlingban>

## 功能概览

- 多轮情感对话与老人画像：记录称呼、偏好、家人和慢性病等上下文。
- 健康科普 RAG：从 `backend/data/health_knowledge/` 检索健康知识并返回来源信息。
- 生活服务：提醒、天气、社区信息和常用工具调用。
- 多媒体能力：图片识别/生成、语音识别、语音合成和数字人动作字段。
- 双端使用：浏览器联调页面，以及 Windows `pywebview` 桌面窗口。
- 可扩展部署：默认 SQLite、内存缓存和本地向量存储，也支持通过配置切换 PostgreSQL、Redis、Milvus 和 Docker。

## 项目结构

```text
.
├── backend/
│   ├── app/                 # FastAPI 应用、API 路由、核心服务、数据库和 RAG
│   ├── data/                # 健康知识、运行时数据和生成图片
│   ├── static/              # 前端脚本与样式
│   ├── templates/           # 浏览器联调页面
│   ├── tests/               # 后端、接口和前端联调测试
│   ├── .env.example         # 配置模板（不要提交 .env）
│   ├── requirements.txt     # 后端依赖
│   ├── start.py             # 推荐的后端启动入口
│   └── docker-compose.yml   # Docker Compose 部署
├── desktop.py               # Windows 原生 WebView2 桌面壳
├── 启动银龄伴.pyw            # Windows 双击启动入口
├── desktop-requirements.txt # 桌面端依赖
├── 前端接入文档.md           # WebSocket、REST 和数字人接入协议
├── HANDOFF.md               # 当前交接记录
└── docs/                    # 补充文档
```

## 快速开始（Windows）

### 1. 获取代码

```powershell
git clone https://github.com/bo117/yinlingban.git
cd yinlingban
```

### 2. 创建虚拟环境并安装依赖

建议使用 Python 3.11 或更高版本：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r backend\requirements.txt
```

如需使用 Windows 桌面窗口，再安装桌面依赖：

```powershell
pip install -r desktop-requirements.txt
```

### 3. 创建本地配置

```powershell
Copy-Item backend\.env.example backend\.env
```

至少配置一个对话模型密钥，例如：

```dotenv
DEEPSEEK_API_KEY=你的密钥
```

完整配置项及可用模型见 `backend/.env.example`。`.env`、数据库和桌面运行数据已被 Git 忽略，禁止将真实密钥提交到仓库。

### 4. 启动服务

推荐使用：

```powershell
python backend\start.py --browser
```

服务默认监听 `http://localhost:8000`，启动后可访问：

- 联调页面：<http://localhost:8000/>
- OpenAPI 文档：<http://localhost:8000/docs>
- 健康检查：<http://localhost:8000/health>
- 就绪检查：<http://localhost:8000/ready>

也可以直接双击 `启动银龄伴.pyw` 打开 Windows 桌面窗口。桌面端使用本地 WebView2，首次使用前请确认已安装 WebView2 Runtime。

## Windows 安装版（推荐普通用户）

无需安装 Python 或执行 pip 命令，可以直接下载当前安装包：

- [下载 Yinlingban-Setup-1.0.0.exe](https://github.com/bo117/yinlingban/releases/download/v1.0.0/Yinlingban-Setup-1.0.0.exe)

安装程序会创建桌面快捷方式和开始菜单入口。安装完成后双击“银龄伴”即可启动；应用会在本机启动 FastAPI 服务和 WebView2 窗口，不会额外打开浏览器。

首次使用建议：

1. 确认 Windows 已安装 Microsoft Edge WebView2 Runtime。
2. 打开“设置”，选择对话模型并填写 API Key。
3. 如需语音通话，另外配置 TTS；如需后端语音识别，配置火山引擎 ASR。
4. 如需真实 3D 数字人，还需要配置对应平台的应用凭据；未配置时会保留文字、浏览器语音和占位形象降级能力。

安装版的用户数据保存在 `%LOCALAPPDATA%\Yinlingban`，包括数据库、配置、日志、向量索引、生成图片和 WebView2 缓存。卸载程序不会自动删除这份用户数据，便于重新安装后恢复历史记录；确认不再需要时可手动删除该目录。

## API 与前端接入

后端同时提供 REST 和 WebSocket 接口。完整的请求字段、事件时序、情绪/动作映射和数字人接入示例，请阅读：

- `前端接入文档.md`
- `backend/操作文档.md`

常用入口：

- `POST /api/users`：创建或初始化用户。
- `POST /api/chat`：非流式对话。
- `GET /api/model`：查看当前模型配置。
- `WS /ws`：流式对话和提醒推送。
- `GET /api/quota`：查看当前客户端的调用额度窗口。

## 测试与质量检查

先启动后端，再在另一个终端执行：

```powershell
pytest backend\tests -q
python backend\tests\runtime_acceptance.py
```

涉及前端交互的测试还需要 Node.js；具体脚本位于 `backend/tests/`，运行前请查看脚本顶部的说明。提交前至少确认：服务可以启动、`/health` 返回 200、关键 API 测试通过，并且没有将 `.env` 或运行时数据库加入提交。

## Docker 部署

在 `backend/` 目录下准备 `.env` 后执行：

```powershell
cd backend
docker compose up -d --build
```

然后访问 <http://localhost:8000/>。生产环境可按需配置 PostgreSQL、Redis 和 Milvus；不配置时会自动使用项目默认的 SQLite、内存缓存和本地向量存储。

## Windows 安装包构建

桌面版可以使用 PyInstaller + Inno Setup 构建为安装包。构建机需要安装 Python 3.11+、Inno Setup 6，并确保 WebView2 Runtime 可用：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
.\.venv\Scripts\python.exe -m pip install -r desktop-requirements.txt
powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -InstallDependencies -Installer
```

只生成可运行目录而不调用 Inno Setup：

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

构建产物在 `dist\Yinlingban` 和 `release\Yinlingban-Setup-1.0.0.exe`。安装版的数据库、配置、日志、向量索引和 WebView2 用户数据会写入 `%LOCALAPPDATA%\Yinlingban`，不会写入安装目录。安装包不包含真实 API Key；用户首次启动后通过设置页面配置。

发布说明：`backend/data/` 和运行时目录默认被 Git 忽略。正式发布前，如果需要内置健康知识、社区信息或示例图片，应在构建机准备这些公开资源，确认它们被 spec 文件复制到安装包后再发布。当前仓库中的 `release\Yinlingban-Setup-1.0.0.exe` 是经过 EXE smoke test 和 Inno Setup 编译验证的未签名安装包。

### Windows 代码签名

公开分发前需要购买或申请受信任的代码签名证书（OV/EV 或 Microsoft Trusted Signing），并在本机安装 Windows SDK 的 `signtool.exe`。不要把 `.pfx` 私钥或密码提交到仓库。构建完成后执行：

```powershell
powershell -ExecutionPolicy Bypass -File packaging\sign.ps1 -CertificatePath C:\secure\yinlingban.pfx
```

脚本会签名 `dist\Yinlingban` 中的 PE 文件和 `release\Yinlingban-Setup-1.0.0.exe`，并使用时间戳服务验证签名。自签名证书只能用于内部测试，不能消除普通用户的 SmartScreen 警告。

## 协作开发约定

1. 从最新 `main` 创建功能分支，例如 `feature/reminder-ui`、`fix/ws-timeout`。
2. 一个提交只解决一个主题，提交信息建议使用 `feat:`、`fix:`、`docs:`、`test:` 或 `refactor:` 前缀。
3. 不提交真实 API Key、`backend/.env`、`*.db`、缓存目录、个人运行数据或生成的临时文件。
4. 修改 API、WebSocket 事件或配置项时，同步更新对应文档和测试。
5. 提交 Pull Request 前运行相关测试，并在描述中写明启动方式、验证结果和可能的兼容性影响。
6. 不要直接改写他人的分支；需要联调时优先通过 PR 或明确的共享分支协作。

## 常见问题

- **聊天提示未配置 API Key**：确认 `backend/.env` 存在、变量名正确，并重启服务。
- **端口被占用**：使用 `python backend\start.py --port 8001 --browser`，或结束占用 8000 端口的进程。
- **浏览器打不开本地页面**：确认服务日志中已经出现启动完成信息，并直接访问终端打印的地址；系统代理不应代理 `localhost` 和 `127.0.0.1`。
- **知识库内容未更新**：将 Markdown 文件放入 `backend/data/health_knowledge/` 后重启服务，或按 `backend/操作文档.md` 的接口说明重新导入。
- **前端无法连接 WebSocket**：确认前端使用当前实际端口，并检查浏览器控制台和后端日志中的连接地址。

## 安全说明

本项目面向开发和联调环境。部署到公网前，请重新配置 CORS、API 访问控制、密钥存储、数据库权限和日志脱敏策略；不要把个人健康数据或生产密钥放入公开仓库。

