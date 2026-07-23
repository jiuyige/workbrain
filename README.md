# WorkBrain

WorkBrain 是一个可部署的企业知识库与 IT 服务申请助手。它把多组织权限、异步文档处理、带引用的 RAG、IT 服务审批，以及“补全信息 → 用户确认 → 创建申请”的 Agent 安全闭环整合到同一个全栈产品中。

项目重点不是演示一次模型调用，而是展示 AI 应用进入真实业务系统时所需的数据隔离、权限控制、异步任务、审计、幂等、测试和部署能力。

> 当前仓库提供完整源码、自动化测试和生产化 Docker 编排。当前仓库不声明已经部署到公网；公网域名、云主机、真实密钥和线上数据仍需由部署者配置。

## 产品闭环

```text
注册 / 登录
  → 创建或切换组织
  → 创建企业知识库
  → 上传文档
  → Celery 异步解析、切块和向量化
  → 审批发布
  → 带引用来源的 RAG 问答
  → 浏览 IT 服务目录
  → Agent 识别申请意图并补全信息
  → 用户确认后创建 pending 申请
  → approver / admin 批准或拒绝
  → 申请人查看结果和审计记录
```

前端已覆盖注册、登录、组织与成员、知识库、文档、RAG 问答、服务目录、我的申请、审批工作台和服务 Agent 页面。

## 核心能力

### 企业身份与权限

- 用户注册、登录、JWT 鉴权和受保护路由
- 组织、成员与 RBAC，支持 `member`、`approver`、`admin`
- 通过 `X-Organization-ID` 显式选择当前组织
- 组织、知识库、文档、服务目录、申请、日志和 Agent Trace 跨组织隔离
- 普通成员只能查看自己的申请；approver/admin 可查看组织内申请
- 申请人不能审批自己的申请，已结束申请不能重复审批

### 企业知识库与 RAG

- 多知识库管理和组织级数据隔离
- TXT、Markdown 文档上传安全校验和大小限制
- Celery + Redis 异步解析、切块、Embedding 和任务重试
- 后台任务原子领取、幂等执行、状态与失败原因查询
- 文档版本、发布、归档、生命周期事件和处理日志
- PostgreSQL + pgvector 向量检索与关键词相关度联合过滤
- 资料不足时拒答，回答返回 `[S1]`、`[S2]` 等引用来源
- RAG 查询日志、延迟、命中数量和来源分块记录

### IT 服务申请审批与审计、Agent

- IT 服务目录创建、编辑、软停用、重新启用和分页
- 成员创建申请并查看自己的申请、状态和审计记录
- approver/admin 批准或填写原因后拒绝申请
- 申请创建、批准和拒绝事件均记录操作者、前后状态、原因与时间
- 企业服务 Agent 查询当前组织目录和当前用户申请
- 自然语言识别申请意图，服务不明确时返回候选项，字段缺失时要求补充
- 完整信息先生成确认卡片；只有用户提交确认令牌后才写入数据库
- 确认时重新校验用户、组织、服务启用状态，并通过令牌哈希和消费状态保证幂等
- Todo Agent 与企业服务 Agent 相互独立，不共用危险操作入口

### 可观测性与生产化

- 统一错误响应、`X-Request-ID` 和请求日志关联
- Tool Call 日志、Agent Trace、RAG 日志、文档任务和业务审计
- liveness、readiness、数据库和 Redis 健康检查
- Alembic 迁移先于 API 与 Worker 启动
- PostgreSQL、Redis AOF、上传文件和 Caddy 证书持久化
- API 与 Celery Worker 使用非 root 用户运行
- Caddy 暴露 80/443，Nginx 托管 React SPA 并代理 `/api`

## 技术栈

| 层级 | 技术 |
| --- | --- |
| 前端 | React 19、TypeScript、Vite、React Router、Vitest |
| API | FastAPI、Pydantic、SQLModel、SQLAlchemy |
| 鉴权 | JWT、Argon2、组织上下文、RBAC |
| 数据库 | PostgreSQL 16、pgvector、Alembic |
| 异步任务 | Celery、Redis |
| LLM / Agent | DeepSeek、原生 Tool Calling |
| Embedding | OpenAI Embeddings |
| 网关与部署 | Docker Compose、Caddy、Nginx |
| 质量检查 | Pytest、Ruff、ESLint、TypeScript |

## 系统架构

```mermaid
flowchart LR
    Browser["React SPA"] --> Gateway["Caddy :80/:443"]
    Gateway --> Nginx["Nginx"]
    Nginx -->|"/api"| API["FastAPI"]
    API --> DB[("PostgreSQL + pgvector")]
    API --> Redis[("Redis")]
    Worker["Celery Worker"] --> Redis
    Worker --> DB
    API --> DeepSeek["DeepSeek"]
    API --> OpenAI["OpenAI Embeddings"]
    Worker --> OpenAI
    API --> Uploads[("Uploads volume")]
    Worker --> Uploads
```

更完整的组件边界、文档/RAG 数据流和 Agent 审批数据流见：

- [系统架构与核心数据流](doc/architecture.md)
- [Agent 技术方案对比与 MCP 小型 Demo](doc/agent-framework-comparison.md)
- [5 分钟演示与录屏指南](doc/demo-guide.md)
- [简历描述与面试讲解稿](doc/resume-and-interview.md)
- [RAG 固定评测集](evals/rag_retrieval_cases.json)

## 项目结构

```text
app/                         FastAPI、领域模型、Agent、RAG 与异步任务
app/routers/                 用户、组织、知识库、文档、服务与 Agent API
alembic/                     数据库迁移
frontend/                    React + TypeScript 前端
tests/                       后端单元、权限、集成与端到端测试
evals/                       固定 RAG 评测数据
scripts/                     RAG 评测、参数实验、生产冒烟脚本
experiments/                 非生产 MCP 只读 Demo
doc/                         架构与技术方案文档
docker-compose.yml           生产化完整编排
docker-compose.dev.yml       仅供本机开发暴露数据库、Redis 和 API
Caddyfile                    公网入口与 HTTPS
```

## 本地开发

### 1. 前置条件

- Python 3.13
- Node.js 24 与 npm
- Docker 与 Docker Compose

### 2. 安装后端和前端依赖

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt

cd frontend
npm ci
cd ..
```

### 3. 配置开发环境

从模板创建本地配置：

```bash
cp .env.example .env
```

将 `.env` 至少调整为本地开发配置。数据库 URL 中的密码必须与 `POSTGRES_PASSWORD` 相同：

```env
APP_ENV=development
POSTGRES_USER=workbrain
POSTGRES_PASSWORD=workbrain-local-password
POSTGRES_DB=workbrain
DATABASE_URL=postgresql+psycopg://workbrain:workbrain-local-password@localhost:5432/workbrain
SECRET_KEY=local-development-secret-key-32-characters-minimum
CORS_ORIGINS=http://localhost:5173
SITE_ADDRESS=http://localhost
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1
```

使用真实 RAG 和 Agent 功能还需要填写 `DEEPSEEK_API_KEY` 和 `OPENAI_API_KEY`。普通自动化测试会替换模型调用，不会产生模型费用。

不要提交 `.env`。也不要把 `docker compose config`、`printenv` 或完整容器环境输出复制到日志，因为这些内容可能展开真实密钥。

### 4. 启动 PostgreSQL 和 Redis

`docker-compose.dev.yml` 只把开发需要的端口绑定到 `127.0.0.1`：

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d postgres redis
```

执行迁移：

```bash
alembic upgrade head
alembic current
```

### 5. 启动 API 与 Celery Worker

终端一：

```bash
source .venv/bin/activate
uvicorn app.main:app --reload
```

终端二：

```bash
source .venv/bin/activate
celery -A app.celery_app:celery_app worker --loglevel=INFO --queues=celery,document_processing
```

API 地址为 `http://127.0.0.1:8000`，交互式接口文档为 `http://127.0.0.1:8000/docs`。

### 6. 启动前端

```bash
cd frontend
npm run dev
```

浏览器访问 `http://localhost:5173`。Vite 会把 `/api` 请求代理到本地 FastAPI。

### 7. 停止本地基础设施

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml down
```

不加 `-v` 会保留数据库、Redis 和上传文件卷。

## 使用 Docker 启动完整产品

此模式会构建并启动 PostgreSQL、Redis、迁移任务、FastAPI、Celery Worker、React/Nginx 和 Caddy。

### 1. 准备生产配置

```bash
cp .env.example .env
```

必须替换示例值：

- `POSTGRES_PASSWORD`：强随机数据库密码
- `DATABASE_URL`：密码与上面一致，Docker 内数据库主机保持 `postgres`
- `SECRET_KEY`：至少 32 个字符的强随机密钥
- `DEEPSEEK_API_KEY`、`OPENAI_API_KEY`：真实模型密钥
- `SITE_ADDRESS`：正式域名，例如 `workbrain.example.com`
- `CORS_ORIGINS`：允许的 HTTPS 前端来源，不允许生产环境使用 `*`

完整变量及默认值见 [.env.example](.env.example)。

### 2. 部署前检查并启动

下面的 `--quiet` 只校验 Compose，不把展开后的密钥打印到终端：

```bash
docker compose config --quiet
docker compose build
docker compose up --build -d
docker compose ps -a
```

`migrate` 和 `uploads-init` 正常完成后会显示为 exited；`postgres`、`redis`、`api`、`worker`、`frontend` 和 `gateway` 应为 running/healthy。

查看有限范围日志：

```bash
docker compose logs --tail=100 migrate api worker gateway
```

本机部署默认访问 `http://localhost`。通过域名上线时，还需要：

1. 将域名 A/AAAA 记录指向服务器。
2. 在防火墙开放 80 和 443。
3. 把 `SITE_ADDRESS` 设置为该域名。
4. 把 `CORS_ORIGINS` 设置为对应的 `https://` 来源。
5. 重启 gateway，让 Caddy 自动申请和续期 HTTPS 证书。

### 3. 生产冒烟测试

冒烟脚本会创建带随机后缀的测试用户和组织，走通鉴权、知识库、服务申请与后台任务，因此应在允许写入演示数据的环境执行：

```bash
.venv/bin/python scripts/production_smoke.py --base-url http://localhost
```

公网示例：

```bash
.venv/bin/python scripts/production_smoke.py --base-url https://workbrain.example.com
```

成功时输出 JSON，`status` 为 `passed`。健康检查也可以独立验证：

```bash
curl --fail http://localhost/api/health/live
curl --fail http://localhost/api/health/ready
```

### 4. 生成作品集演示数据

在本地、预发布或允许保存演示数据的环境运行：

```bash
.venv/bin/python scripts/seed_demo_data.py --base-url http://localhost
```

脚本只通过公开 API 创建三个演示账号、一个组织、一个知识库、三个服务项目，以及 `approved`、`rejected`、`pending` 三种申请状态。输出包含随机演示密码，不要提交到 Git 或展示在公开录屏中。

生成数据后，按照 [演示与录屏指南](doc/demo-guide.md) 上传 `evals/enterprise_it_service_handbook.md`，即可演示异步文档处理、带引用 RAG、Agent 确认、审批和审计闭环。

## 环境变量

| 变量 | 用途 |
| --- | --- |
| `APP_ENV` | `development`、`test` 或 `production` |
| `DATABASE_URL` | SQLAlchemy PostgreSQL 连接串 |
| `SECRET_KEY` | JWT 签名密钥，生产环境至少 32 字符 |
| `CORS_ORIGINS` | 逗号分隔的允许来源 |
| `SITE_ADDRESS` | Caddy 监听地址或正式域名 |
| `UPLOAD_DIR` / `UPLOAD_MAX_BYTES` | 上传目录和单文件限制 |
| `DEEPSEEK_API_KEY` / `DEEPSEEK_MODEL` | 对话和 Tool Calling |
| `OPENAI_API_KEY` / `OPENAI_EMBEDDING_MODEL` | 文档与问题向量化 |
| `OPENAI_EMBEDDING_DIMENSIONS` | pgvector 向量维度，必须与迁移结构一致 |
| `RAG_MIN_SCORE` | RAG 最低综合相关度 |
| `RAG_MAX_DOCUMENT_CHARS` | 单文档处理字符预算 |
| `RAG_MAX_CHUNKS_PER_DOCUMENT` | 单文档最大分块数 |
| `CELERY_BROKER_URL` | Celery Broker |
| `CELERY_RESULT_BACKEND` | Celery 结果后端 |
| `DOCUMENT_PROCESSING_MAX_RETRIES` | 文档任务最大重试次数 |
| `DOCUMENT_PROCESSING_RETRY_BASE_SECONDS` | 指数退避基础秒数 |

## API 使用说明

直接连接本地后端时：

```bash
export API_BASE=http://127.0.0.1:8000
```

通过完整 Docker 网关时：

```bash
export API_BASE=http://localhost/api
```

### 1. 注册和登录

```bash
curl -X POST "$API_BASE/users/register" \
  -H "Content-Type: application/json" \
  -d '{"username":"demo-member","password":"demo-password-123"}'

curl -X POST "$API_BASE/users/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"demo-member","password":"demo-password-123"}'
```

从登录响应复制 `access_token`：

```bash
export TOKEN=粘贴_access_token
```

### 2. 创建并选择组织

```bash
curl -X POST "$API_BASE/organizations" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Demo Company","slug":"demo-company"}'
```

保存响应中的组织编号：

```bash
export ORGANIZATION_ID=粘贴_organization_id
```

后续所有企业接口都必须同时携带 JWT 和 `X-Organization-ID`：

```bash
curl "$API_BASE/organizations/current" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-ID: $ORGANIZATION_ID"
```

### 3. 创建知识库并上传文档

创建知识库需要 admin：

```bash
curl -X POST "$API_BASE/knowledge-bases" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-ID: $ORGANIZATION_ID" \
  -H "Content-Type: application/json" \
  -d '{"name":"IT Handbook","description":"企业 IT 制度"}'
```

保存知识库编号后上传 TXT 或 Markdown 文件：

```bash
export KNOWLEDGE_BASE_ID=粘贴_knowledge_base_id

curl -X POST "$API_BASE/knowledge-bases/$KNOWLEDGE_BASE_ID/documents" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-ID: $ORGANIZATION_ID" \
  -F "file=@sample.md;type=text/markdown"
```

上传返回 `202 Accepted` 和后台任务信息。通过 `/jobs/{job_id}` 查看任务结果；处理完成后由 approver/admin 发布文档。

### 4. 企业 RAG 问答

```bash
curl -X POST "$API_BASE/rag/knowledge-bases/$KNOWLEDGE_BASE_ID/ask" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-ID: $ORGANIZATION_ID" \
  -H "Content-Type: application/json" \
  -d '{"question":"如何申请开发软件？"}'
```

响应包含 `answer`、`sources` 和检索信息。事实性回答使用 `[S1]` 等编号关联来源分块；资料不足时返回空来源并拒绝编造。

### 5. 创建服务目录与申请

admin 创建服务项目：

```bash
curl -X POST "$API_BASE/service-catalog/items" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-ID: $ORGANIZATION_ID" \
  -H "Content-Type: application/json" \
  -d '{"name":"VPN Access","description":"申请企业 VPN 权限"}'
```

成员创建 pending 申请：

```bash
curl -X POST "$API_BASE/service-requests" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-ID: $ORGANIZATION_ID" \
  -H "Content-Type: application/json" \
  -d '{"service_catalog_item_id":1,"title":"开通 VPN","description":"远程办公需要访问内网"}'
```

### 6. 使用 Agent 安全创建申请

先让 Agent 识别意图、补充信息并返回确认内容：

```bash
curl -X POST "$API_BASE/assistant/service-tools" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-ID: $ORGANIZATION_ID" \
  -H "Content-Type: application/json" \
  -d '{"message":"我要申请 VPN，标题是开通研发 VPN，用于远程访问代码仓库"}'
```

当信息完整时，响应的 `result` 包含服务项目、标题、说明和一次性 `confirmation_token`。此阶段不会创建申请。用户明确确认后再提交令牌：

```bash
curl -X POST "$API_BASE/assistant/service-tools/confirm" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-ID: $ORGANIZATION_ID" \
  -H "Content-Type: application/json" \
  -d '{"confirmation_token":"粘贴_confirmation_token"}'
```

确认接口会重新校验组织、用户和服务状态；重复提交同一有效确认不会创建第二条申请。

## 核心接口

| 接口 | 作用 |
| --- | --- |
| `POST /users/register` | 注册 |
| `POST /users/login` | 登录并获取 JWT |
| `GET /users/me` | 当前用户 |
| `POST /organizations` | 创建组织 |
| `GET /organizations` | 当前用户的组织 |
| `POST /organizations/members` | admin 添加成员 |
| `POST /knowledge-bases` | admin 创建知识库 |
| `POST /knowledge-bases/{id}/documents` | 上传并异步处理文档 |
| `POST /knowledge-bases/{id}/documents/{document_id}/publish` | approver/admin 发布文档 |
| `POST /rag/knowledge-bases/{knowledge_base_id}/ask` | 企业知识库 RAG |
| `GET /rag/knowledge-bases/{knowledge_base_id}/logs` | 知识库查询日志 |
| `POST /service-catalog/items` | admin 创建服务项目 |
| `GET /service-catalog/items` | 查询启用服务目录 |
| `POST /service-requests` | 创建申请 |
| `GET /service-requests` | 按角色查询申请 |
| `POST /service-requests/{id}/approve` | approver/admin 批准 |
| `POST /service-requests/{id}/reject` | approver/admin 拒绝 |
| `GET /service-requests/{id}/events` | 申请审计记录 |
| `POST /assistant/tools` | Todo Tool Calling Agent |
| `POST /assistant/service-tools` | 企业服务 Agent |
| `POST /assistant/service-tools/confirm` | 确认后创建申请 |
| `GET /jobs/{job_id}` | 后台任务状态 |
| `GET /health/live` | 进程存活 |
| `GET /health/ready` | 数据库和 Broker 就绪 |

FastAPI 的 `/docs` 和 `/openapi.json` 是完整接口契约，本表只列核心业务入口。

## 权限和安全边界

| 操作 | member | approver | admin |
| --- | ---: | ---: | ---: |
| 查看组织内知识库与启用服务 | 是 | 是 | 是 |
| 上传文档 | 是 | 是 | 是 |
| 创建/修改知识库与服务目录 | 否 | 否 | 是 |
| 发布/归档文档 | 否 | 是 | 是 |
| 创建申请、查看自己的申请 | 是 | 是 | 是 |
| 查看组织内所有申请 | 否 | 是 | 是 |
| 批准/拒绝他人的 pending 申请 | 否 | 是 | 是 |

主要防线：

- JWT 只证明用户身份；`X-Organization-ID` 不能替代成员关系校验。
- 所有企业资源查询同时限制 `organization_id`，越权资源通常返回 403 或 404。
- 文件名、扩展名、MIME、内容与大小都会校验，上传文件使用随机存储名。
- RAG 只检索当前组织、当前知识库内已经发布的文档。
- Agent 不能伪造确认；确认令牌只保存哈希、绑定用户与组织、可过期且只消费一次。
- Tool 参数在执行前由后端校验，模型输出不直接成为数据库写入权限。
- 生产配置拒绝弱占位密钥、非 PostgreSQL 数据库和通配符 CORS。

这些应用层措施不能替代云防火墙、密钥托管、数据库备份、依赖漏洞扫描和平台级监控。

## 测试与质量检查

先启动测试所需的 PostgreSQL 和 Redis：

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d postgres redis
```

后端全量测试：

```bash
source .venv/bin/activate
python -m pytest -q
```

后端静态检查和迁移检查：

```bash
ruff check .
git diff --check
alembic upgrade head
alembic check
alembic current
```

前端检查：

```bash
cd frontend
npm run test
npm run lint
npm run build
```

测试覆盖正常行为、认证、角色权限、跨组织隔离、文档生命周期、后台任务重试与幂等、RAG 引用和拒答、Agent Tool Calling、确认令牌、审批状态流转，以及从注册到审批的后端 MVP 端到端流程。

## RAG 评测与参数实验

固定评测集不会调用在线模型，也不会修改生产数据：

```bash
.venv/bin/python scripts/rag_evaluation.py
```

可以显式比较检索参数：

```bash
.venv/bin/python scripts/rag_evaluation.py --top-k 3 --min-score 0.45
```

运行预设的 `top_k`、阈值和分块大小实验：

```bash
.venv/bin/python scripts/rag_parameter_experiment.py
```

当前小型固定数据集支持 `top_k=3`、`RAG_MIN_SCORE=0.45`，并暂时保留 500 字符/100 重叠的切块默认值。该结论只适用于当前数据集，增加真实企业语料后应重新评估。

## MCP 小型 Demo

`experiments/mcp_service_catalog_server.py` 是一个只读、本地 stdio 的学习实验，只暴露当前固定组织的启用服务目录：

```bash
.venv/bin/python -m pip install -r requirements-mcp-demo.txt
WORKBRAIN_MCP_ORGANIZATION_ID=1 \
  .venv/bin/python -m experiments.mcp_service_catalog_server
```

它没有公网入口、用户认证和写操作，不属于生产运行架构。采用原生 Tool Calling、Agents SDK、LangGraph 和 MCP 的取舍见 [方案对比](doc/agent-framework-comparison.md)。

## 故障排查

按以下顺序排查：

1. `docker compose ps -a`：确认 migrate/uploads-init 正常完成，其余服务 healthy。
2. `curl --fail <base-url>/api/health/live`：确认网关、前端代理和 API 可达。
3. `curl --fail <base-url>/api/health/ready`：确认 PostgreSQL 与 Redis 可达。
4. `docker compose logs --tail=100 migrate api worker`：分别检查迁移、API 和任务失败原因。
5. `alembic current` 与 `alembic heads`：确认数据库处于唯一 head。
6. 文档长时间停留 queued/running 时，检查 Worker 健康、Redis 和 `/jobs/{job_id}`。
7. 浏览器出现 401 时重新登录；403 时检查当前组织和角色；404 时检查资源是否属于当前组织。

不要在 Issue、日志截图或聊天中粘贴 JWT、确认令牌、数据库连接串或模型密钥。

## 当前边界

- 审批只包含单级批准/拒绝，不包含转派、撤回、回滚和复杂 BPM。
- 文档格式当前聚焦 TXT 与 Markdown，不包含 OCR 和复杂 Office/PDF 排版解析。
- RAG 评测集规模较小，结果不能直接代表大型企业语料表现。
- MCP 仅为只读实验，不是生产 Agent 通信层。
- Docker Compose 是单机部署方案，尚未提供 Kubernetes、多区域容灾和托管对象存储适配。

## 项目亮点

- 用统一的组织上下文和 RBAC 保护传统业务、RAG、异步任务与 Agent 工具。
- 将文档上传从同步请求拆为可重试、可观测、幂等的 Celery 任务。
- 通过发布状态、检索阈值、词法过滤、引用来源和资料不足拒答约束 RAG。
- 把高风险 Agent 写操作拆成“生成确认内容”和“确认令牌提交”两个阶段。
- 用迁移检查、全量自动化测试、生产冒烟脚本和容器健康检查形成可验证交付闭环。
