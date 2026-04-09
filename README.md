# Vault2Wiki

中文 | English

`Vault2Wiki` 是一个面向开源发布的、安全可公开的知识库框架模板，面向 Obsidian 风格的 vault 工作流，用来把原始材料编译成可检索的 LLM wiki：

- 把杂乱原始材料放进 `raw/`
- 让大模型把它们编译成结构化的 `wiki/` 条目
- 在编译后的知识库上做本地检索与问答
- 将机器维护区与人类手写区分离

`Vault2Wiki` is a public-safe starter kit for Obsidian-style vault workflows that compile raw material into a retrievable LLM wiki:

- drop messy source material into `raw/`
- let an LLM compile it into structured notes in `wiki/`
- query the compiled knowledge base with local retrieval
- keep machine-maintained artifacts separate from your handwritten notes

这个项目从设计上就是为了便于公开分享而做的模板仓库，不包含私人 vault 内容、真实 API key 或用户本机路径。

This repository is intentionally designed to be open-source friendly. It contains no private vault content, no committed API keys, and no user-specific local paths.

它适合与 Obsidian 这类 Markdown knowledge vault 一起使用，但不是 Obsidian 的官方项目。

It works well with Obsidian-style Markdown knowledge vaults, but it is not an official Obsidian project.

## 功能 | What It Does

- 监听 `raw/` 中新增或变更的内容，并编译成 Markdown 条目
- 支持 `.md`、`.txt`、`.pdf`、图片占位文件
- 构建本地 SQLite FTS5 全文检索，包含 CJK bigram 增强
- 自动生成 wiki 索引、MOC 页面、健康检查和验证报告
- 为高频断链概念生成 `glossary/` 聚合页
- 支持对 `wiki/` 提问，并把回答写回 `outbox/`
- 使用 staging + gate 流程，降低低质量条目直接进入 `wiki/` 的风险

- Watches a `raw/` folder and compiles new or changed files into Markdown notes
- Supports text files, Markdown, PDFs, and image placeholders
- Builds local SQLite FTS5 search indexes, with bigram support for Chinese and other CJK text
- Generates a wiki index, MOC pages, health reports, and verification reports
- Generates `glossary/` concept pages for frequent unresolved wikilinks
- Lets you ask questions against `wiki/` and writes the answer into `outbox/`
- Uses a staging and quality gate before promoting generated notes into `wiki/`

## 设计理念 | Why This Shape

核心思路很简单：

1. 把原始材料放进机器维护区。
2. 让模型负责整理、链接、索引和格式化。
3. 把你真正的手写思考保留在另一个更稳定的区域。
4. 针对编译后的 `wiki/` 做检索和问答，而不是每次都把整个 vault 直接喂给模型。

这样做更容易复现、更容易审查，也更适合自动化。

The core idea is simple:

1. Put raw source material into a machine-maintained zone.
2. Let the model compile, normalize, link, and index that material.
3. Keep your curated or handwritten thinking separate.
4. Use retrieval over the compiled wiki instead of chatting with the whole vault directly.

That keeps the workflow reproducible, inspectable, and safer to automate.

## 模型接入策略 | LLM Integration Strategy

发布版仓库刻意保持 provider-agnostic：

- 默认使用 `llm.provider: mock`，保证示例链路离线可跑
- 真实模型由使用者在自己的 `config.yaml` 和 `.env` 中自行配置
- `llm.provider: openai` 同时覆盖原生 OpenAI 和任意 OpenAI-compatible 服务
- 当你使用 OpenAI-compatible 服务时，只需要填写对应的 `base_url`、模型名和本地环境变量名

The published repository is intentionally provider-agnostic:

- it defaults to `llm.provider: mock` so the demo flow works offline
- real model wiring is supplied by each user in their own `config.yaml` and `.env`
- `llm.provider: openai` covers both native OpenAI and any OpenAI-compatible endpoint
- for OpenAI-compatible services, users only need to set their own `base_url`, model name, and local env var names

这意味着仓库本身不会替你预设“唯一正确”的模型供应商，也不会提交任何真实凭证。

That means the repository does not bake in a single preferred vendor and does not commit any live credentials.

## 仓库结构 | Repository Layout

```text
vault2wiki/
├── src/vault2wiki/        # Python package / Python 包
├── example-vault/         # Safe demo vault / 安全示例仓库
├── docs/                  # Documentation / 文档
├── config.example.yaml    # Starter config / 配置模板
└── .env.example           # Example env file / 环境变量模板
```

目标 vault 的结构建议如下：

Expected vault layout:

```text
your-vault/
├── raw/
├── wiki/
├── outbox/
├── assets/
├── config.yaml
└── .env
```

## 快速开始 | Quickstart

1. 创建虚拟环境并安装包。

Create a virtual environment and install the package.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

2. 将配置模板和环境变量模板复制到你的 vault 中。

Copy the config and env templates into your vault.

```bash
cp config.example.yaml /path/to/your-vault/config.yaml
cp .env.example /path/to/your-vault/.env
```

3. 如果你要使用真实模型，请在 `/path/to/your-vault/.env` 中填写你自己的 provider 凭证，并按需修改 `config.yaml`。

If you want real model output, put your own provider credentials into `/path/to/your-vault/.env` and update `config.yaml` as needed.

4. 编译示例 vault。

Compile the example vault.

```bash
vault2wiki compile --vault example-vault
```

仓库内置的 `example-vault` 默认使用 `llm.provider: mock`，因此整条链路可以在不配置任何 API key 的情况下跑通。需要真实模型时，再切换成 `openai` 或 `anthropic`，并在你自己的 vault 本地填写 provider 配置。

The bundled `example-vault` uses `llm.provider: mock`, so the end-to-end workflow works without API keys. Switch it to `openai` or `anthropic` when you want real model output, and keep the provider-specific config in your own local vault.

5. 发起一次问答。

Ask a question.

```bash
vault2wiki query "What themes keep showing up in the notes?" --vault example-vault
```

## 命令 | Commands

```bash
vault2wiki compile --vault /path/to/vault
vault2wiki watch --vault /path/to/vault
vault2wiki query "your question" --vault /path/to/vault
vault2wiki reindex --vault /path/to/vault
vault2wiki health --vault /path/to/vault
vault2wiki maintain --vault /path/to/vault
```

## 支持的输入类型 | Supported Inputs

- `.md`
- `.txt`
- `.pdf`
- `.png`
- `.jpg`
- `.jpeg`
- `.webp`

默认情况下，图片会被转成占位条目。PDF 使用 PyMuPDF 提取文本；如果 PDF 主要是扫描页且提取效果太差，`Vault2Wiki` 会生成 stub note，而不是强行编造总结。

Images are currently turned into placeholder notes by default. PDFs are parsed with PyMuPDF. If a PDF is mostly scanned pages and text extraction fails, `Vault2Wiki` creates a stub note instead of hallucinating a summary.

## 隐私模型 | Privacy Model

这个仓库是模板和工具链，不是真实个人知识库。

This repository is intentionally a template and toolchain, not a real personal vault.

- 不要提交真实 `.env`
- 不要提交 `.vault2wiki/` 下的运行态文件
- 不要提交你的私有 `raw/`、`wiki/`、`outbox/`
- 最安全的方式是从干净的新仓库开始发布，而不是在长期使用的私有 vault 上原地脱敏

- Do not commit your real `.env`
- Do not commit generated runtime state in `.vault2wiki/`
- Do not commit your private `raw/`, `wiki/`, or `outbox/`
- Start your public repo from a clean template rather than trying to sanitize a long-lived private vault in place

详细说明见 [docs/PRIVACY.md](docs/PRIVACY.md)。

See [docs/PRIVACY.md](docs/PRIVACY.md) for the detailed guidance.

如果你想看这个项目与 Karpathy 提出的 “LLM Knowledge Bases” 工作流理念如何对应，可以继续看 [docs/PHILOSOPHY.md](docs/PHILOSOPHY.md)。

If you want to see how this project maps onto the “LLM Knowledge Bases” workflow idea discussed by Karpathy, see [docs/PHILOSOPHY.md](docs/PHILOSOPHY.md).

## 发布前检查 | Release Checklist

建议在准备发布前至少确认下面几件事：

Before publishing, at minimum verify these:

- 仓库内没有真实 `.env`
- 仓库内没有 `.vault2wiki/`、日志、数据库或 query 输出
- `rg` 搜不到你的用户名、本机路径、私人项目名或密钥片段
- `compile`、`maintain`、`reindex`、`query`、`watch` 都能跑通
- 示例 vault 可以在 `mock` 模式下完整演示
- 文档明确要求使用者自行配置 provider、模型名、`base_url` 与本地 `.env`

- No real `.env` files are present
- No `.vault2wiki/`, logs, databases, or personal query outputs are tracked
- `rg` does not find your username, local paths, private project names, or key fragments
- `compile`, `maintain`, `reindex`, `query`, and `watch` all run successfully
- The example vault demonstrates the full flow in `mock` mode
- The docs clearly tell users to configure their own provider, model, `base_url`, and local `.env`

## 路线图 | Roadmap

- Obsidian 插件配方 / Optional Obsidian plugin recipes
- launchd/systemd 示例 / Optional launchd or systemd helpers
- OCR 后端扩展 / Optional OCR backends
- 更丰富的标签插件机制 / Optional richer tag taxonomy plugins

## 许可证 | License

MIT
