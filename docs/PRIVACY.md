# 隐私说明 | Privacy Guidance

这个项目应该作为“公开工具链”发布，而不是“你的私有知识库副本”。

This project is meant to be the public toolchain, not the public version of your private vault.

## 可以提交的内容 | Safe To Commit

- `src/` 下的源代码
- 包内提示词模板
- `config.example.yaml`
- `.env.example`
- 为本仓库重新编写的示例内容
- 文档

- Source code under `src/`
- Prompt templates bundled with the package
- `config.example.yaml`
- `.env.example`
- Example demo content created specifically for this repository
- Documentation

## 不应提交的内容 | Do Not Commit

- 真实 `.env`
- 含真实 tenant、组织或内部网关信息的模型端点配置
- `.vault2wiki/` 下的运行态状态文件
- 私有 raw 笔记
- 私有编译后 wiki 条目
- 私人问答输出
- 检索数据库和日志

- Real `.env` files
- Provider configs that expose a real tenant, org, or internal endpoint
- Runtime state under `.vault2wiki/`
- Private raw notes
- Private compiled wiki pages
- Personal query outputs
- Machine indexes and logs

## 最佳实践 | Best Practice

最安全的方式是：

1. 新建一个全新的公开仓库。
2. 只迁移通用代码和通用文档。
3. 示例内容全部重写，不要抽取你的真实笔记片段。
4. 在第一次真实运行之前就先写好 `.gitignore`。
5. 公开版默认保持 `mock`，真实 provider 只在本地 vault 中配置。

The safest pattern is:

1. Create a fresh public repository.
2. Port only generic code and generic documentation.
3. Write brand-new sample notes for demos instead of copying private ones.
4. Add ignore rules before the first real run.
5. Keep the public template on `mock` by default and configure real providers only in a local vault.

## 为什么不能在私有仓库上原地脱敏 | Why Sanitizing In Place Is Risky

即使删掉正文文件，私密信息仍可能通过这些地方泄露：

- 运行态索引数据库
- 日志
- 绝对路径
- shell 命令配置
- 示例提示词或标签体系
- Git 历史

Even after deleting the obvious content files, private information can still leak through:

- generated indexes
- logs
- hardcoded absolute paths
- shell command configs
- sample prompts or tag taxonomies that mirror your private system
- git history

## 发布前最低要求 | Minimum Pre-Publish Standard

在决定上传到 GitHub 之前，建议至少完成下面这些检查：

Before you decide to upload to GitHub, you should at least verify:

- 仓库内没有真实密钥
- 仓库内没有真实 provider 端点、组织专属网关地址或租户信息
- 仓库内没有本机用户名、绝对路径或私人项目代号
- 所有被保留的示例内容都是可公开的
- 所有运行态文件都被忽略且已清理
- 主链路命令在示例 vault 中可跑通

- No real keys remain in the repository
- No live provider endpoints, org-specific gateways, or tenant identifiers remain
- No local username, absolute path, or private project codename remains
- All retained sample content is intentionally public-safe
- All runtime files are ignored and cleaned
- The main commands work end to end in the example vault
