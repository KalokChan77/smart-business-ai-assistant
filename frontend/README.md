# 智慧商务 AI 助手平台 · 前端

Vue 3 + TypeScript + Vite 业务前端。浏览器只访问本前端与 FastAPI，不直接调用 DeepSeek、LangGraph、Dify 或携带任何模型 / 低代码平台密钥。

## 技术栈

- Vue 3
- TypeScript `~5.9.3`
- Vite
- Vue Router
- Pinia
- Vitest + Vue Test Utils

不引入 Axios、UI 组件库和图表库。普通请求使用浏览器 `fetch`，统计展示使用 CSS/SVG。

## 本地启动

1. 确认后端已在 `http://127.0.0.1:8000` 运行；
2. 安装依赖（使用锁文件）：

```bash
cd frontend
npm ci
```

若尚未安装过依赖，也可用 `npm install`。

3. 可选：复制 `.env.example` 为 `.env`，按需修改代理目标：

```bash
VITE_API_PROXY_TARGET=http://127.0.0.1:8000
```

4. 启动开发服务：

```bash
npm run dev
```

默认地址：`http://127.0.0.1:5173`。Vite 会把 `/api` 代理到 FastAPI。

## 角色工作台

| 角色 | 默认落地页 | 主要页面 |
|---|---|---|
| `user` | `/app/chat` | AI 对话、知识问答、我的工单、历史会话 |
| `customer_service` | `/service/tickets` | 工单处理、知识检索 |
| `admin` | `/admin/overview` | 管理概览、用户与角色、知识文档、统计 |
| `decision_maker` | `/decision/overview` | 经营总览、咨询趋势、分类、满意度、AI 质量 |

多角色默认工作台顺序：`admin -> decision_maker -> customer_service -> user`。

## 关键契约

- 访问令牌与刷新令牌保存在 `sessionStorage`，仅当前标签页会话有效；退出、刷新失败或 401 后清理；
- 受保护请求遇到 401 时只去重刷新一次，并最多重放原请求一次；
- 分类置信度与统计百分比均为后端 **0–100**，使用 `formatPercent` 直接展示；
- 客服回复建议状态只有 `draft | confirmed`；
- AI 建议必须经客服/管理员人工确认后，普通用户才能看到最终回复。

## 验证命令

```bash
npm run typecheck
npm test
npm run build
npm audit --omit=dev
```

2026-07-18 验证结果：

- 类型检查通过；
- 7 个测试文件、21 项测试通过；
- 生产构建成功；
- 生产依赖审计 0 vulnerabilities；
- 真实浏览器四角色冒烟通过（详见决策日志 `DEC-20260718-029`）。

## 目录结构

```text
frontend/src
  api/          # fetch 客户端、SSE、接口封装
  auth/         # 令牌会话读写
  components/   # 通用 UI
  layouts/      # 应用壳
  router/       # 路由与角色导航元数据
  stores/       # Pinia 认证状态
  types/        # 前后端契约类型
  ui/           # 格式化与展示工具
  views/        # 四角色业务页面
```

## 安全注意

- 不要把真实 API Key、JWT、Cookie、密码或 Dify Dataset ID 写入前端代码、测试或 README；
- 浏览器只应持有当前用户会话令牌；
- 任何上游模型或 Dify 凭据必须只存在于后端环境变量。
