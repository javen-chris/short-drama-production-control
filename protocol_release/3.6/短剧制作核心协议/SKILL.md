---
name: d-drive-short-drama-automation
description: Use for automated D-drive short-drama production with gated project state, user-authorized storyboards, independent QA, and explicitly authorized generation.
---

# D盘短剧自动化生产技能

> 协议版本：3.1 ｜ 最后更新：2026-09-21

**先读：** `<PROTOCOL_ROOT>\00_自动化生产唯一入口_v3.0.md`（唯一入口，含完整读取顺序、按 Gate 补读清单与 Gate 表）。

本目录是 Hermes、Codex 和其他 Agent 的共同协议源。读取顺序只在唯一入口维护一处，本文件不重复；执行契约见 `AGENTS.md`。对当前项目工作时，再读取该项目的 `00_项目入口.md`、状态、最新交接和当前 Gate 的权威文件。

核心规则：

1. 一段视频按 Gate 连续执行；用户明确“脚本已确认、全自动、RunningHub 720P 测试”时，默认使用消费级会员 `NORMAL→coins` API。只有用户明确授权cash/企业通道时才可改用SHARED；不得自行切换或把泛称“RH API”解释为企业SHARED现金授权。
2. 人物 MASTER 管身份；场景 MASTER 管空间；道具 MASTER 管外观；上一真实成片尾帧只管承接；故事本只管镜头顺序。
3. 没有明确视频提交授权不得生成/付费；一次测试授权不包含失败重试、追加候选、换模型、扩时长或发布。
4. QA 与生成模型独立，完整播放和抽帧取证；用户目视优先。
5. 状态、确认、QA、异常与下一步必须写入项目文件；不依赖聊天记忆。

详细规则见同目录 `01_标准项目目录与文件职责_v3.0.md`、`02_每段视频制作流程_v3.0.md`、`04_QA与文件治理_v3.0.md`。\n