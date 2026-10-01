# ResearchOps on DeepSeek Harness (dsh) — 垂直切片验证报告

> 路线 B 交付物:`dsh-v0.2.0-rc.2` 上验证把 ResearchOps 能力挂载为 dsh 插件,
> 为"是否全面迁移"(路线 A)提供决策依据。

## 结论(先说答案)

**可行,且 seams 吻合度高于预期。** 建议推进路线 A,分三个里程碑,预估 3–5 周
(比原估 4–6 周低,因为 dsh 原生覆盖了我们大量自研基础设施)。

## 已验证的切片(全部真实运行,非设计稿)

运行环境:`deepseek-harness` @ `dsh-v0.2.0-rc.2`(锁 tag 浅克隆),Node 22。
`pnpm dsh --profile researchops "Survey contrastive learning for speaker
verification and report the top paper."` 一次跑通:

| 步骤 | 结果 |
|---|---|
| `mcp__research__search_papers` | ✅LOW 自动放行 → **真实 arXiv 数据**经我们的 Python MCP server 流回模型(1705.03670) |
| `bash`(echo acc=0.82) | ✅被移植的风险规则判为 MEDIUM → `ask` → 无审批通道时 **fail-closed 拒绝**(策略拦截验证) |
| `bash`(`autoApprove=true`) | ✅预批准 → **沙箱内真实执行**,输出 `acc=0.82` 流回模型 |
| 最终报告 | ✅引用**真实检索到的论文标题**,事件流 `--json` 全程可审计 |

## 功能映射(实测确认的挂载点)

| ResearchOps (Python) | dsh 上的落点 | 移植成本 |
|---|---|---|
| ToolGateway(白名单/校验/超时/审计) | dsh 原生(core/tools 管线 + session 事件 + guard/timeout-policy) | **删掉,零成本** |
| 风险分级 + 预算网关 | `tools/pre-execute` 瀑布监听器(`@researchops/dsh-guardrail`,本仓库已移植) | 已完成 ✅ |
| HITL 审批(ApprovalRequired/interrupt) | dsh 原生 `ctx.approval` + `approval/request` 应答器瀑布 + web UI 人工应答 | 接口适配,~2 天 |
| 3 个 Python MCP servers | `dsh-mcp-client` stdio 配置行,**零移植直接挂载** | 已验证 ✅ |
| LangGraph 编排图 | 需重写:单 agent 循环内置;多阶段图用 `core/agent`+`agent/*` 事件,或 experimental `agent-team` | **最大工作项,~2 周** |
| 记忆/混合检索(BM25+RRF) | dsh session 存储原生;检索器作为 sidecar service 或 TS 移植 | ~3 天 |
| 模型路由(llm/router.py) | `llm-pi-ai` providers 路由 + `agent-default-model` 行(纯配置) | 已验证 ✅ |
| ResearchOpsBench 评测 | Python SDK 驱动 dsh(`--profile sdk`),graders 原样保留 | ~2 天 |
| FastAPI + Next.js 仪表盘 | dsh web UI 原生(session/审批/事件流);我们的仪表盘可做成 client 插件或不移植 | 0–1 周(可选) |

## 切片中的关键发现

1. **`!!js` 表达式在 loader 上下文求值,不是 process.env** — 操作员配置的正确
   位置是 Harness home 的 profile `cordis.patch.yml`(按 row id 覆写)。
2. **dsh 的 bash 工具强制 `description` 参数**(供 UI 卡片),移植提示词时注意。
3. **MCP 2.x**:Python SDK 已升 2.x(`FastMCP`→`MCPServer`),本仓库三个 server
   已迁移;tool 名带 `mcp__<server>__` 前缀,风险策略要按前缀+白名单处理。
4. **未决**:typert 三个包在本机报 failed to import(不影响切片运行,需在
   全面迁移前排查;疑似环境相关)。
5. dsh 处于 developer preview(官方声明有 breaking changes)— 迁移时锁 tag。

## 复现步骤

```bash
# 1. dsh 工作副本(本切片在 /Users/haobowang/ZCodeProject/dsh,基于 dsh-v0.2.0-rc.2)
git clone --depth 1 --branch dsh-v0.2.0-rc.2 https://github.com/deepseek-ai/deepseek-harness.git
cd deepseek-harness && pnpm install && pnpm run build

# 2. 拷入本目录的两个包并接线(见 researchops-agent/researchops-dsh/)
#    packages/researchops/guardrail + packages/bundle/researchops
#    + apps/cli 依赖、tsconfig.host.json 引用、
#    packages/boot/app-boot/src/profile.ts 增加 researchops profile 模板

# 3. 离线演示模型 + 跑切片
cd researchops-agent && (.venv/bin/python scripts/mock_dsh_llm.py --port 8901 &)
cd ../deepseek-harness
RESEARCHOPS_MCP_PYTHON=~/ZCodeProject/researchops-agent/.venv/bin/python \
RESEARCHOPS_LLM_API_KEY=dummy \
node ./apps/cli/lib/bin.js researchops "Survey contrastive learning for speaker verification and report the top paper." --json
```

换真实模型:profile patch 里把 `RESEARCHOPS_LLM_BASE_URL` 指向
`https://api.deepseek.com/v1`、`agent-default-model.model` 改 `deepseek-chat`
即可(llm-pi-ai 支持任意 OpenAI 兼容网关,纯配置)。
