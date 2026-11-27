# 类似产品、扩展与 Skill 对照

调研日期：2026-11-19。以下是从作者官网、官方帮助文档、扩展商店和项目仓库核对的功能，不是安装或实测结论。没有把你的邮箱、简历或账号交给这些产品，也没有复制或执行它们的代码。

| 工具 | 已核对的特点 | 对这个软件的启发 |
| --- | --- | --- |
| [Simplify Copilot](https://help.simplify.jobs/en/articles/1749022-install-and-set-up-copilot) · [Chrome 扩展](https://chromewebstore.google.com/detail/simplify-copilot-autofill/pbanhockgagggenencehbnadejlgchfc) | 支持的申请网站可预填，申请人核对并点最终提交。其 [不支持的填表帮助](https://simplifyjobs.featurebase.app/help/articles/8717287-autofill-not-supported) 区分收藏岗位与填表。 | 继续把「职位建档」「填表」「提交」拆开，不能因为填了表或存了岗位就显示已投。 |
| [Teal Job Search Companion](https://help.tealhq.com/en/articles/9524956-teal-job-search-companion-bookmark-jobs) · [Chrome 扩展](https://chromewebstore.google.com/detail/teal-job-search-companion/opafjjlpbiaicbbgifbejoochmmeikep) | 在岗位页面收藏；不能完整提取时仍可以手工调整。 | v1.1 增加「从当前网页提取岗位草稿」，预览后送往本机的手动录入表。不完整的字段由你补。 |
| [Huntr](https://help.huntr.co/en/articles/9859408-the-huntr-chrome-extension) · [Chrome 扩展](https://chromewebstore.google.com/detail/huntr-job-search-tracker/mihdfbecejheednfigjpdacgeilhlmnf) | 集中收集职位、辅助填表、以看板跟踪阶段与截止日期。 | v1.1 增加状态看板与每条投递所用的简历版本标记。继续保留方便搜索的列表。 |
| [Jobright](https://jobright.ai/tools/ai-job-apply) | 其页面区分 Autofill 扩展与 Agent 代办流程，宣传岗位匹配和定制申请。 | 先看岗位资格和证据，不给没有依据的匹配分，也不自动批量投递。 |
| [jlog](https://jlog.ai/open-source-job-tracker/) · [MIT 仓库](https://github.com/brgv-code/jlog) | 可自行部署的候选人追踪工具，有职位捕获、支持部分站点的预填和进度记录；自部署功能范围以其文档为准。 | 找到与本项目很接近的开源参考。保留你现有的零 Python 依赖本机运行，不为替换框架重做现有功能。 |
| [AI Job Search](https://github.com/ai-job-search-dev/ai-job-search) · MIT | 基于 Claude Code 的求职工作流，含岗位评估、按职位调整简历草稿和模拟面试等。README 明确将 `/apply` 描述为材料评估与生成流程，不应仅凭命令名理解为自动提交。 | 适合参考工作流，不等同于 Codex 一键可用。本项目附独立的 [岗位复核 Skill](../skills/job-workbench-review/SKILL.md)，不接管浏览器、不改台账。 |
| [Just a Job App](https://github.com/JustAJobApp/jobseeker-analytics) | 项目说明使用 Gmail 邮件构建求职看板。 | 收件箱集成是值得后续做的方向；本版仍以手选邮件和人工确认避免误更新，未连接真实邮箱。 |

## 对香港实习与内地校招的实际取舍

- [Jobsdb 香港官方提醒说明](https://help.hk.jobsdb.com/article/What-are-JobsDB-Job-Alerts-DB) 和 [LinkedIn 官方提醒帮助](https://www.linkedin.com/help/linkedin/answer/a511279) 都有按保存搜索推送新岗位的功能。可以在网站自己开启，将自己筛过的职位再送进本机台账；不是本软件代开提醒。
- [CityUHK CareerHub](https://www.cityu.edu.hk/en/sds/career-leadership/for-employers/post-a-job) 值得作为单独来源。从校内平台打开的页面可用人工录入，是否有可读取的职位字段需要实测。
- BOSS 直聘、Jobsdb、城大招聘平台都不宣称能通用自动填表。特别是只在 App 显示或网页访问受限的岗位，继续使用分享链接 + 手动补充。不做后台抓取、绕过验证码或代投。
- 对企业自己的招聘系统，使用已公开文档的板块 API 比抓取网页更可控。v1.1 接入 **SmartRecruiters** 官方公开发布职位接口；正常使用不需登录，源失败仍保留历史快照。配置说明见 [支持的招聘源](SOURCES.md)。

## 实施与未做事项

已实现：当前页职位草稿、投递看板、每条投递的简历版本、面试/截止日 `.ics` 导出、SmartRecruiters 来源、岗位复核 Skill。日历格式参照 [RFC 5545](https://www.rfc-editor.org/rfc/rfc5545)；导出是快照，改期不会自动同步到日历。

未开启：真实邮件同步、招聘账户登录、第三方扩展安装、批量自动提交。未核实第三方扩展对 BOSS 或你常用的香港招聘表单的兼容性。若比较实际体验，首轮应只用模拟资料和你个人常用的一两个门户，分别检查「能否看清提取的数据」「能否手动复核」「是否误标已投」。
