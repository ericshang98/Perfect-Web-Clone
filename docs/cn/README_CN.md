# Nexting

<div align="center">

**AI 驱动的网页克隆工具 - 提取、分析、克隆**

[English](../../README.md) | 中文 | [日本語](../ja/README_JA.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Next.js](https://img.shields.io/badge/Next.js-15.x-black)](https://nextjs.org/)
[![React](https://img.shields.io/badge/React-19.x-61dafb)](https://react.dev/)
[![Python](https://img.shields.io/badge/Python-3.11+-3776ab)](https://python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688)](https://fastapi.tiangolo.com/)
[![Playwright](https://img.shields.io/badge/Playwright-1.49+-2EAD33)](https://playwright.dev/)
[![Claude](https://img.shields.io/badge/Claude-Anthropic-cc785c)](https://anthropic.com/)

</div>

其他工具从截图猜测代码。我们提取**真实代码** — DOM、样式、组件、交互。几秒钟内获得像素级精确、可维护的输出。

https://github.com/user-attachments/assets/248af639-20d9-45a8-ad0a-660a04a17b68

## 目录

- [为什么选择 Nexting？](#为什么选择-nexting)
- [功能特性](#功能特性)
- [演示](#演示)
- [快速开始](#快速开始)
- [架构](#架构)
- [API 参考](#api-参考)
- [技术栈](#技术栈)
- [贡献](#贡献)
- [许可证](#许可证)

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
- **实时预览** - 使用 WebContainer (StackBlitz) 实时预览代码
- **框架支持** - 导出到 React、Next.js、Vue 或纯 HTML

### 多代理系统

传统的单模型方法在复杂页面上会失败。我们的多代理系统分解问题：

| 代理 | 职责 |
|------|------|
| **DOM 结构代理** | 处理大规模、深度嵌套的 DOM 树。提取语义结构和组件边界。 |
| **样式分析代理** | 处理数千条 CSS 规则。捕获计算样式、CSS 变量和断点。 |
| **组件检测代理** | 识别代码库中的可重用模式，实现模块化输出。 |
| **代码生成代理** | 将所有输出合成为生产就绪的、特定框架的代码。 |

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
| **预览** | WebContainer (StackBlitz) |
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
