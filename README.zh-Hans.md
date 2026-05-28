<p align="center">
  <img src="frontend/public/logo/chatrpg-logo-warm-transparent.png" alt="AiChatTrpg 章鱼 Logo" width="160" />
</p>

<h1 align="center">AiChatTrpg</h1>

<p align="center">
  <a href="README.md">English</a> | <a href="README.zh-Hans.md">简体中文</a>
</p>

AiChatTrpg 是一款开源的 AI-GM 跑团引擎，也是一套本地优先的可玩应用。
把规则书 PDF 和冒险模组交给它，再选一个模型供应商；引擎负责读规则、
掷骰、记忆和 NPC 连续性，GM 模型负责叙事。

> **状态**：Pre-alpha，正在快速开发。默认形态是本地自托管；公开测试
> 平台只是邀请制实验环境，不是正式 SaaS。

## 这是什么

AiChatTrpg 想解决一个很具体的问题：普通聊天机器人能讲故事，但跑团时
容易忘角色、漂规则、甚至自己编骰子结果。AiChatTrpg 把规则和骰子交给
代码，把叙事交给 LLM。

目前它包含：

- **三阶段回合管线**：预处理 → 生成 → 后处理，支持流式输出。
- **文本标记驱动状态变化**：不依赖 function calling；GM 在文本里发出
  `[ROLL]`、`[SET_SCENE]`、`[UPDATE_MEMORY]` 这类标记，回合结束后由代码解析。
- **双层记忆**：一份结构化状态（场景、NPC、剧情线等）+ 一份压缩后的叙事概要。
- **Dice IR**：骰子和检定走确定性中间表示，结果更公平，也方便回溯。
- **场景感知上下文**：当前场景决定哪些规则、模组片段和记忆会进 GM 提示词。
- **多模型供应商**：OpenAI-compatible（OpenAI / DeepSeek / Kimi / GLM /
  Doubao / Qwen / Grok）、Gemini、Claude。

## 它不是什么

- **不是模组商城**：V1 只有“从社区 URL 下载”的入口。所谓社区可以只是
  一组放在 GitHub Releases 或别处的 JSON 文件。
- **还不是公开 SaaS**：V1 仍然是本地优先。线上部署只是测试模式，不是托管产品。
- **默认不开放注册**：本地安装用 `auth.json` 启动管理员；线上测试可以开启
  邀请码注册。

## 公开测试平台

邀请制测试平台在：

[`test.aichattrpg.com`](https://test.aichattrpg.com/)

它用于早期验证注册、登录、私人房间和当前单人游戏流程。这个环境还很早期，
不要上传敏感个人信息、私人战役档案、API key 或受版权保护的规则书。

## 技术栈

**后端**：Python 3.11+、FastAPI、SQLAlchemy、PostgreSQL。当前不要求 pgvector。

**前端**：Vite 8、React 19、TypeScript 5.7+、Tailwind CSS 4、TanStack Query、
`@microsoft/fetch-event-source`、`marked` + KaTeX、`react-virtuoso`、
`@3d-dice/dice-box`、`@hey-api/openapi-ts` + `@hey-api/client-fetch`。

**接口同步**：后端 FastAPI OpenAPI spec 会编译成前端使用的 TypeScript client。

## 快速启动

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL=postgresql+asyncpg://chatrpg:chatrpg@127.0.0.1:54318/chatrpg
cp ../auth.example.json ../auth.json
python run.py                       # http://localhost:8013

# Frontend
cd frontend
npm install
npm run dev                          # http://localhost:3013
```

## 登录与注册

本地安装使用 `auth.json` 作为管理员启动源。每次后端启动时，这些账号都会同步
到数据库里，方便操作者通过编辑 `auth.json` 并重启来恢复管理员访问。

线上测试环境可以通过环境变量开启邀请制玩家注册：

```bash
REGISTRATION_ENABLED=true
REGISTRATION_INVITE_REQUIRED=true
REGISTRATION_INVITE_CODES=alpha-test-code
REGISTRATION_INVITE_MAX_USES=1
JWT_SECRET=<long-random-secret>
```

数据库中新创建的用户使用 PBKDF2-SHA256 密码哈希。明文 `auth.json` 路径只保留
给本地启动管理员使用。

## 给贡献者

项目还在 Pre-alpha，最好提交小而清楚的 PR。开始前请先读：

- `CONTRIBUTING.md`：如何提 issue、PR、本地验证。
- `SECURITY.md`：如何报告安全问题，以及哪些内容不要发到公开 issue。
- `CLAUDE.md` 和 `AGENTS.md`：项目愿景、架构约束、协作规则。

AiChatTrpg 内部使用 Codex 组长模式 / Team Lead Mode 来处理较复杂的工作流。
这部分是项目协作方式，不影响普通使用者安装和运行。

## 安全提醒

不要把这些内容贴到公开 issue、PR、日志或聊天里：

- 模型供应商 API key；
- 邀请码、JWT、数据库密码；
- 生产服务器细节；
- 受版权保护的 TRPG 规则书；
- 私人战役内容或用户上传文件。

## 许可证

AiChatTrpg 使用 Apache License 2.0。你可以免费使用、修改和分发，包括商业用途，
前提是遵守 Apache-2.0 的再分发条款。Apache-2.0 还包含明确的专利授权；如果某方
发起专利诉讼声称本作品侵权，其专利授权会按许可证条款终止。

### 商业使用时注意依赖

`requirements.txt` 里的默认 PDF 文本抽取依赖 PyMuPDF 是 **AGPL-3.0**，
不适合闭源商业分发。如果你想在闭源商业产品里使用 AiChatTrpg，请替换这部分适配器。

可选方案：

- **[MinerU](https://github.com/opendatalab/MinerU)** — Apache 2.0 + 附加条款。
  商业免费，除非 MAU > 100M 或月收入 > 2000 万美元；如果作为在线服务提供，需要
  明示归因 MinerU。
- **[pypdf](https://github.com/py-pdf/pypdf)** — BSD-3-Clause。
- **[pdfplumber](https://github.com/jsvine/pdfplumber)** — MIT。

默认 ruleset / module parser 已内置在后端里。商业部署可以通过替换
`RulesetParser` / `ModuleParser` 适配器来换掉 PDF 文本抽取后端。
