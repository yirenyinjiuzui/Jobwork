# 验收记录

发行版 1.1 的检查使用临时 SQLite 数据库与虚构通知，不需要真实招聘账户。

| 场景 | 验收 |
| --- | --- |
| 四种公共招聘板 | Greenhouse、Lever、Ashby、SmartRecruiters 的公开格式、地点与类型归类、分页与地址校验使用固定模拟响应测试。实际公司的板块是否开放、能否在你的网络连接，要在「招聘来源 → 检查」确认。 |
| 开招提醒 | 用演示招聘板连查三次：第一次建立基线，第二次新增 1 个、下架 1 个，第三次有 1 个重新开放。读取异常不会把旧记录下架。 |
| 岗位追踪 | 同公司不同岗位编号独立、导入后较晚的改期优先、旧安排留在历史、重复通知不重复写、期限延期标注推算、完成回执清理网测待办。 |
| 应用端到端数据流程 | 前端 DOM 模拟 + 真实 localhost HTTP / SQLite：渲染四个页面、保存岗位、录入申请、识别预览不写库、明确确认后更新状态与历史、资料保存。 |
| 辅助填表 | 测试扩展权限、双语匹配、跳过已有值和凭据控件、选择目标发生变化时拒绝写入、只填写已确认目标。未能在构建环境启动真正的 Chrome/Edge，因此尚未做工具栏实机验证；可按扩展说明在 Windows 用本地练习表单复现。 |
| 截图识别 | 使用本机 Tesseract 实测模拟截图，成功提取 “Full name” 与 “Email address”。未验证中文语言包；需要在你本机安装。 |
| v1.1 回归 | 测试旧版 SQLite 数据迁移、旧版带营销参数收藏复用、不同有效岗位 ID 不误合并、Chrome 草稿解析与隐私链接清理、显式保存、看板状态变更、简历标签与真实 HTTP `.ics` 下载。 |
| 安全与隐私 | 测试本机服务拒绝非本机 Host、跨站 Origin、非 JSON 写入与已知危险链接。没有登录真实邮箱、读取登录后的招聘后台、上传简历或投递。 |

运行命令：

```text
python -m unittest discover -s tests -v
node --test tests/test_extension.mjs tests/test_capture.mjs tests/test_popup.mjs tests/test_ui.mjs
```

在 Windows 上建议先用演示库和扩展附带的虚构资料试跑。对于真实求职，先核查职位入口和岗位条件，核对每次扩展填入的资料和网站本身的“已提交”回执；浏览器扩展不会代替你点提交，也不会把填完表当成投递成功。


## 首轮项目监督（2026-11-19 UTC，仅维护副本）

负责方：助手负责排查、维护和回归；用户仅负责 Windows 本机、浏览器扩展和本机网络验证。状态：云端验收通过，Windows 实机待验收。此记录不改变已归档 v1.1。

- 基线：维护副本初始 35 个归档条目逐字节一致；ZIP 和现有 TXT 解码结果均为 SHA-256 `c42727b07937de0ac0bae329282a940d16e331fccdb0d20bf61fbfb84a4565c1`。没有重新生成备份。
- Windows 静态核对：两个 CMD 均为 CRLF；`cd /d "%~dp0"` 支持切换盘符及带空格目录；启动入口、默认端口 8765、数据位置及参数转发与 README 一致。脚本不主动检查 Python 次版本，仍需安装 3.11+。PowerShell 手动运行命令前须进入包含 server.py 的目录。
- 云端实测：Python 3.12.14，临时独立 SQLite，实际启动 server.py（回环端口 18765，关闭自动检查与自动打开浏览器）。`/`、`/index.html`、`/app.js`、`/style.css`、`/demo-form.html`、`/demo-form.css`、`/api/state` 全为 HTTP 200。验证结束后服务退出、临时库清理。
- 非阻塞遗留：ASSETS 有 `/demo-form.js` 路由但文件不存在，访问为 404；练习页未引用它，当前功能无需该文件。本轮不改动此路由。
- 公开源只读实测：Greenhouse/stripe 780 条，Ashby/linear 32 条，SmartRecruiters/Visa 有效空列表（不代表其他渠道无岗位）。Lever/palantir 默认 8 秒超时；诊断总时限 30 秒可在 25.40 秒返回 307 条。
- 维护修复：仅 discovery.py 的 fetch_jobs 默认总时限由 8 改为 30 秒，保留分页完整性和失败不更新旧记录的逻辑。修复后不传 timeout 的真实默认路径在 26.56 秒返回 307 条。未重新打包或替换已发布版本，用户现有 v1.1 仍为旧时限。
- 回归：修复前和修复后均为 Python 52 项 + Node 14 项全部通过，包括真实 HTTP/SQLite 的界面流程。模拟 DOM 测试不等于 Windows Chrome/Edge 工具栏实测。以上在线条数仅为本次检查快照，不是岗位推荐。

### 最短 Windows 验收（下一验收点）

1. 附件已恢复可跳过。若 ZIP 仍无法下载，继续使用现有 TXT 和既有 PowerShell 还原方案；不要重新索取同一备份。恢复 ZIP 后用 Get-FileHash 核对上述 SHA-256，再解压到 D 盘；进入实际含 start-windows.cmd 的 job-workbench 文件夹。
2. 在该文件夹打开 PowerShell，运行 `py -3 --version`（无 py 时用 `python --version`），确认 3.11+。运行 `.\start-windows.cmd --data data\acceptance.sqlite3 --interval 0`。首页应自动打开；未打开则访问 http://127.0.0.1:8765/ 。点“载入演示记录”，演示来源连查三次，观察基线、新岗位、重新开放。关闭服务，再用同一命令启动，确认演示记录仍在。
3. 只验用户常用的一个浏览器：在 Chrome/Edge 扩展页加载本目录 extension，打开本地练习表单，导入 extension/demo-profile.json；扫描、勾选并填写。姓名等空白字段应填入，已有作品集链接不变，毕业时间和工作许可保持空白。关闭弹窗后重新打开，应需重新导入资料。无需点击任何真实申请提交。
4. 在一个可信公开职位详情页“识别当前岗位”，点“在工作台核对（不保存）”；应只带入表单，未点击录入前岗位库不增加。对用户实际想监测的公开招聘板做一次“检查”，记录成功/错误提示；无需为验证而添加全部四个平台。失败由助手继续定位，不让用户调代码。

验收反馈最小集合：启动/重开是否成功、扩展练习和草稿是否成功、招聘源检查结果（失败时复制错误文字与公开源地址）。目前没有 Windows 环境，无法替代 D 盘启动、浏览器工具栏权限、客户端附件下载和用户网络的实测。下一轮由助手根据这组结果继续处理；维护补丁尚未交付安装，不能把它视为用户机器已更新。无真实邮箱、凭证、登录或投递操作。


## v1.1.1 候选：Windows 安装与恢复维护轮次

负责方：助手完成同一维护副本修改、测试、打包和交付；Windows 本机只承担无法在 Linux 替代的最后验收。未修改 v1.1 发布包。

变更：增加 launch.py 预检（Python 3.11+、主模块与页面资源完整性），两种 Windows 入口复用 Python 选择与错误退出处理；新增 Windows 安装、故障、独立试用库及保留旧数据的升级说明；保留已验证的 Lever 默认 30 秒修复。TXT 附带 PowerShell 恢复命令和 ZIP SHA-256，先验码再创建全新目标，拒绝已有目标。ZIP 打包排除 data、缓存和数据库，已有发行成品禁止覆盖。

本轮自动测试：Python 60 项、Node 14 项，共 74 项通过。新增 8 项覆盖旧 Python、缺失文件、预检不修改已有 data、失败启动不创建 data、打包排除数据库、中文空格路径、ZIP/TXT 字节一致、拒绝覆盖发行文件、损坏/截断备份拒绝。既有 UI/HTTP 测试仍使用临时 SQLite，覆盖演示源、追踪、草稿预览、看板和日历下载。测试计数中一项可含多个断言。

限制：Linux 未安装 PowerShell，恢复命令经过静态检查与对应编解码/摘要/归档保护逻辑测试，但没有执行 Windows PowerShell、CMD、D 盘或真实扩展工具栏。不能把云端通过宣称为 Windows 全面验收。归档解压后的完整回归与实际启动结果随本轮交付正文记录。

下一最重要缺口：在常用 Chrome 或 Edge 完成真实扩展的本地练习表单和公开职位草稿回传验收，以确认发现→预填→追踪交接可用；缺少实机证据时不追加自动提交功能。


## v1.1.2 候选：本地邮件 MIME 证据与岗位隔离

负责方：助手负责唯一维护副本、虚构夹具、针对性与完整回归、解压验证和交付；真实 Windows 与扩展工具栏由用户仅作必要验收。本轮没有访问另一个 Windows Codex 项目。

修复前已复现：text/plain 只有通用页脚，HTML 的公司、岗位和拒信被忽略，解析返回 waiting、has_explicit_status=False、空公司/岗位。修复后分别分析 plain、HTML 文本与主题，显示有来源的惰性文字证据。正文状态或身份冲突不预选，需勾选复核；不明确选择新状态则只写历史，不改投递字段。明确建议目标与用户选中目标不同，服务端也要求复核。

测试：新增 20 项 MIME/存储针对性测试与 3 项真实 HTTP 测试；完整 Python 共 83 项、Node 扩展/捕获/UI 共 14 项全部通过。UI 测试另覆盖虚构文件选择→HTML 证据→确认，仅 A 终止而 B 的已排面试逐字段不变；冲突复核默认不变更。对外 socket 禁用下 HTML 解码正常，链接、图片、脚本、样式不执行，跟踪参数不进入证据。新建数据均为临时 SQLite，无真实用户数据。

可复现证据：同一虚构公司 Fictional Harbor Labs，A Data Intern / FA-1001，B Systems Graduate / FB-2002。HTML 的 “Your application was unsuccessful.” 仅建议 A；确认前不变，确认后 A closed、B interview 与时间原样。正文 closed/interview 两种顺序、雇主级审核、SWE/泛称、重复岗位名、推荐区/链接/裸编号、身份冲突均有回归。详见 tests/test_mail_evidence.py、tests/test_server.py、tests/test_ui.mjs 与 docs/MAIL-IMPORT.md。

范围限制：这是保守规则解析，不支持任意自然语言、模板或邮件真实性认证；链接文字、图片内岗位、非标准推荐区与复杂转发可能需要人工核对。Linux 自动化与模拟 DOM 不等于 Windows 或真实浏览器扩展工具栏实测。既有 v1.1、v1.1.1 发布包保持原字节；最终解压验收证据随交付正文报告。


## v1.1.3 候选：原页面与原表单绑定

负责方：助手检查和修复唯一维护副本，用户仅保留必要 Windows 实机验收。先确认旧版已有完整 URL/标签页/字段元数据检查，再用新增失败回归复现同 URL 同形替换节点被错误写入。修复增加当前文档隔离世界的单次、两分钟内有效会话及原节点/form 引用；DOM 变化、标签隐藏/切换和重载失效；全组选项预检、逐项同步检查后写入，事件改变页面则停止余项。没有增加权限、持久化个人值或指纹、采集完整页面，也不自动提交。

完整回归：Python 83 项；Node 29 项（扩展字段 17、岗位捕获 6、popup 5、UI/HTTP 1），合计 112 项通过。Node 部分是模拟 DOM/API 与隔离世界，不是真实浏览器。覆盖原 URL、SPA 新字段与表单、标题变化、切页再切回、最后查询竞态、字段改动前整组停填、第一项事件重建后其余不填、正常页面、超时/单次/重扫会话。v1.1.2 邮件 83 项 Python 回归与 UI 中 A/B 隔离仍通过。

Linux 真实 Chromium 156.0.8078.79 已尝试启动独立临时无账号浏览器，因 process_singleton_posix.cc 的 socket() failed: Operation not permitted 在启动阶段退出，故真实扩展尚未加载验证。Windows/Edge、CMD 与 PowerShell 实机也未验证。完整限制与虚构页面复现步骤见 docs/PREFILL-BINDING.md。版本只作候选；不上传本轮或上一轮文件到 Library。


## v1.1.4 候选：香港实习地点误筛

负责方：助手继续唯一维护副本与本地验收，主对话负责交付。本轮先复现地点标注 Hong Kong、实习正文 Singapore＋毕业后香港转正仍进入旧筛选的缺口。修复浏览器有限摘录、原文来源传递、主程序派生判断与 HK 筛选复核分区。没有覆盖原文或静默删岗，不改变数据库 schema。

新增 Python 地点测试 13 项、Node 捕获测试 3 项，UI/HTTP 集成扩展五份虚构本地网页的闭环。完整预期计数为 Python 96＋Node 32＝128；最终归档解压复测结果随交付正文记录。旧记录可读，原 jobs 字段与列结构保持；旧缺失正文列为待复核而非自动肯定香港实习。此前预填和邮件回归继续包含。

模拟网页/DOM 与真实本机 HTTP/SQLite 分开记录，不宣称真实扩展已验证；Windows/Chrome/Edge 实机仍待。有限摘录和规则无法覆盖所有自然语言及 ATS 模板，见 docs/LOCATION-REVIEW.md。产物只保留工作区，不上传、不再请求交付审批。


## v1.1.5 独立数据快照候选

负责方：本监督任务。唯一维护副本继续；无真实数据、账户访问或上传。

隔离复现：WAL 活跃连接下，已提交投递记录 1 条；只复制主库读到 0 条。新增 data_snapshot.py 使用标准库 SQLite Backup API，新目标独占创建、只读打开源、快照转独立 DELETE journal、关闭回读 integrity_check 和 foreign_key_check，再显示路径/投递及岗位数量/SHA256。备份和还原都不覆盖已有目标及旁文件，不迁移来源。Windows 新增 data-tools-windows.cmd，复用 Python 版本检测；无需粘贴 PowerShell。

维护副本完整回归：Python 104 项、Node 32 项通过（136 项）。新增 8 项测试覆盖活跃 WAL 已提交/未提交、主文件遗漏对照、恢复记录与完整 sqlite_master 一致、来源缺失、原库/原备份/目标及旁文件保护、无效来源清理、缺失父目录、中文/空格/方括号、CLI 非零失败与交互入口。无实际 Windows PowerShell 5.1，因此不声称 TXT 的 PowerShell 恢复或 CMD 启动已实测。ZIP/TXT 内容校验、解压复测及还原库 HTTP 结果见产物目录 FINAL-VERIFICATION.txt。

下一验收点：Windows 上按 WINDOWS.md 双击完成一次合成库备份/还原，核对 SUCCESS、条数和启动；真实扩展验收仍待。备份完成之后的新事务不会自动追加到快照；升级前停旧服务。异常中断留下的未验证目标不应使用，工具拒绝覆盖，换新名字重试。


## v1.1.6 岗位身份候选

参见 [岗位身份与验证](JOB-IDENTITY.md)。维护副本 Python 109、Node 32 项通过。公开源同 ID 更新/重新开放保持原条目；手动跨来源编号分别保留；5 个 UI 草稿确认、分别收藏及独立状态闭环通过。没有数据库结构迁移，没有改默认 data 或旧发行包；归档数据库与解压复测见成品 FINAL-VERIFICATION.txt。


## v1.1.7 邮件时序与确认

[详细变更与验收](MAIL-CHRONOLOGY.md)。Python 118 + Node 32 = 150 项通过；新增实际投递时间列，旧记录默认未知；确认事务内核对预览记录。归档旧库迁移和解压复测见成品目录 FINAL-VERIFICATION.txt。无真实数据访问或上传，Windows/真实浏览器仍待验收。


## v1.1.8 离线核心闭环与测评延期

[验收步骤与边界](OFFLINE-CORE-ACCEPTANCE.md)。修复相对测评截止缺少身份/单独确认的实际缺口。维护副本 Python 123 + Node 32 = 155 项通过；同一虚构投递串联发现、确认收藏、预填无提交、测评和面试邮件证据。模拟 DOM 与真实 HTTP/SQLite 明确区分；解压与旧库兼容详见成品 FINAL-VERIFICATION.txt。


## v1.1.9 测评完成作用域

[复现、修复与步骤](ASSESSMENT-COMPLETION.md)。Python 132 + Node 32 = 164 项通过；只清唯一确认的已知测评，保留其他待办，重复/旧延期不能重开。沿用 settings，无表结构迁移。旧库及解包结果见成品 FINAL-VERIFICATION.txt。无上传；Windows/真实 Chrome/Edge 仍待验收。


## v1.1.10 来源状态证据

[复现、规则与验收](SOURCE-VERIFICATION.md)。Python 141 + Node 32 = 173 项通过；异常空或旧快照缺席不关闭，正常恢复不虚报重新开放，原页证据确认可关闭指定岗位。沿用 settings，不迁移表结构。新 ZIP 解包和旧库兼容见成品 FINAL-VERIFICATION.txt。Windows/真实 Chrome/Edge 仍待验收；无真实数据或上传。


## v1.1.11 普通投递回执

[缺陷与验收](APPLICATION-RECEIPTS.md)。Python 146 + Node 32 = 178 项通过。收紧完成语义，避免岗位名 Test 被当成已完成测评；粘贴证据有限保留；连续确认、乱序和重复不降级、不串岗。无数据库迁移。解包与旧库兼容见成品 FINAL-VERIFICATION.txt。真实 Windows/Chrome/Edge 仍待。


## v1.1.13：重建恢复基线 + 启动保护

原始 v1.1.12 未找回，不声称相同包或哈希。[基线与补丁记录](BASELINE-RECONSTRUCTION.md)。重建恢复阶段 Python 154 通过，合并启动补丁后 Python 159 + Node 32 = 191 项通过。最终解包、归档旧库及补丁复放见成品 FINAL-VERIFICATION.txt。无上传，真实 Windows/Chrome/Edge 待验收。
