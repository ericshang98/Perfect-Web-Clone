# Nexting

<div align="center">

**开源 Agent 协作系统**

*网页克隆领域的 Claude Code。一个配备 40+ 专业工具的垂直 AI Agent。*

[English](../../README.md) | 中文 | [日本語](../ja/README_JA.md) | [한국어](../ko/README_KO.md) | [Español](../es/README_ES.md) | [Português](../pt/README_PT.md) | [Deutsch](../de/README_DE.md) | [Français](../fr/README_FR.md) | [Tiếng Việt](../vi/README_VI.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Next.js](https://img.shields.io/badge/Next.js-15.x-black)](https://nextjs.org/)
[![React](https://img.shields.io/badge/React-19.x-61dafb)](https://react.dev/)
[![Python](https://img.shields.io/badge/Python-3.11+-3776ab)](https://python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688)](https://fastapi.tiangolo.com/)
[![Playwright](https://img.shields.io/badge/Playwright-1.49+-2EAD33)](https://playwright.dev/)
[![Claude](https://img.shields.io/badge/Claude-Anthropic-cc785c)](https://anthropic.com/)

</div>

**真正的 AI Agent** — 不只是 LLM 的包装。多代理协作，配备真实工具、自我修正循环，以及完整的沙箱环境，从零构建生产级代码。

其他工具从截图猜测代码。我们提取**真实代码** — DOM、样式、组件、交互。**像素级完美克隆**，这是基于截图的工具根本做不到的。

https://github.com/user-attachments/assets/248af639-20d9-45a8-ad0a-660a04a17b68

## 开源多代理架构

**整个多代理系统完全开源。** 学习它、使用它、在此基础上构建。

### 为什么选择 Cowork？

让一个 AI 处理所有事情，就像让一个同事独自承担所有工作一样 — 他们会不堪重负。传统的单模型方法会遇到瓶颈：
- 大型页面上的上下文窗口溢出
- 同时处理太多任务时产生幻觉
- 缓慢的串行处理

我们的解决方案：**专业代理协同工作**，就像同事们各自专注于自己最擅长的领域。少一些来回沟通，多一些高效完成。

### 为什么不直接用 Cursor / Claude Code / Copilot？

<p align="center">
  <img src="https://img.shields.io/badge/Cursor-000000?style=for-the-badge&logo=cursor&logoColor=white" alt="Cursor" />
  <img src="https://img.shields.io/badge/Claude_Code-cc785c?style=for-the-badge&logo=anthropic&logoColor=white" alt="Claude Code" />
  <img src="https://img.shields.io/badge/GitHub_Copilot-000000?style=for-the-badge&logo=githubcopilot&logoColor=white" alt="GitHub Copilot" />
  <span style="margin: 0 10px;">vs</span>
  <img src="https://img.shields.io/badge/Nexting-8B5CF6?style=for-the-badge" alt="Nexting" />
</p>

我们试过了。即使给它们 **完整的提取 JSON** — 完整的 DOM 树、所有 CSS 规则、每个资源 URL — 单模型工具依然力不从心：

| 挑战 | <img src="https://img.shields.io/badge/-Cursor-000?style=flat-square&logo=cursor" /> <img src="https://img.shields.io/badge/-Claude_Code-cc785c?style=flat-square&logo=anthropic" /> <img src="https://img.shields.io/badge/-Copilot-000?style=flat-square&logo=githubcopilot" /> | <img src="https://img.shields.io/badge/-Nexting-8B5CF6?style=flat-square" /> 多代理 |
|------|-------------------------------|----------------|
| **50,000+ 行 DOM 树** | ❌ 上下文溢出，截断关键部分 | ✅ 任务分发给 Worker 代理 |
| **3,000+ 条 CSS 规则** | ❌ 丢失优先级，遗漏变量 | ✅ Worker 并行处理 |
| **组件识别** | ❌ 猜测边界，生成巨石代码 | ✅ 结构化工作流保证一致性 |
| **响应式断点** | ❌ 通常硬编码单一视口 | ✅ 提取所有媒体查询 |
| **悬停/动画状态** | ❌ 看不到，无法复现 | ✅ 浏览器自动化捕获全部 |
| **输出质量** | ❌ "差不多"的近似 | ✅ 像素级精确，生产就绪 |

> **核心问题**：200KB 的提取 JSON 超出实际上下文限制。即使能装下，单个代理也无法在上下文被过多信息污染时保持连贯。解决方案不是更聪明的代理 — 而是**任务分发**加可靠的工作流。

**诚实的局限**：复杂动效目前仍难以完美提取 — 但这是爬虫层面的问题，不是多代理架构的问题。多代理架构本身的能力**远不止网页克隆**。想象一下：自动化重构、代码库迁移、文档生成，或任何单个代理无法处理的大型任务。

### Agent + Tools + Sandbox 模式

```
┌─────────────────────────────────────────────────────────┐
│                    多代理系统                            │
├─────────────────────────────────────────────────────────┤
│                  ┌───────────────┐                      │
│                  │  主代理       │                      │
│                  │  (协调者)     │                      │
│                  └───────┬───────┘                      │
│                          │ 分发任务                     │
│         ┌────────────────┼────────────────┐             │
│         ▼                ▼                ▼             │
│  ┌───────────┐    ┌───────────┐    ┌───────────┐       │
│  │  Worker   │    │  Worker   │    │  Worker   │  ...  │
│  │  代理 1   │    │  代理 2   │    │  代理 N   │       │
│  └─────┬─────┘    └─────┬─────┘    └─────┬─────┘       │
│        └────────────────┼────────────────┘              │
│                         ▼                               │
│  ┌─────────────────────────────────────────────────┐   │
│  │                    工具层                        │   │
│  │  • 文件操作  • 代码分析                         │   │
│  │  • 浏览器控制  • API 调用                       │   │
│  └─────────────────────────────────────────────────┘   │
│                         │                               │
│                         ▼                               │
│  ┌─────────────────────────────────────────────────┐   │
│  │              沙箱 (BoxLite)                      │   │
│  │  隔离的执行环境，用于安全的                      │   │
│  │  代码生成、测试和预览                           │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

这种模式 — **Agent + Tools + Sandbox** — 可复用于任何 AI Agent 产品：

| 组件 | 用途 | 在 Nexting 中 |
|------|------|---------------|
| **主代理** | 协调工作流，分发任务 | 分析页面，生成 Worker，合并结果 |
| **Worker 代理** | 执行子任务，具有限定权限 | 并行处理各区块，隔离上下文 |
| **Tools** | 代理可以调用的能力 | 文件 I/O、浏览器自动化、API 调用 |
| **Sandbox** | 安全的执行环境 | [BoxLite](https://github.com/boxlite-ai/boxlite) - 嵌入式微型虚拟机运行时 |

> **BoxLite**: 为 AI Agent 设计的硬件级隔离微型虚拟机。无需 root 权限，运行 OCI 容器，真正的内核隔离。→ [github.com/boxlite-ai/boxlite](https://github.com/boxlite-ai/boxlite)

### 联系我

正在使用这个架构构建项目？有问题？欢迎联系：

[![Twitter](https://img.shields.io/badge/Twitter-@ericshang98-1DA1F2?style=flat&logo=twitter)](https://twitter.com/ericshang98)
[![GitHub](https://img.shields.io/badge/GitHub-ericshang98-181717?style=flat&logo=github)](https://github.com/ericshang98)

---

## 目录

- [开源多代理架构](#开源多代理架构)
- [Agent 工具包](#agent-工具包)
- [为什么选择 Nexting？](#为什么选择-nexting)
- [功能特性](#功能特性)
- [演示](#演示)
- [快速开始](#快速开始)
- [架构](#架构)
- [API 参考](#api-参考)
- [技术栈](#技术栈)
- [贡献](#贡献)
- [许可证](#许可证)

## Agent 工具包

基于 **[Claude Agent SDK](https://docs.anthropic.com/en/docs/agents-and-tools/claude-agent-sdk)** 构建 — 与 Claude Code 相同的底层架构。这不是一个带 API 调用的聊天机器人；它是一个**真正的 Agent**，能够在隔离沙箱中思考、规划、执行和自我修正。

### 10 大类 40+ 工具

| 类别 | 工具 | 用途 |
|------|------|------|
| **文件操作** | `read_file`, `write_file`, `edit_file`, `delete_file`, `rename_file`, `create_directory` | 项目文件的 CRUD 操作 |
| **搜索发现** | `glob`, `grep`, `ls`, `search_in_file`, `search_in_project` | 查找文件和内容（ripgrep 驱动）|
| **任务管理** | `todo_read`, `todo_write`, `task`, `get_subagent_status` | 追踪进度，启动子代理 |
| **系统执行** | `bash`, `run_command`, `shell` | 在沙箱中运行任意命令 |
| **网络** | `web_fetch`, `web_search` | 获取 URL，搜索网络 |
| **终端** | `create_terminal`, `send_terminal_input`, `get_terminal_output`, `install_dependencies`, `start_dev_server` | 管理多个终端会话 |
| **预览** | `take_screenshot`, `get_console_messages`, `get_preview_dom`, `get_preview_status` | 检查实时预览状态 |
| **诊断** | `verify_changes`, `diagnose_preview_state`, `analyze_build_error`, `get_comprehensive_error_snapshot` | 调试和验证 |
| **自我修复** | `start_healing_loop`, `verify_healing_progress`, `stop_healing_loop` | 自动修复构建错误 |
| **源数据查询** | `list_saved_sources`, `get_source_overview`, `query_source_json` | 查询提取的网站数据 |

### 设计哲学

```
┌────────────────────────────────────────────────────────────┐
│                      Claude Agent SDK                       │
│  ┌──────────────────────────────────────────────────────┐  │
│  │                    Nexting Agent                      │  │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐ │  │
│  │  │ 规划器  │  │ 编码器  │  │ 调试器  │  │ 验证器  │ │  │
│  │  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘ │  │
│  │       └──────────┬─┴───────────┬┴────────────┘      │  │
│  │                  ▼             ▼                     │  │
│  │         ┌──────────────────────────────┐            │  │
│  │         │       40+ 专业工具            │            │  │
│  │         └──────────────┬───────────────┘            │  │
│  └────────────────────────┼────────────────────────────┘  │
│                           ▼                                │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              BoxLite 沙箱 (微型虚拟机)                │  │
│  │         隔离的代码执行和预览环境                      │  │
│  └──────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────┘
```

**与 ChatGPT/Claude 聊天有什么不同？**
- **持久状态**：Agent 在整个会话中记住上下文
- **工具链**：可以连续执行 10+ 个工具，无需人工干预
- **自我修正**：检测错误，诊断根因，自动修复
- **实时预览**：看到实际渲染输出，而不仅仅是代码

## 为什么选择 Nexting？

### 截图工具 vs 代码提取

大多数 AI 克隆工具把网页当成图片来**猜测**代码。我们读取**真实源码** — 这就是为什么我们的输出是生产就绪的，而不是粗略的近似。

| 基于截图的工具 | Nexting |
|---------------|---------|
| AI 解读像素 → 猜测布局 | 提取真实 DOM → 分析 CSS |
| 硬编码像素值 | 响应式弹性单位 |
| 无交互效果 | 保留悬停效果和动画 |
| 全是 div 标签 | 保留语义化 HTML |
| 不可维护的输出 | 干净、模块化的组件 |

## 功能特性

### 网页提取器
- **全页面捕获** - 使用 Playwright 提取完整的 DOM 结构、CSS 样式和资源
- **主题检测** - 自动检测并捕获亮色和暗色主题
- **组件分析** - AI 驱动的组件边界检测
- **技术栈分析** - 识别页面使用的框架和库
- **资源提取** - 下载图片、字体和其他资源

### 克隆代理
- **多代理架构** - 专业代理并行工作，实现更快、更准确的结果
- **AI 代码生成** - Claude 根据提取数据生成生产就绪的代码
- **实时预览** - 使用 BoxLite 沙箱实时预览代码
- **框架支持** - 导出到 React、Next.js、Vue 或纯 HTML

### 多代理系统

传统的单模型方法在复杂页面上会失败 — 不是因为模型不够聪明，而是因为任务量太大。我们的多代理系统通过**任务分发**来解决这个问题：

| 代理 | 职责 |
|------|------|
| **主代理** | 分析页面，将工作分解为子任务，生成 Worker 代理，并将它们的输出合并为连贯的代码。 |
| **Worker 代理** | 在隔离的上下文中并行执行子任务。每个 Worker 具有限定权限和专注的职责。 |

**为什么有效**：不让单个代理淹没在 200KB 的上下文中，Worker 各自处理可管理的区块。结构化工作流防止上下文污染，确保最终输出的一致性。

## 演示

<div align="center">

https://github.com/user-attachments/assets/248af639-20d9-45a8-ad0a-660a04a17b68

</div>

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 18+
- Anthropic API Key

### 快速启动

1. **克隆仓库**

```bash
git clone https://github.com/ericshang98/perfect-web-clone.git
cd perfect-web-clone
```

2. **后端设置**

```bash
cd backend

# 复制环境变量文件并添加你的 API Key
cp ../.env.example .env
# 编辑 .env 并添加你的 ANTHROPIC_API_KEY

# 启动服务器（自动安装依赖）
sh start.sh
```

3. **前端设置**

```bash
cd frontend

# 安装依赖
npm install

# 配置环境变量（可选）
cp ../.env.example .env.local

# 启动开发服务器
npm run dev
```

4. **打开应用**

在浏览器中访问 [http://localhost:3000](http://localhost:3000)。

### 使用方法

#### 1. 提取网站

1. 进入 **Extractor** 页面
2. 输入要提取的 URL
3. 配置提取选项（视口、主题等）
4. 点击 **Analyze** 开始提取
5. 完成后，点击 **Save to Cache** 保存结果

#### 2. AI 克隆

1. 进入 **Agent** 页面
2. 点击 **Sources** 按钮打开源面板
3. 选择一个缓存的提取结果
4. 与 AI 对话生成代码
5. 在代理编写代码时查看实时预览

## 架构

```
nexting/
├── backend/                 # Python FastAPI 后端
│   ├── cache/              # 提取结果的内存缓存
│   ├── extractor/          # 基于 Playwright 的网页提取器
│   ├── agent/              # 集成 Claude 的多代理系统
│   ├── boxlite/            # 后端沙箱环境
│   ├── image_proxy/        # 图片 CORS 代理
│   └── image_downloader/   # 批量图片下载服务
│
├── frontend/               # Next.js 前端
│   ├── src/app/           # App Router 页面
│   ├── src/components/    # React 组件
│   │   ├── ui/           # Shadcn/UI 组件
│   │   ├── landing/      # 落地页组件
│   │   ├── extractor/    # 提取器组件
│   │   └── agent/        # 代理聊天和预览
│   ├── src/hooks/        # 自定义 React Hooks
│   └── src/lib/          # 工具和 API 客户端
│
├── docs/                  # 文档和资源
│   ├── assets/           # 演示视频和图片
│   ├── cn/               # 中文文档
│   └── ja/               # 日文文档
│
└── .env.example          # 环境变量模板
```

## API 参考

### 提取器 API

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/extractor/extract` | POST | 开始网页提取 |
| `/api/extractor/status/{id}` | GET | 查询提取状态 |

### 缓存 API

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/cache/store` | POST | 存储提取结果到缓存 |
| `/api/cache/list` | GET | 列出缓存的提取结果 |
| `/api/cache/{id}` | GET | 获取缓存的提取结果 |
| `/api/cache/{id}` | DELETE | 删除缓存的提取结果 |

### 代理 API

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/agent/ws` | WebSocket | AI 代理通信 |

### BoxLite API

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/boxlite/*` | 多种 | 后端沙箱环境 |
| `/api/boxlite-agent/*` | 多种 | 代理沙箱操作 |

## 技术栈

| 类别 | 技术 |
|------|------|
| **前端** | Next.js 15, React 19, TailwindCSS 4, Shadcn/UI, Three.js |
| **后端** | FastAPI, Python 3.11+, Playwright, WebSocket |
| **AI** | Claude (Anthropic API), 多代理架构 |
| **沙箱** | BoxLite |
| **样式** | TailwindCSS, CSS 变量, 暗色模式支持 |

## 贡献

欢迎贡献！请随时提交 Pull Request。

1. Fork 仓库
2. 创建功能分支 (`git checkout -b feature/amazing-feature`)
3. 提交更改 (`git commit -m 'Add amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 打开 Pull Request

## 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](../../LICENSE) 文件。

---

<div align="center">

**[Nexting](https://github.com/ericshang98/perfect-web-clone)** - 提取真实代码，而非猜测。

由 [Eric Shang](https://github.com/ericshang98) 用 ❤️ 制作

</div>
