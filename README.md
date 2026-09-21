# Multi-Agent Production Control

A source-controlled **control plane** for multi-agent production workflows. It decomposes a complex, multi-stage production process into routable agent roles, enforces quality gates before and after generation, and governs every artifact with provenance — so a pipeline runs repeatably, with reviewable evidence instead of ad-hoc coordination.

It is deliberately **not** the authority for scripts, MASTER assets, media, or API keys. It is the layer that decides *what may proceed, on what evidence, and in what order*.

> Validated end-to-end on a real high-complexity pipeline: **scripted episodic video production** — script breakdown → independent script review → scene continuity → adaptive asset routing → prompt compilation → generation → pre/post QA → version governance.

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
- requires every video prompt to record Skill provenance, an independent QA `PASS`, and a `PASS` script review;
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
- keeps validation offline; provider credentials and actual submissions stay local.

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

## 运行总表：前台审查工具（中文）

日常用得最多的入口。完整操作手册：[docs/运行审查工具_操作手册.md](docs/运行审查工具_操作手册.md)。

### 启动方式

| 方式 | 命令 / 动作 |
|---|---|
| 双击（推荐） | `tools\start-run-board.cmd` — 自动扫描出所有项目，输入序号回车即可，无需拖文件夹 |
| 命令行起实时服务 | `python tools/render_run_report.py "<项目目录>" --serve` |
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
python tools/append_event.py "<项目目录>" --run RUN-EP02-N3-A2 --step <skill> ^
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
- **Gates over trust.** Generation is expensive; independent review runs before and after, and no stage repairs the objects it reviews.
- **Provenance by default.** Every accepted artifact traces back to its inputs and decisions.
- **Domain-portable.** The chain is defined by roles and gates, not by the content it produces. The same skeleton applies to any multi-stage pipeline with hard continuity constraints.
