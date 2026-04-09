# 设计理念对齐 | Philosophy Alignment

这个项目明确对齐的是一类 “LLM Knowledge Bases” 工作流：

This project is explicitly aligned with an “LLM Knowledge Bases” style workflow:

1. 原始资料统一进入 `raw/`
2. 使用 LLM 增量编译成 `wiki/` 下的一组 Markdown 条目
3. 条目包含摘要、概念、相关链接与可追溯来源
4. 通过 wikilinks、MOC 和概念页逐步形成互联结构
5. 在本地 wiki 上做检索和问答，而不是每次直接对整堆原始资料提问

1. Source material lands in `raw/`
2. An LLM incrementally compiles that material into Markdown files under `wiki/`
3. Notes carry summaries, concepts, related links, and traceable sources
4. Wikilinks, MOC pages, and concept pages gradually form a linked structure
5. Retrieval and question answering happen over the local wiki instead of the raw pile every time

## 当前实现如何对应 | How The Current Implementation Maps

- `raw/`：作为统一摄入区
- `wiki/`：作为编译后的 Markdown 知识库
- `compile`：负责增量编译
- `query`：对 `wiki/` 进行本地检索后问答
- `moc`：提供主题入口页
- `glossary`：为高频断链概念生成聚合页
- `health`：检查断链、缺字段、孤岛条目等结构问题

- `raw/`: the unified ingest area
- `wiki/`: the compiled Markdown knowledge base
- `compile`: incremental compilation
- `query`: local retrieval plus QA over `wiki/`
- `moc`: topic entry pages
- `glossary`: aggregate pages for frequent unresolved concepts
- `health`: structural checks for broken links, missing metadata, and orphan notes

## 有意保留的边界 | Deliberate Boundaries

这个项目是框架，不是你的真实 vault，因此不会默认包含：

- 私人笔记正文
- 私有标签体系
- 本机自动化脚本
- 真实 API key

This repository is a framework, not your real vault, so it deliberately does not ship with:

- private note content
- private taxonomies
- user-specific machine automation
- real API keys

## Provider 边界 | Provider Boundary

这里提到的 Karpathy 理念，强调的是工作流形态，而不是绑定某一家模型服务商。

The Karpathy reference here is about the workflow idea, not a commitment to one model vendor.

- 仓库默认用 `mock` 保持可演示性
- 真实 provider 由使用者在本地配置
- `openai` 配置块可以接原生 OpenAI，也可以接 OpenAI-compatible 端点
- 如果你使用公司私有网关、组织专属代理或其他内部模型入口，不应把这些真实配置提交到公开仓库

- The repository defaults to `mock` to stay demo-friendly
- Real providers are configured locally by each user
- The `openai` block can target native OpenAI or any OpenAI-compatible endpoint
- If you use a company gateway, tenant-specific proxy, or internal model endpoint, do not commit that live configuration into the public repository
