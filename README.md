# Multi-Agent Production Control

A source-controlled **control plane** for multi-agent production workflows. It decomposes a complex, multi-stage production process into routable agent roles, enforces required content gates before generation and tracks provider task facts through a terminal status, and governs every artifact with provenance — so a pipeline runs repeatably, with reviewable evidence instead of ad-hoc coordination.

It is deliberately **not** the authority for scripts, MASTER assets, media, or API keys. It is the layer that decides *what may proceed, on what evidence, and in what order*.

> The repository validates the offline control plane, schemas, and fixtures. Real provider submission and generated media are not part of CI; post-generation analysis is a separate user-requested task.

## Why this exists

Complex production processes fail in predictable ways:

- **state drifts between stages**, so later steps silently contradict earlier ones;
- **quality is checked only at the end**, when rework is most expensive;
- **reruns are not reproducible**, and no one can prove why an output was accepted;
- **prompts and assets are edited ad hoc**, with no version or provenance trail.

This control plane addresses each of those with explicit contracts, gates, and governance — not with a bigger prompt.

## Control plane

- validates `production_contract.json` before any provider adapter can submit work;
- lints a prompt production unit before routing;
- requires every video prompt to record Skill provenance, an independent pre-generation QA `PASS`, and a `PASS` script review;
- checks consecutive shot-language reuse and requires a stated reason when repetition is intentional;
- implements a source-controlled Skill chain for routing, breakdown, independent script review, scene continuity, adaptive assets, conditional storyboards, neutral prompts, pre/post QA, and three local provider adapters;
- persists confirmed workflow decisions in `docs/decisions/` and adaptive asset routing in `docs/architecture/`;
- pins every image asset to one declared model and channel, with the paid fallback used only on a recorded reason and explicit authorization;
- renders a step-by-step run report — text or a self-contained HTML page — showing which Skill each step invoked, which protocol documents it read, where the evidence is, and where a run stopped;
- keeps a multi-segment episode navigable: one trace file per segment plus a project index, with a locally served page (`--serve`) whose refresh button always returns current state;
- blocks a video submission when its content is incomplete: every reference asset and parameter must be listed and verified (authorization alone is not enough);
- keeps task state, asset decisions, provider capabilities, unified QA checks, provenance hashing, payload compilation, and PR security scanning;
- keeps a dated AIGC production benchmark and reuse boundary in `docs/research/`;
- treats prompts as the default path and storyboards as a risk-triggered exception;
- keeps validation offline; provider credentials and actual submissions stay local. CI security scanning rejects media, common secrets, machine-specific Windows paths, production workflow-record directories, and production-shaped RUN/provider task IDs outside synthetic fixtures.

## Providers

The same contract supports only these provider adapters:

- `runninghub`
- `xiaoyunque`
- `libtv`

Each provider has a repository Skill describing its adapter boundary. These Skills do not contain credentials or network implementation. They may translate validated inputs into provider parameters, but cannot change story, asset responsibilities, duration, or prohibited actions. Actual submission requires local credentials and explicit contract authorization.

## Skill chain

The executable chain declaration is `skills/skill-chain.json`. Validate it with:

```powershell
python -m production_control.skill_chain_validator
```

Install or refresh the repository Skills in the current user's Codex Skill directory with:

```powershell
powershell -ExecutionPolicy Bypass -File tools/install_repo_skills.ps1
powershell -ExecutionPolicy Bypass -File tools/install_repo_skills.ps1 -Replace
```

`-Replace` deletes and recopies only the exact Skill folders named by the repository manifest. It never copies API keys. Restart Codex after installation so discovery is refreshed.

## Local use

```powershell
python -m pip install -e ".[dev]"
python -m production_control.contract_validator examples/production_contract.valid.json
python -m production_control.prompt_linter examples/prompt_unit.direct.json
pytest
```

See [docs/protocol-mapping.md](docs/protocol-mapping.md) for the mapping to the local authority protocol documents.

### Protocol release and local authority

The source of truth remains the local authority folder declared by `SHORT_DRAMA_PROTOCOL_ROOT` or the repository's relative `skills/skill-chain.json` entry. This checkout includes a versioned, read-only protocol release at `protocol_release/3.6/短剧制作核心协议` so CI and clean installations do not need a personal Windows drive. It contains protocol text and a fingerprint manifest, not production scripts, media, RUNs, or credentials. When the authority changes, publish a reviewed release snapshot and regenerate its manifest; do not edit the local authority by editing the release copy.

```powershell
$env:SHORT_DRAMA_PROTOCOL_ROOT = 'D:\path\to\短剧制作核心协议'
py -3 tools/protocol_fingerprint.py check --root $env:SHORT_DRAMA_PROTOCOL_ROOT
```

### Asset index and RUN restore

Keep reusable character, scene, and prop MASTER assets in the series asset library. Keep episode-specific inputs in that episode's existing project folders, and point to them from its project entry and the series `asset_index.json`; do not bulk-move existing project media. The index stores IDs, roles, source paths, hashes, confirmation evidence, and change history. A RUN may keep a separate immutable snapshot of confirmed inputs under its own `workflow/asset_snapshots/<RUN-ID>/` folder.

```powershell
py -3 tools/validate_asset_index.py '<series-root>\资产库\asset_index.json'
py -3 tools/resume_run.py '<episode-project>' --run '<existing-RUN-ID>' --inspect
py -3 tools/resume_run.py '<episode-project>' --run '<existing-RUN-ID>'
```

`--inspect` is read-only. Resume keeps the original RUN and appends a resume record; evidence without stored hashes is not automatically trusted. An existing provider task resumes at G6-S12 for status lookup and is never resubmitted by this command.

## 运行控制台

入口说明和离线命令见[运行审查工具操作手册](docs/运行审查工具_操作手册.md)。本机项目路径通过 `tools/board-project.txt` 配置；请勿把生产项目目录、RUN 轨迹或媒体提交到公共仓库。

### 启动方式

**只有一个启动入口**：`tools\一键打开看板.cmd`（桌面上的「短剧看板」快捷方式指向它）。
双击即可，它会回收旧看板占用的端口、启动服务、并打开浏览器。要切换项目，
先复制 `tools/board-project.example.txt` 为 `tools/board-project.txt`，再填入本机项目路径；该个人配置文件由 `.gitignore` 排除。

> 之前有 5 个入口（仓库内 2 个 `.cmd`、仓库外 2 个 `.cmd`、1 个交互式菜单），
> 行为各不相同，双击两次还可能互相杀掉对方的看板。已合并为这一个。

| 方式 | 命令 / 动作 |
|---|---|
| 双击（推荐） | `tools\一键打开看板.cmd` — 读 `tools\board-project.txt`，回收端口后启动 |
| 命令行起实时服务 | `python tools/render_run_report.py "<项目目录>" --serve` |
| 等价的模块写法 | `python -m production_control.run_server "<项目目录>"` |
| 只看一次，不起服务 | `python tools/render_run_report.py "<项目目录>"` |
| 导出静态快照归档 | `python tools/render_run_report.py "<项目目录>" --html 快照.html` |

服务只绑定 `127.0.0.1`，默认端口 **8765**（被占用会自动试到 8775，以黑窗口里实际打印的网址为准）。
关掉黑窗口＝停止服务。页面每次刷新都重新读取磁盘上的轨迹文件，所以永远是最新状态，Agent 正在跑也看得到。

`<target>` 可以是三种东西，工具会自动识别：项目目录（整局总表）、`<项目>/workflow/run_index.json`（同上）、
`<项目>/workflow/runs/<某个>.json`（单段明细）。

### 页面入口

| 地址 | 内容 |
|---|---|
| `/` | 当前段视图（`?run=<run_id>` 可切段） |
| `/overview` | 全剧总览；可编辑并保存段清单 |
| `/run/<run_id>` | 单段明细 |
| `/data`、`/text` | JSON / 纯文本总表（给脚本消费） |
| `/api/segments` | GET 读段清单；**POST 是唯一的写入通道** |
| `/health` | `{"status":"ok"}` — 排查时先敲它 |

### Agent 侧：记一步

```powershell
python tools/append_event.py "<项目目录>" --run RUN-EXAMPLE --step <skill> ^
  --protocol <协议文件> --evidence <证据文件> --outcome COMPLETED
```

两条硬约束：`--evidence` 指向的文件**必须真实存在**（拒绝指向不存在的证据）；
`--outcome` 只有 8 个合法值，定义在 `src/production_control/outcomes.py`，未知值直接报错而非静默吞掉。

### 本机跑测试

终端里若设了 `HTTP_PROXY`，访问 `127.0.0.1` 的测试会被发给代理而假死（表现为跑完不退出）。先清掉再跑：

```bash
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy no_proxy=127.0.0.1,localhost pytest
```

## Design notes

- **Contract-first.** Nothing reaches a provider adapter without a validated contract.
- **Gates over trust.** Generation is expensive; independent content review runs before submission, and no stage repairs the objects it reviews.
- **Provenance by default.** Every accepted artifact traces back to its inputs and decisions.
- **Domain-portable.** The chain is defined by roles and gates, not by the content it produces. The same skeleton applies to any multi-stage pipeline with hard continuity constraints.

## 最终包审核与协议迁移（2026-10-10）

RunningHub 使用 `tools/final_packet.py bind/qa/check`；包上传绑定先冻结，QA 调用固定 Terra，通用 `qa_verdict.py` 的 S09 增加 `--qa-invocation-evidence`。提交适配器调用 `final_submission.submit_bound_packet(project, run_id, send)`，send 只发送原 payload；网络前保留单次提交意图，超时不自动重试。`start_run.py --confirmed-assets <已确认资产清单.json>` 建卡同时保存任务快照。

协议维护 generate 追加 `.protocol_versions` 文本版本；迁移先 `tools/migrate_run_protocol.py <project> --run <RUN-ID> --inspect`，适用变更需逐项 `--confirmed-path` 和已确认的 `--confirmation-evidence`。缺少旧文本不伪造 diff，旧 RUN/Task ID/预算/已消费提交次数沿袭。运行不会因无关 Gate 文档变化而全局失效。
