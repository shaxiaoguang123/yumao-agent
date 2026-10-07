# 羽毛球预约系统：多用户与 Agent 计划设计

- 日期：2026-10-07
- 状态：设计方向已在对话中确认，等待用户审阅本规格
- 目标：在现有预约流程上构建本地开发的前后端分离多用户应用，后续仅向授权的 Tailscale 网络成员开放。

## 1. 已确认的目标与约束

- 保留人工选择场地、编辑队列和定时执行的使用方式。
- 增加邀请制注册、应用登录和多用户数据隔离。
- 每位用户可以维护多个上游 Token。
- LLM 使用可配置的 OpenAI 兼容接口；环境变量提供服务级默认配置，用户也可在应用内配置自己的接口。
- 人工界面与 LLM 都能创建和修改预约计划；同一计划可以由任一入口继续调整。
- 所有计划由同一个预约执行器处理。
- 后端采用 Flask API、SQLite 和轻量后台 Worker；不引入 Redis、Celery 或多节点集群。
- 先在本地开发和验证，之后通过私有 Tailscale 网络访问；不开放公共互联网注册入口。
- Agent 不执行验证码或频控绕过。若上游要求人工验证，任务暂停并交给用户处理。

## 2. 系统边界

应用由三个逻辑部分组成：

1. **Vue 前端**：登录、邀请码注册、Token 管理、场地查询、人工队列编辑、Agent 对话、计划差异确认和任务状态。
2. **Flask API**：会话认证、用户与 Token 授权、计划服务、上游接口适配、任务提交和状态查询。
3. **SQLite 与 Worker**：SQLite 保存用户数据、计划版本和执行任务；单独的轻量 Worker 领取到期任务并调用预约服务。

当前目录只有前端构建产物，没有 Vue 源码或构建清单。实施前需要恢复前端源码或建立新的 Vue/Vite 源目录，并明确唯一维护版本。后端的可读源码位于打包目录内，另有一份完全重复的副本；实施前需要选定唯一源文件位置。

Flask 开发服务和前端开发服务可以分别运行。前端开发服务通过代理访问 Flask API；生产访问时由同源服务路由或 Tailscale 私有代理提供页面和 API。

## 3. 人工与 Agent 共用的预约计划

### 3.1 单一事实来源

系统不保存“人工队列”和“AI 队列”两份互不关联的数据。每份计划属于一个用户，可绑定一个 Token，并记录场馆、预约日期、预约类型和有序候选队列。队列继续表达两小时和一小时场次及各自的候选顺序，以保留现有优先级语义。

人工界面和 Agent 使用同一个 PlanService：

- 人工保存场地选择时，PlanService 创建新版本。
- Agent 先读取当前计划和经筛选的场地可用信息，再提交结构化修改。
- 修改支持追加、删除和替换；有明确替换指令时执行替换。意图含糊且会移除已有候选时，先显示差异并请求确认。
- 每个版本记录修改来源（manual 或 agent）、操作者、时间和变更摘要。
- 保存时检查预期版本号。若人工和 Agent 并发修改了旧版本，返回冲突并要求读取最新计划后重试，避免静默覆盖。

### 3.2 计划与执行快照

任务启动时固定引用一个计划版本，并将必要的队列内容复制为不可变任务快照。用户之后编辑计划会生成新版本，只影响尚未启动的任务；运行中的任务继续使用启动时的快照。

保存计划本身不会隐式发起下单。执行由用户手动触发，或由该计划明确启用的后端定时设置触发。浏览器关闭后，已持久化的定时任务仍由 Worker 管理；承载服务的本地机器需要保持运行且不休眠。

## 4. Agent 的职责与工具边界

Agent 负责把用户表达转为计划修改，不直接调用上游接口：

1. 根据当前登录用户选择的 Token ID 读取该用户现有计划。
2. 通过后端受限工具查询可预约信息，拿到场地、时间、可用状态和必要价格信息。
3. 生成结构化计划修改，展示被新增、删除或替换的队列项。
4. 按用户指令将修改提交给 PlanService；需确认的破坏性修改先取得确认。
5. 返回新计划版本和是否已经设置定时执行的状态。

Agent 工具不能读取原始 Token、支付密码、用户资料全量响应或任意上游响应。Agent 不能通过保存计划直接启动真实下单。

Agent 通过后端 LLM Provider Adapter 调用模型。首版协议采用支持工具调用的 OpenAI Chat Completions 兼容格式；支持其他协议时增加独立适配器，不把协议差异散落在 PlanService 或执行器中。

模型调用所需的 base URL、API key 和模型 ID 由后端解析。Agent 不能读取或改写这些配置。

## 5. 预约执行与任务调度

### 5.1 Worker

Flask API 将执行请求写入 SQLite 并返回任务 ID；Worker 异步执行，前端轮询或请求任务状态。建议状态为：

- scheduled
- queued
- running
- awaiting_human
- succeeded
- failed
- cancelled
- needs_attention

Worker 在领取任务时，通过事务将任务从 queued/scheduled 原子改为 running，并创建执行租约。启动时读取用户、Token ID 和计划快照，构造仅属于该任务的 CredentialContext 与 ApiClient Session。

默认允许不同 Token 的任务并行，单个 Token 同一时间最多执行一个任务；全局并发上限保持较小并可配置。手动运行与定时运行经过同一执行器和状态机。

### 5.2 失败与恢复

- 对查询类请求采用有限次数重试。
- 创建预约和发起支付等有副作用的步骤禁止盲目重试。
- Worker 重启后，未结束的任务先通过订单查询核对上游状态，再决定恢复或进入 needs_attention。
- 对同一计划版本的重复触发进行去重；计划、Token 和任务之间均校验 user_id。
- 上游以 HTTP 200 返回业务失败时，仍按 JSON 中的 success 和业务字段处理。

### 5.3 支付

现有流程包含 openPlatFormPayOrder。多用户版本按 Token 保存加密后的支付凭证；自动支付设置属于每个 Token 的显式选择，默认关闭。未启用时，成功创建预约后任务进入需要用户处理的状态。启用自动支付后，只能按照现有上游支付流程执行，并记录支付步骤结果，不能由 LLM 决定金额或直接取得支付密码。

## 6. 数据与隔离

建议的主要实体：

- **User**：唯一登录标识、密码哈希、角色、状态和创建时间。
- **Invitation**：邀请码哈希、有效期、使用者和使用时间；邀请码单次使用。
- **Credential**：user_id、用户可辨识的标签、加密 Token、加密支付密码、启用状态及最近验证时间。
- **UserLLMConfig**：user_id、接口 base URL、模型 ID、加密 API key、协议类型和更新时间。API key 只允许后端解密使用。
- **BookingPlan**：user_id、credential_id、日期、场馆、预约类型、队列、自动执行选项、当前版本号和更新时间。
- **PlanRevision**：计划 ID、版本号、来源、操作者、变更摘要和队列快照。
- **BookingJob**：user_id、credential_id、计划版本、执行来源、计划执行时间、状态、尝试次数、开始和结束时间及可公开给用户的错误摘要。
- **JobEvent**：任务状态变更和经脱敏的步骤信息。

所有数据库查询以已认证用户 ID 限定。即使知道其他用户的 ID、计划 ID 或任务 ID，也不能读取或修改其数据。后台执行任务时使用任务记录里的 owner ID 和 credential ID 做二次校验。

## 7. 认证与凭证保护

- 初始化管理员通过本地 CLI 创建，不开放默认管理员密码。
- 普通注册必须提交管理员生成的高熵、单次、可过期邀请码。
- 密码使用 Werkzeug 支持的 scrypt 哈希，不可逆存储。
- Token 和支付密码使用独立的 Fernet 加密；主密钥只放在本地环境变量或部署密钥文件中，不存入 SQLite、Git 或日志。此密钥与上游协议要求的 AES 参数完全分开。
- LLM API key 使用同一应用密钥管理机制加密保存，但与预约 Token、支付密码分字段管理。服务级环境变量中的 key 保留在进程环境，不复制到用户配置表。
- base URL 只接受明确配置的 HTTP(S) 地址；生产环境要求 HTTPS，并拒绝指向 loopback、link-local、云元数据和未授权内网地址的配置或重定向。管理员可以精确允许可信的 tailnet 模型服务地址；本机开发允许管理员配置 localhost 模型服务。
- 用户配置 API key 后，接口只返回“已配置”状态；前端不再读取保存的明文。用户可以替换或清除自己的配置。
- 应用使用可撤销的服务端会话；生产 Cookie 设置 HttpOnly、Secure 和 SameSite，并为状态变更请求启用 CSRF 防护。
- 本地与生产都保留应用登录；Tailscale 网络成员资格不自动等同于应用用户身份。

## 8. 上游接口与 req 抓包观察

抓包目录按参考资料使用，仅汇总字段名、接口顺序和业务状态，没有将原始值写入本规格。

观察到的主要接口包括：

- bookingByTime：返回 timeList、nodeList、conflictList、priceList 及预约开放时间等元数据。
- getPayPrice：返回 txamt 和 pricemap。
- createBookingBytime：成功响应可能带 orderno 和 txamt；捕获的 4 个响应中有 3 个 JSON success=false 和 1 个 success=true，HTTP 均为 200。
- openPlatFormPayOrder、payOrderForPhone、payOrderDetails：用于支付请求与订单状态核对。
- getPictureCheckFlag、getPictureCheckInfo 及图片资源请求：表明上游流程存在图片验证相关交互。

userAddress/getUserInfo 响应含身份标识、电话和用户名字段；payOrderDetails 含订单标识、联系方式、二维码及支付详情字段。服务端要对这些响应做最小化投影，不将完整响应传给 Agent 或写入普通日志。原始 req 抓包不纳入 Git；如实施时需要契约样本，应先生成不含凭证、个人数据和可重放值的脱敏 fixture。

验证相关步骤若要求用户操作，Worker 暂停为 awaiting_human 并提供清晰状态；不解题、不模拟用户操作、不绕过验证码或频率限制。

## 9. API 草案

- POST /api/auth/invitations/redeem：创建邀请码并注册。
- POST /api/auth/login、POST /api/auth/logout：登录和注销。
- GET/POST/DELETE /api/credentials：读取、添加和删除当前用户自己的 Token。
- GET/PUT/DELETE /api/llm/settings：读取状态、设置或清除当前用户自己的 LLM 接口；读取时仅返回 base URL、模型 ID、协议类型和 key 是否已配置。
- POST /api/llm/test：仅在用户主动点击“测试连接”时验证当前生效配置；日志不记录 API key 或完整请求头。
- GET/POST/PATCH /api/plans：读取、创建和修改当前用户的预约计划；修改携带 base_version。
- POST /api/plans/{id}/agent-edits：提交受限的结构化计划变更。
- POST /api/plans/{id}/jobs：立即执行或登记定时任务，创建任务时固定计划版本。
- GET /api/jobs、GET /api/jobs/{id}、POST /api/jobs/{id}/cancel：读取和取消当前用户的任务。
- GET /api/availability：通过指定 credential ID 查询并返回脱敏的场地信息。

除登录与邀请码兑换外，所有接口均需登录并进行对象所有权检查。禁止从客户端接收 Token 作为上游调用的临时参数；客户端只传 credential ID，由后端加载并解密。

## 10. 前后端体验

前端提供：

- 登录和邀请码注册。
- Token 标签、状态、验证结果和自动支付开关。
- 场地网格、两小时/一小时队列、人工排序和删除。
- Agent 修改预览、队列差异、版本历史和冲突提示。
- LLM 接口设置：base URL、API key、模型 ID；已保存的 key 只显示配置状态，可替换或清除。
- 定时执行设置、当前任务状态、执行步骤摘要和人工验证提示。

本地开发阶段前后端分别启动，Vite 代理 API；上线到 Tailscale 时使用同源 HTTPS 访问。CORS 不再允许任意来源，开发和生产来源分别明确配置。

## 11. LLM 接口配置

配置字段采用以下名称：

- LLM_BASE_URL：OpenAI 兼容 API 的根地址，通常包含 /v1，不填写完整的 chat/completions 路径。
- LLM_API_KEY：服务级默认 API key。
- LLM_MODEL：服务级默认模型 ID。
- LLM_PROTOCOL：首版固定为 openai-chat-completions。

优先级为：用户在应用内保存的配置覆盖环境变量；用户清除个人配置后恢复使用环境默认值。若既无用户配置也无环境默认值，Agent 功能显示“尚未配置”，不影响人工预约流程。

用户配置保存在所属用户的 UserLLMConfig 中。服务级默认配置由部署者管理。密钥只能由后端 Provider Adapter 使用；不能返回给浏览器、Agent prompt、任务事件或普通日志。连接测试仅由用户明确触发。

该设置用于 OpenAI 兼容的 Chat Completions 与工具调用。只有 base URL、key 和模型 ID 并不保证任意厂商 API 兼容；非兼容协议需后续增加专用 Provider Adapter。

## 12. Tailscale 接入

- 仅授权 tailnet 成员可通过私有 Tailscale Serve/ACL 访问；不启用面向所有互联网用户的 Funnel 或公开注册。
- Tailscale ACL 限制可访问的成员或组及服务端口。
- 应用登录和用户数据隔离继续生效；网络授权不能替代应用授权。
- 生产关闭 Flask debug，限制来源，Cookie 启用 Secure，并确认日志和 SQLite 备份不会对 tailnet 以外暴露。
- 本地开发阶段不要求安装或启用 Tailscale。

## 13. Git 与实施阶段

当前仓库已初始化在 main，但没有代码基线提交；现有应用文件仍未跟踪，且混有重复打包目录、Windows 二进制、日志和抓包文件。

本规格提交后，实施开始前先挑选可维护源码、创建项目级 .gitignore 并提交干净的源代码基线。凭证、个人 booking_plan.json、日志、req 抓包、Windows 可执行文件、打包压缩包和重复发布目录不进入源码基线。基线提交完成后，建立一个 feature/multitenant-booking worktree；所有实现阶段在该 worktree 内按垂直功能分批提交，完成后本地合并回 main，不需要配置远程。

实施阶段：

1. 源码与依赖清理：确定唯一后端源码、恢复或建立前端源码、补充 Conda test 依赖和启动说明。
2. 用户与凭证：邀请注册、登录会话、凭证加密、用户隔离。
3. LLM Provider Adapter：环境默认配置、用户配置覆盖、密钥加密和显式连接测试。
4. 统一计划：计划 CRUD、来源标记、版本历史、冲突保护、人工编辑和 Agent 结构化变更。
5. Worker：持久化任务、定时调度、并发上限、每 Token 锁、恢复与人工验证暂停。
6. 前端闭环：Token 管理、LLM 设置、计划编辑、Agent 差异确认和任务状态。
7. 本地安全验证：双用户隔离、凭证不出现在日志/Agent 上下文、模拟上游流程、重启恢复和重复执行防护。
8. Tailscale 私有接入：关闭 debug，配置 Serve/ACL，验证授权成员可访问且未授权成员不可访问。

## 14. 验收标准

- 邀请码只能使用一次且可过期；未登录访问业务接口被拒绝。
- 用户 A 不能读取或修改用户 B 的 Token、计划、订单摘要或任务。
- Token 和支付密码在 SQLite 中不可读；日志、Agent 输入和 API 错误不含原始凭证。
- 环境默认 LLM 配置和用户覆盖配置均可用；用户 key 只对其所属用户生效且不会通过 API、Agent 或日志明文返回。
- 没有 LLM 配置时，人工预约功能仍可用；连接测试只在用户主动操作后发起。
- 人工 UI 和 Agent 编辑会修改同一计划，修改均可追溯并产生版本。
- 对同一计划并发修改时能检测版本冲突；执行中的任务不会被编辑悄悄改变。
- 多个不同 Token 的任务可以按全局上限并行；同一 Token 不会重复并发下单。
- 执行器能处理 HTTP 200 下的业务失败，且不会盲目重放创建预约或支付步骤。
- 上游要求图片验证时任务进入 awaiting_human。
- 自动支付默认关闭，用户逐 Token 明确开启后才会调用支付接口。
- 未授权 tailnet 成员不能访问服务；授权成员仍需通过应用登录。
- 验证使用模拟上游或脱敏 fixture，不对真实预约和支付接口发起自动化测试。

## 15. 不在首版范围

- 公网匿名访问、开放自助注册、公开 Funnel。
- Redis/Celery、多节点调度或高可用集群。
- LLM 直接访问 Token、支付密码、任意 HTTP 客户端或数据库。
- 非 OpenAI Chat Completions 兼容协议的 Provider Adapter。
- 验证码识别/绕过、反复高速轮询或规避上游限额。
- 服务器休眠时仍保证自动任务运行；本地机器休眠期间 Worker 无法执行任务。
