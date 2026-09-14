# GitHub AIGC 生产工作流对标研究

研究目的：为 Prompt 优先、故事本按风险触发、RunningHub/小云雀/LibTV 三渠道的短剧生产线筛选可复用组件。

说明：Star/fork/许可证/更新时间是 2026-09-14 的 GitHub API 快照；它们是筛选信号，不代表代码质量或商业可用性。引入前仍需锁定 commit、读取 LICENSE/README/依赖和实际行为。

## 结论先行

没有一个仓库可以原样作为本生产线。最值得借鉴的组合是：

1. `ArcReel`：研究中文“小说/剧本→资产→分镜→视频→剪映草稿”的产品架构，但 AGPL-3.0，不能直接复制到闭源核心。
2. `OpenReels`：借鉴 JSON brief、分阶段产物、成本/QA/可恢复运行的产品形态；它面向短视频，不是短剧资产权威链。
3. `LangGraph`：借鉴持久化状态、暂停/恢复和人工审批，不接管创作规则。
4. `Pydantic AI`：借鉴强制结构化输出，让脚本拆解、Prompt 和资产决策返回可校验对象。
5. `OpenTimelineIO`：借鉴生产单元到剪辑时间线的交换格式。
6. `Remotion`：只在以后做可编辑预览/渲染层时研究；不要让它成为视频生成渠道。
7. `ttv-pipeline`：借鉴长视频拆段、关键帧/尾帧链和远程 API 抽象；要移除本地模型假设并改为三渠道合同。

## 候选仓库矩阵

| 仓库 | 2026-09-14 快照 | 适合借鉴 | 不应直接搬入 |
|---|---:|---|---|
| [ArcReel/ArcReel](https://github.com/ArcReel/ArcReel) | 4,451 stars / 896 forks / AGPL-3.0 / active | 中文短剧产品形态、资产/分镜/费用/多供应商的模块边界 | AGPL 代码、默认全流程和其供应商模型假设 |
| [tsensei/OpenReels](https://github.com/tsensei/OpenReels) | 184 / 40 / MIT / active | JSON brief→plan→生成→QA 的 CLI/报告结构 | 自动重试、发布导向、其 provider 列表；需改成你的三渠道和授权门禁 |
| [seme-org/open-director](https://github.com/seme-org/open-director) | 97 / 18 / LGPL-3.0 / active | 多 Agent 阶段划分、Docker/本地状态思路 | 9-agent 全自动创作、LGPL 合规边界、与核心协议冲突的自动决策 |
| [trilogy-group/ttv-pipeline](https://github.com/trilogy-group/ttv-pipeline) | 25 / 8 / MIT / active | 长视频分段、Keyframe/Chaining、并行与远程 API 抽象 | 本地 Wan/FramePack 安装路径；不能绕过合同直接生成 |
| [pydantic/pydantic-ai](https://github.com/pydantic/pydantic-ai) | 19,915 / 2,710 / MIT / active | 结构化输出、Pydantic Schema、校验失败停机/修复 | 让模型自行重试或改变已确认剧情；需保留人工/合同边界 |
| [langchain-ai/langgraph](https://github.com/langchain-ai/langgraph) | 41,598 / 7,022 / MIT / active | 持久化状态、长流程、暂停/恢复、人工审批节点 | 把通用 Agent 图当导演规则；不允许自动扩大授权 |
| [AcademySoftwareFoundation/OpenTimelineIO](https://github.com/AcademySoftwareFoundation/OpenTimelineIO) | 1,981 / 351 / Apache-2.0 / active | 生产单元/剪辑时间线交换与可编辑交付 | 不能替代剪映实际 UI/导出 QA |
| [remotion-dev/remotion](https://github.com/remotion-dev/remotion) | 59,149 / 4,512 / license需核对 / active | 程序化预览、确定性渲染、模板化后期 | 不作为生成渠道；商业许可证需先核对 |
| [wonderunit/storyboarder](https://github.com/wonderunit/storyboarder) | 3,838 / 393 / 无明确仓库许可证 / stale | 人工故事板交互概念 | 无许可证不得复制代码；不适合 Prompt-first 自动路由 |
| [tjebastin/openmontage](https://github.com/tjebastin/openmontage) | API 快照 0 stars / AGPL-3.0 / active | pipeline/manifest/agent-skill 分层、回放和成本审计概念 | AGPL、泛化 provider、研究/素材路径和其自动化重试行为 |

## 与当前仓库对照

当前已有：

- `production_contract` Schema 与 Gate/授权校验；
- Prompt Skill 强制、Prompt QA PASS、脚本审核 PASS；
- Prompt-first / keyframe / storyboard 风险路由；
- 镜头语言重复检查；
- RunningHub/小云雀/LibTV provider enum；
- 决策记录和自适应资产路由文档；
- PR 的离线 GitHub Actions。

明显遗漏：

1. **脚本→镜头→生产单元的正式 Schema**：目前 Prompt unit 有了，缺 `shot_unit`、`production_unit`、入口/出口状态和真实尾帧依赖图。
2. **资产决策执行器**：目前只有文档，缺 `ASSET_DECISION` Schema 和 `PROMPT_ONLY_READY / KEYFRAME_REQUIRED / ASSET_PLAN_REQUIRED / STORYBOARD_REQUIRED / BLOCKED_MISSING_MASTER` 的机器状态。
3. **持久化任务状态**：需要 `TASK_CURRENT` 的仓库镜像、事件日志、任务 ID、费用、唯一下一步和异常队列；可借鉴 LangGraph 的 checkpoint 思路，但状态文件仍服从 D 盘协议。
4. **Skill provenance 锁定**：已有字段，但还需要记录输入摘要 hash、Skill commit/version、QA reviewer、证据路径，防止“Skill 名字写了但实际没用”。
5. **三渠道能力矩阵**：要描述每个渠道的参考图槽位、时长/分辨率、提交方式和可验证状态；当前只有 provider 名称。
6. **生成前/生成后两套 QA**：Prompt/资产/脚本 QA 与视频解码/画面/连续性 QA 还需统一报告 Schema。
7. **PR 规则**：目前 CI 只验证示例；还要禁止媒体、密钥、外部 URL Schema 解析和未经授权的 provider 调用代码。

## 建议复用顺序

### 现在就做

- 从 Pydantic AI 的结构化输出思路完善本地 Schema 边界；不必引入完整 Agent 框架。
- 参考 OpenReels/Reelwright 的 brief、manifest、QA report 文件形态。
- 参考 LangGraph 的 checkpoint/interrupt 概念，自己实现 JSON 事件日志，避免引入过重依赖。

### 第二阶段

- 加 `shot_unit.schema.json`、`production_unit.schema.json`、`asset_decision.schema.json`。
- 加三渠道只读 capability manifest；适配器先生成“待提交请求”，不直接提交付费任务。
- 加 FFmpeg/ffprobe 视频 QA 报告结构和 OpenTimelineIO 导出草案。

### 暂不接入

- ArcReel、StoryMind、OpenMontage、OpenDirector 的整套 Agent/平台代码；许可证、默认自动化边界或 provider 假设不适合原样搬运。
- ComfyUI 或本地视频模型链；不符合当前只通过云端三渠道生产的决定。
- 自动重试、自动换渠道、自动发布和自动生成所有资产。

## 推荐的下一条 PR

`feat: add shot, production-unit, and asset-decision contracts`

验收：给定一个 30 秒短剧段落，系统能输出结构化镜头单元、判定 Prompt-only/关键帧/故事本、列出缺失资产和唯一下一步；在任何一个字段缺失、脚本审核未通过或 Skill QA 非 PASS 时，不能生成 provider submission payload。

## 来源

- ArcReel、OpenReels、OpenDirector、OpenMontage、ttv-pipeline：对应 GitHub 仓库 README 与仓库 API 快照。
- Pydantic AI、LangGraph、OpenTimelineIO、Remotion、Storyboarder：对应 GitHub 仓库 README/API 快照。

