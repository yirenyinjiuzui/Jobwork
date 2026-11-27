# 招聘来源：支持范围与录入方式

「岗位发现」只读取公开招聘板，无须平台账号或 API 密钥。新增来源时，先从公司招聘官网确认平台，记录公司名，并填入板块代号或对应的完整网址。不要把你的账号链接、求职状态页面或含私人令牌的链接填作招聘源。

| 来源 | 公司官网给出的招聘板示例格式 | 备注 |
| --- | --- | --- |
| Greenhouse | `https://job-boards.greenhouse.io/公司代号` | 使用 [Greenhouse 公共 Job Board API](https://docs.greenhouse.io/job-board#list-jobs)。 |
| Greenhouse（欧洲招聘板） | `https://job-boards.eu.greenhouse.io/公司代号` | 仍使用官方文档列出的公共 API；若该公司未通过这一接口发布，则会报错，请手动收藏。 |
| Lever | `https://jobs.lever.co/公司代号` | 按 [Lever 官方 Postings API](https://github.com/lever/postings-api#get-a-list-of-job-postings) 分页读取发布中的岗位。 |
| Lever（欧洲） | `https://jobs.eu.lever.co/公司代号` | 使用 Lever 的欧洲公共 API。 |
| Ashby | `https://jobs.ashbyhq.com/公司代号` | 用 [Ashby 公共 Job Posting API](https://developers.ashbyhq.com/docs/public-job-posting-api)，仅显示已发布且在官网列表可见的岗位。 |
| SmartRecruiters | `https://careers.smartrecruiters.com/公司代号` | 用 [SmartRecruiters 公共 Posting API](https://developers.smartrecruiters.com/reference/v1listpostings) 分页读取公开岗位，无需身份验证。列表未给单个岗位链接时，打开公司招聘板后用岗位标题搜索。 |
| 其他网站、招聘公众号、BOSS 直聘 | 公司的官方招聘入口或你核实过的职位分享链接 | 手动收藏。软件不抓这些站点，不处理登录、验证码、反爬限制。 |
| 演示来源 | 不访问网络 | 用于演示新岗位和重新开放提示，不是真实招聘。 |

首次成功检查只建立基线，已有岗位会显示，但不会作为新消息刷屏。后续检查时，同一来源里新增或重新出现的职位会被标记。职位从成功读取的招聘板消失，只表示**这个来源不再公开显示该岗位**，并不代表你的申请结束。连接失败、限流、招聘板不存在或响应不完整时，保留旧清单。初次添加请核对链接与公司，不要只凭同名代号判断是同一家公司。

香港、内地、实习、校招等分类根据来源给出的地点、职位名和用工类型预分。截止日仅在有明确日期时录入；毕业要求和到岗时间为空时，请打开官方职位页确认。尚未公开发布的校招通道、公司预告或只通过其他门户发布的岗位，不会被此处的 API 发现。

手动收藏时，岗位身份判断会忽略明确的营销追踪参数（如 `utm_*`、`gh_src`、`gclid`）及链接片段，但保留岗位 ID 和其他功能参数。打开时仍使用你录入的完整网址。
