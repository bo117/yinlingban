# 银龄伴项目交接

更新：2026-09-21，项目目录 C:\Users\Administrator\Desktop\yinlingban_env。

用户最终提供截图：要横向拖动的白色圆球、蓝色填充轨道、灰色剩余轨道，白色圆角弹窗；明确不要选项菜单或“标准/延长”分段按钮。现已按截图改为自定义样式的原生 range 滑块，白色圆球、蓝色当前轨道、灰色剩余轨道、离散档位圆点、蓝色当前强度文字、实际模型名称和重置按钮。原参数映射 null/low/medium/high 保持，支持连续拖动、方向键、重置和外部点击收起。最新截图 ui-reasoning-slider.png；旧 ui-codex-reasoning-menu.png 不代表最终版本。

## 用户目标

最新尺寸修正：推理弹层236px宽，滑块提供36px点击区域、24px轨道和28px白色圆球；模型名11px灰字并可点击打开模型设置。显示直接使用 /health 返回的当前模型，不额外发起可能过时的查询。切换厂商但未指定模型时后端清除旧模型，采用新厂商默认值；手动配置的目录外模型也能在设置中回显。

AI 数字人交互赛道参赛项目。重视实际桌面运行效果、启动和请求响应速度、成熟克制的界面。要求不要默认开浏览器，保留便捷字号按钮，缺 API 要明确提示；任务列表需要右键管理、会话独立记忆；评分/诊断默认隐藏，设置有顶部关闭按钮，推理强度用滑块。

## 已完成

- 原生 pywebview/WebView2 桌面入口 desktop.py / 启动银龄伴.pyw，后端并行启动，HTTP /ready 就绪探测。
- 字号 A−/百分比重置/A+，70%–180%，按文本缩放，避免按钮无谓放大。
- 生图请求正确使用页面所选模型、厂商、临时 Key；展示文案分厂商/能力提供。
- 缺少 API Key 的 REST/WS 结构化反馈、打开设置、草稿保留，本地提醒无需对话 API。
- 会话任务数据库/API、搜索/置顶/右键重命名删除、历史恢复、独立草稿。
- 聊天消息和提取/MCP 长期记忆按 user_id + session_id 隔离。旧用户记忆不注入新会话；提取事实不改写共享档案，旧引导习惯和分型策略不自动跨会话注入。
- WebSocket 每连接独立聊天任务、取消、超时及 request_id；前端首段/静默兜底、5 秒慢响应提示、手动重试。普通默认20秒首段、15秒静默；深入推理/生图另有预算。
- 回复调试信息默认隐藏，高级设置可开启；设置分组折叠，顶部×/Esc关闭、底部保存固定。推理弹出滑块对兼容 GPT 模型发送真实参数。
- 魔珐星云仅预留接口与桥接；官方 SDK 未拿到真实应用凭据，未做云端渲染验收。文档为《魔珐星云接入说明.md》。
- 新增独立便签画布：暖白细网格背景、白/黄/砖红便签、拖动与双击编辑、搜索、缩放、整理、导入导出、撤销/重做和专注模式；画布数据使用独立 `canvas_boards` 表和乐观 revision 保存，不与会话记忆混用。
- 侧栏导航改为带文字的较大点击区域，画布侧栏提供便签搜索和列表；原有应用配色保持不变。
- 修复双击 `启动银龄伴.pyw` 时因 Windows 关联到项目 `Scripts/pythonw.exe` 而提示 `No module named 'webview'` 的启动问题：检测到当前解释器缺少 pywebview 时，自动交给已安装桌面依赖的 `pyw -3` 无控制台启动，并保留真实缺依赖时的中文提示。

## 测试及重要限制

- py -3 backend/tests/test_conversations.py：9项通过，新增画布持久化、用户隔离、revision 冲突和非法备份校验。
- py -3 backend/tests/runtime_acceptance.py：真实 HTTP + headless Edge，任务 CRUD、右键、字体、设置、反馈、跨进程记忆和画布重启恢复均通过；浏览器 JavaScript 异常为0，外部启动请求为0。最新指标看 runtime-acceptance.json。
- 本轮详情/具体替换语句见《对话工作台改动与验收.md》，截图 ui-conversation-workspace.png 和 ui-settings-*.png。
- 本轮原生桌面 smoke 已通过，实际启动数据库迁移成功，窗口连接后退出；此次后端就绪3.749秒、页面加载5.998秒，见 desktop-smoke.json，不宣称桌面秒开。
- 额外用 `Scripts/python.exe desktop.py --smoke-test` 模拟双击关联解释器，确认自动切换 `pyw -3` 后仍能创建 WebView2 窗口并正常退出。
- 不把模拟上游成功宣称真实厂商验收，也不把编译成功当作运行正确。真实云端生成尚未测试。
- 用户确认赛道，但未获得准确对应的比赛官方原文，不能声称完全合规。已有魔珐 SDK 官方页面快照 docs/references/xingyun-sdk-2026-09-14.html。
- 用户要求清理/扩展 Codex 上下文：已用本文件保存状态。本会话没有手动扩展模型上下文窗口的工具；不要修改全局配置猜测上限。OpenAI Docs 官方页面本轮抓取受阻，没有据此宣称扩容。

## 工作环境

Windows PowerShell；py -3 是可用 Python3.14，根目录 Scripts/python.exe 原先不可用。库在根目录 Lib/site-packages。测试脚本自行配置导入路径；直接运行后端时在 backend 目录并设 PYTHONPATH 为 ../Lib/site-packages 和当前目录。

Playwright NODE_PATH=C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules，浏览器 channel=msedge。

中文终端/管道必须 UTF-8：$OutputEncoding=[Console]::OutputEncoding=[Text.UTF8Encoding]::new()，$env:PYTHONIOENCODING='utf-8'。避免因乱码误判代码。项目无 Git 仓库；根目录是虚拟环境，.gitignore 的 * 不要贸然取消。
