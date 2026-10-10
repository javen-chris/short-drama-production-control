# G4 故事本独立 QA 报告｜<项目>/<EP>/<段>

- 任务ID：`<TASK-ID>`
- QA 执行模型 / 工具：`<必须不同于故事本生成模型>`
- 故事本文件：`<绝对路径>`
- 资产映射表：`<绝对路径>`
- 生产模式：`MANUAL_REVIEW / AUTOMATION_EXCEPTION_DRIVEN`

| 格 | 人物身份 | 人数/肢体/鞋子 | 服装 | 道具 | 空间/方向 | 动作因果 | 特效 | 无文字/画质 | 结论 | 证据/修复项 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | PASS/FAIL/UNCERTAIN |  |  |  |  |  |  |  |  |  |

## 全局检查

- [ ] 格序、版式、时间区间明确
- [ ] 无重复格、白边、拼版裂缝、格号
- [ ] 每格 16:9
- [ ] 格间因果成立
- [ ] 使用真实尾帧或已标记硬切
- [ ] 故事本未被用于人物身份参考

## 下游决定

- QA 总结：`PASS / FAIL / UNCERTAIN`
- 人工模式：`WAITING_USER_STORYBOARD_APPROVAL / BLOCKED`
- 自动模式：`AUTO_PRODUCE_VIDEO_PROMPT / EXCEPTION_QUEUE / BLOCKED`
- 视频提交授权：`不由本报告授予`\n