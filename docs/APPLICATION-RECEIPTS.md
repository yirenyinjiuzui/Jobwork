# v1.1.11 普通投递回执不清测评待办

负责方：原监督任务，沿用 v1.1.10 唯一维护副本。没有访问真实邮箱、资料或 Windows 本地项目。

## 实际复现

在临时库中已有 Test Developer / TR-1，状态 assessment、截止 2026-12-01 10:00。粘贴普通回执 `Your application for Test Developer was submitted. Thank you for applying.` 并确认，旧版 completion=True，将其当成测评完成，写为 waiting 并清空截止。

既有阶段排序本来能阻止普通 waiting 回执把面试、Offer、终止降级，但“完成测评”是允许从 assessment 转 waiting 的例外。本轮修复该例外的错误触发，不新增状态或改变已有排序规则。

## 最小修复

完成判定要求明确的测评对象与完成动作相连，不再允许 Test/Assessment 岗位名与任意后续 submitted/completed 组成测评完成。明确 application/resume/CV 的提交回执不算测评完成。真正的 `Your online assessment has been successfully completed`、`Your test was submitted` 和中文“测评已完成”仍被识别。

粘贴通知增加最多 800 字符的当前正文证据摘录，预览及历史可查看；省略链接、跟踪参数、引用历史和推荐内容。EML 保持原来的分来源有限证据，不存整个邮箱或整封邮件。不明确的岗位归属继续人工核对，未知状态不凭空创建。

当前没有批量写入端点：每条通知都有独立预览 token 和确认。本轮验证两条预览连续确认及重复导入，未加入批量功能。

## 验证

Python 146 + Node 32 = 178 项通过。新增 5 项测试含多组子场景：Test Developer / Assessment Engineer / Test / Assessment 等岗位名，粘贴与 EML、新旧发送时间、重复回执；assessment/interview/offer/closed 的状态、截止、预约及下一步保持；同公司另一岗位不变；泛化邮件保持人工复核；真正完成回执仍识别。撤回与终止沿用已有 closed 状态，没有新造状态。

HTTP 验证两个通知分别预览、连续确认只入历史，不改岗位 A 或 B。UI 闭环实际粘贴该错误样例，预览显示原文，确认后提示未覆盖当前状态，保留截止及下一步，输出 `RECEIPT LOOP PASS`。现有测评完成、延期和三项核心离线闭环继续通过。

无表结构、字段或 settings 迁移。归档 v1.1.10 实际创建的合成库与新 ZIP 解包复测见 FINAL-VERIFICATION.txt。历史包、默认 data 保持不动。

## 最短手工验收

1. 使用新的隔离演练库；创建 Fictional Receipt Lab / Test Developer / TR-1，设为测评，截止 2026-12-01 10:00。再建同公司另一岗位 TR-2，设为面试。
2. 在 TR-1 粘贴上面的英文回执，填对应公司、岗位、编号及发送时间，解析预览。应显示 waiting/等待结果的通知建议及原文证据，但不应当作“测评完成”。
3. 确认写入后应提示仅留历史，TR-1 仍为测评，原截止和下一步不变；TR-2 不变。重复导入不增加重复记录或改状态。

这套步骤未在真实 Windows/Chrome/Edge 实测；自动化为 Linux、模拟 DOM 和真实本地 HTTP/SQLite，不代表扩展工具栏或 Windows 验收。下一验收点是上述虚构流程实机核对。没有上传或对外分享。
