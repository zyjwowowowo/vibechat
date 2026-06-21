# VibeChat — AI 驱动的情绪社交

> 先被理解，再遇见同频的人。

VibeChat 是一款基于当下情绪进行匿名匹配的 Web 应用。用户写下一段心情，AI 会识别复合情绪、强度、正负向和唤醒度，再把这些结果真正用于匹配，而不是只展示一个标签。匹配成功后双方进入匿名实时聊天；10 秒无人时，明确标注身份的 AI 旅伴会接住这次表达。

## 核心亮点

- **情绪不只是标签**：输出八维情绪分布、强度、正负向、唤醒度、关键词和解释。
- **分析结果直接驱动匹配**：情绪分布 50% + 正负向 20% + 唤醒度 15% + 强度 10% + 关键词 5%，总分达到 0.65 才匹配。
- **真人优先，AI 兜底**：等待 10 秒仍无同频用户时进入明确标识的 AI 旅伴会话，绝不冒充真人。
- **真正实时匿名聊天**：WebSocket 消息、输入状态、在线状态、断线重连和历史补齐。
- **双标准接口**：同一个 DeepSeek Pro API 可切换 OpenAI Chat Completions 与 Anthropic Messages 两种协议。
- **安全与隐私**：危机表达显示求助提示；原始心情不分享给对方；数据 24 小时后自动清理。

## 技术架构

```text
Next.js 16 / React 19
        │ REST + WebSocket
FastAPI / SQLAlchemy
        ├── OpenAI-compatible adapter ─┐
        ├── Anthropic adapter ─────────┤ DeepSeek Pro API
        └── PostgreSQL (Railway)       │
```

前端位于 `frontend/`，后端位于 `backend/`。开发环境默认使用 SQLite 和规则降级分析，因此没有密钥也能演示完整流程；公网版本使用 Railway PostgreSQL。

## 本地启动

环境要求：Node.js 20+、Python 3.11+。

### 1. 启动后端

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

若暂时没有 LLM 密钥，在 `.env` 设置 `LLM_MOCK_MODE=true`。后端会明确标记 `degraded=true`，但分析、匹配、聊天和 AI 兜底均可继续演示。

### 2. 启动前端

```bash
cd frontend
cp .env.example .env.local
pnpm install
pnpm dev
```

打开 <http://localhost:3000>。使用普通窗口和隐私窗口，可模拟两位匿名用户完成真人匹配。

也可以运行：

```bash
docker compose up --build
```

## DeepSeek Pro：OpenAI 标准模式

后端调用 `{OPENAI_BASE_URL}/chat/completions`，请求使用 Bearer Token 和标准 `messages` 数组。

```env
LLM_PROVIDER=openai
OPENAI_BASE_URL=https://你的服务商地址/v1
OPENAI_API_KEY=你的密钥
OPENAI_MODEL=deepseekpro
LLM_MOCK_MODE=false
```

启动：

```bash
uvicorn app.main:app --reload --port 8000
curl http://localhost:8000/health
```

健康接口应显示 `provider: openai`、`model: deepseekpro` 和 `llm_configured: true`。

## DeepSeek Pro：Anthropic 标准模式

后端调用 `{ANTHROPIC_BASE_URL}/messages`，发送 `x-api-key`、`anthropic-version: 2023-06-01` 和标准 content blocks。

```env
LLM_PROVIDER=anthropic
ANTHROPIC_BASE_URL=https://你的服务商地址/v1
ANTHROPIC_API_KEY=你的密钥
ANTHROPIC_MODEL=deepseekpro
LLM_MOCK_MODE=false
```

重启后端并访问 `/health`，应显示 `provider: anthropic`。两套适配器拥有独立环境变量，不会把密钥或模型名打包到浏览器。

> Base URL 是否需要包含 `/v1` 以 DeepSeek Pro API 服务商控制台为准；应用只在末尾追加 `/chat/completions` 或 `/messages`。

## API

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| `POST` | `/api/v1/sessions` | 创建匿名身份 |
| `GET` | `/api/v1/sessions/me` | 恢复匿名身份 |
| `POST` | `/api/v1/emotions/analyze` | LLM 情绪分析 |
| `POST` | `/api/v1/matches` | 创建匹配请求 |
| `GET` | `/api/v1/matches/{id}` | 查询匹配，超时触发 AI 兜底 |
| `DELETE` | `/api/v1/matches/{id}` | 取消等待 |
| `GET` | `/api/v1/conversations/{id}` | 会话与历史消息 |
| `POST` | `/api/v1/conversations/{id}/messages` | HTTP 消息兜底 |
| `WS` | `/api/v1/ws/conversations/{id}` | 实时聊天、输入和在线状态 |
| `GET` | `/health` | 部署健康状态 |

除创建匿名身份和健康检查外，REST 请求需要 `X-Session-Token`；WebSocket 通过 `Sec-WebSocket-Protocol` 传递匿名 token，避免凭据出现在 URL 日志中。token 不包含真实身份信息。

## Railway 部署

1. 从 GitHub 仓库创建 Railway Project，并添加 PostgreSQL。
2. 添加 API Service，Root Directory 设为 `/backend`。Railway 会读取 `backend/railway.json` 和 Dockerfile。
3. API 设置 `DATABASE_URL=${{Postgres.DATABASE_URL}}`、两组 DeepSeek Pro 配置、`LLM_PROVIDER=openai`、`CORS_ORIGINS=<前端公网域名>`。
4. 为 API 生成公网域名，确认 `/health` 返回 `status: ok`。
5. 添加 Web Service，Root Directory 设为 `/frontend`，设置 `NEXT_PUBLIC_API_URL=<API公网域名>`，再生成公网域名。
6. 回到 API 更新 `CORS_ORIGINS` 为最终 Web 域名并重新部署。
7. 切换 `LLM_PROVIDER=anthropic` 重新部署 API，跑一次完整流程；确认后切回比赛默认的 `openai`。

后端固定单 worker，以保证当前 Demo 的 WebSocket 房间广播一致。后续横向扩容时应将广播层替换为 Redis Pub/Sub。

## 测试

```bash
cd backend
pytest -q

cd ../frontend
pnpm build
```

建议上线后按以下顺序回归：情绪分析 → 两浏览器真人匹配 → 双向发消息 → 刷新恢复 → 单浏览器 AI 兜底 → 模型超时降级 → 危机提示。

## 线上演示

- Web：部署后填写
- API Health：部署后填写
- 测试账号：无需账号，打开页面即生成匿名身份
- 数据说明：匿名会话 24 小时后自动清理

## 100 字以内产品介绍

VibeChat 用 AI 读懂你此刻的复合情绪，将真正同频的陌生人匿名连接。情绪分析直接决定匹配，无人等待时，透明标识的 AI 旅伴也会温柔接住每一次表达。

## 演示视频脚本（约 4 分钟）

1. **0:00–0:30 产品命题**：访问线上地址，介绍“先被理解，再遇见同频的人”。
2. **0:30–1:20 情绪分析**：输入一段复杂心情，展示主情绪、光谱、强度、关键词与解释；强调原始文字不会分享。
3. **1:20–2:20 真人匹配**：普通窗口和隐私窗口输入相近心情，展示同频度及双向实时消息。
4. **2:20–3:00 AI 兜底**：单独发起一次匹配，10 秒后进入明确标记的 AI 旅伴并收到回复。
5. **3:00–3:35 技术亮点**：展示 README 的匹配公式和 OpenAI/Anthropic 两种 DeepSeek Pro 配置。
6. **3:35–4:00 稳定性**：展示刷新恢复、降级提示和线上 `/health`，以产品介绍收尾。

## 安全声明

VibeChat 不是心理咨询、医疗诊断或紧急救援服务。检测到高风险文字时会提示用户联系当地紧急服务或可信任的人，但不会声称能够替代专业帮助。
