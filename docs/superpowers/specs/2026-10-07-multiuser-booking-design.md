# 羽毛球预约系统：多用户与 Agent 计划设计

- 日期：2026-10-07
- 状态：加入长期提前预约与上游协议契约后的规格修订版，等待用户审阅
- 目标：在现有预约流程上构建本地开发的前后端分离多用户应用，后续仅向授权的 Tailscale 网络成员开放。

## 1. 已确认的目标与约束

- 保留人工选择场地、编辑预约计划和定时执行的使用方式。
- 增加邀请制注册、应用登录和多用户数据隔离。
- 每位用户可以维护多个上游 Token；不同 Credential 的任务可并行，同一 Credential 同时最多执行一个任务。
- LLM 使用 OpenAI 兼容接口。环境变量提供一套服务级默认 Provider 配置；用户也可在应用内填写自己完整的一套 Provider 配置。
- 人工界面与 Agent 都能创建和修改同一份预约计划；同一计划可以由任一入口继续调整。
- BookingPlan 只描述预约内容。所有立即执行和定时执行都由 BookingJob 管理。
- 每个 BookingJob 创建时固定引用一个 PlanRevision，并保存不可变执行快照。之后修改计划不会改变已创建任务。
- 所有开放时间和预约时间均按服务端配置的业务时区计算。每天业务时区 00:00 起可查询当天、明天、后天的场地；默认目标日是后天，真实预约操作最早在目标日对应的 T-2 日 07:30 开放。
- 用户可以在目标日进入查询窗口前任意天创建 BookingJob；任务冻结的是语义预约意图，不冻结尚不可查询的实时 availability 或数组坐标。T-2 日 00:00 自动查询并准备，T-2 日正式开放时再实时查询、重新解析并尝试。
- 上游接口契约优先根据本地 `req/` 抓包解密后的脱敏结构及同目录官方前端代码确定；已有 Python 实现、README、注释和旧规格仅作次级参考，不能覆盖抓包证据。
- `req/` 含 Token 与个人数据，只允许本机内存分析；不得把原始抓包、解密后的真实请求/响应或真实个人字段写入 Git、日志、Agent 上下文或普通 API 响应。契约测试使用人工生成的脱敏 fixture。
- 00:00 至 07:30 只查询和准备计划，不调用真实预约副作用接口。场地状态查询开放不代表真实预约已经开放。
- Agent 只生成、预览和保存预约计划修改；不能创建 BookingJob、启动真实预约、开启自动支付或控制其他敏感执行设置。
- 后端采用 Flask API、SQLite 和轻量后台 Worker；不引入 Redis、Celery、PostgreSQL、微服务或多节点集群。
- 先在本地开发和验证，之后通过私有 Tailscale 网络访问；不开放公共互联网注册入口。
- Agent 不执行验证码或频控绕过。若上游要求人工验证，任务暂停并交给用户处理。
- 自动支付默认关闭；实际金额、支付上限或上游状态不满足安全条件时，任务暂停等待用户处理。

## 2. 系统边界

应用由三个逻辑部分组成：

1. **Vue 前端**：登录、邀请码注册、Credential 管理、场地查询、人工计划编辑、Agent 计划修改预览、任务调度、支付确认和任务状态。
2. **Flask API**：服务端会话认证、用户与 Credential 授权、计划和版本服务、LLM Provider Adapter、上游接口适配、BookingJob 创建与状态查询。
3. **SQLite 与 Worker**：SQLite 保存用户数据、计划版本、任务队列、执行租约、步骤状态和外部订单记录；轻量 Worker 原子领取到期任务并调用预约服务。

Flask 后端提供唯一的 BookingWindowPolicy、AvailabilityService、PlanService、UpstreamContractAdapter、CandidateResolver 和 BookingExecutionService。BookingWindowPolicy 集中计算查询/预约窗口；AvailabilityService 统一调用 bookingByTime、归一化状态、缓存和节流；CandidateResolver 只用本次最新响应把语义候选解析成临时坐标；BookingExecutionService 是唯一可调用真实预约副作用接口的服务。Vue、Agent、API 路由和 Worker 不得复制时间、冲突码或坐标规则，也不得绕过领域服务。

API 和 Worker 可以在同一台本地机器运行，逻辑上分离即可。Worker 可作为独立命令或受控后台线程运行；同一时刻只允许一个进程初始化数据库迁移。SQLite 是唯一持久化队列和状态来源，不另建内存任务队列作为事实来源。

当前目录只有前端构建产物，没有 Vue 源码或构建清单。实施前需要恢复前端源码或建立新的 Vue/Vite 源目录，并明确唯一维护版本。后端的可读源码位于打包目录内，另有一份重复副本；实施前需要选定唯一源文件位置。

Flask 开发服务和前端开发服务可以分别运行。前端开发服务通过代理访问 Flask API；生产访问时由同源服务路由或 Tailscale 私有代理提供页面和 API。公网入口、反向代理与应用的信任边界必须显式配置。

## 3. 人工与 Agent 共用的预约计划

### 3.1 单一事实来源与版本

系统不保存“人工队列”和“AI 队列”两份互不关联的数据。每份 BookingPlan 属于一个用户，只描述预约业务内容，例如目标日期、场馆、预约类型、时间段、场地优先级和有序候选队列。队列继续表达一小时/两小时场次及各自候选顺序，以保留现有优先级语义。目标日期可以远于当前三日查询窗口；此时计划只保存语义意图并标记为 unresolved_future。

计划中的每个场地候选使用结构化 BookingCandidate，而不是把“7号场19:00-21:00”或 `5-6` 一类展示文本/数组坐标作为业务主键。Schema 至少包含：

```json
{
  "slot_key": "内部语义键",
  "target_date": "YYYY-MM-DD",
  "upstream_venue_nodeid": "场馆 nodeid",
  "upstream_court_nodeid": "nodeList 中场地 nodeid",
  "venue_name_snapshot": "仅展示",
  "court_name_snapshot": "仅展示",
  "start_time_local": "HH:MM",
  "duration_minutes": 120,
  "session_type": "two_hour",
  "priority": 1
}
```

`slot_key` 是由目标日期、上游场馆/场地 nodeid、开始时间、时长和语义预约类型规范化后生成的内部 SlotKey；它不是上游 `slot_id`。PlanRevision 和 BookingJob 绝不保存 `courtIndex`、`timeIndex`、`coordinatesList` 或旧数组下标。端点没有稳定 slot_id 时不得虚构。结束时间由开始时间与时长推导；展示名称快照不能作为身份匹配依据。候选在同一 PlanRevision 内使用同一目标日期；`priority` 在该计划候选队列内唯一。

计划还必须保存用户明确选择的 fallback_policy：默认 `ordered_explicit_candidates_only`，只尝试用户列出的候选；可选 `any_available_court_same_venue_time_duration`，仅当用户主动授权时，才允许在同一场馆、同一目标日期/开始时间/时长内扩展到最新 `nodeList` 中其他正常场地。不得按场地名称或旧坐标猜测，也不得越出该授权范围。若用户授权同场馆任意可用场地，运行时只在当前 nodeList 中按上游返回顺序枚举同一时间/时长下的正常候选，并在任务摘要中说明实际尝试的场地；该临时顺序不写回 PlanRevision。实时 occupancy/window 状态和坐标不写入 PlanRevision。

Plan 不包含 Credential 选择、自动支付开关、支付上限、Worker 状态或执行时间。用户在创建 BookingJob 时选择自己的执行 Credential；任务调度也由 BookingJob 管理。因此一个用户可以将同一份计划用于不同 Credential，也可以修改计划而不隐式提交任务。保存计划前如需验证可用性，用户在 UI 选择一个仅供查询的 validation Credential；PlanService 校验它属于当前用户，但不把它写入 BookingPlan/PlanRevision，也不将它自动用作后续 Job 的执行 Credential。

人工界面和 Agent 使用同一个 PlanService：

- 人工保存场地和队列选择时，PlanService 创建新的 PlanRevision。
- Agent 读取当前计划和经筛选的场地可用信息后，生成结构化修改；只有用户明确要求保存时才提交给 PlanService。
- 修改支持追加、删除和替换；Agent 必须展示会移除或替换的候选项。意图含糊且会造成破坏性修改时，先请求用户确认。
- 每个版本记录来源（manual 或 agent）、操作者、时间、变更摘要和不可变计划内容。
- 更新必须携带期望的当前版本号。服务在一个 SQLite 写事务中检查并推进版本；版本不匹配返回 409，要求重新读取后再编辑。
- PlanRevision 只追加，不允许更新或删除。BookingPlan 的当前版本指针通过比较并交换方式更新；不能覆盖历史版本。
- PlanService 始终校验语义字段、时长与队列结构。目标日尚未到 T-2 查询窗口时，不调用上游、不要求 validation Credential；正常保存 revision，并将候选标记为 unresolved_future。查询窗口内若已有当前有效响应，已确认的活动、社团、已预订及其他硬性不可预约候选不能新增或保存在 revision；没有可用实时响应时可以保存语义意图，但不得把未知状态伪装成可用，BookingJob 仍须等 Worker 解析。

### 3.2 计划与 BookingJob 执行快照

执行时间不属于 BookingPlan。立即执行与未来定时执行统一创建 BookingJob，使用同一张持久化任务表和同一个 Worker 队列：

- 创建任务必须由已登录用户通过明确的人工作用触发，例如点击“立即执行”或“保存定时任务”。Agent 工具没有创建 BookingJob 的能力。
- 创建请求必须明确指定当前用户的 plan、PlanRevision、Credential 和执行策略。若客户端省略 revision，只能由服务端在同一个事务内读取并固定当时的当前 revision，不能留待 Worker 开始时再读取。用户可以在查询窗口前任意天创建任务，不要求此时有 availability。
- BookingJob 创建成功时，固定 plan_revision_id，并把 revision 中的完整语义预约意图复制到不可变 `execution_snapshot_json`，同时保存规范化快照哈希。快照固定 BOOKING_TIMEZONE、BookingWindowPolicy 版本、UpstreamContractAdapter 版本、目标预约日期、候选顺序、用户授权的 fallback_policy 及预约开放基准；不含实时 nodeList/timeList、availability、价格或上游坐标。
- `scheduled_for_utc` 是用户授权的正式预约执行时刻；official_open 模式由 Policy 求“now 之后、目标日 T-2 已开放且落在某个当前每日 bookingstarttime/bookingendtime 写窗口内、且早于场次开始”的最早时刻。默认后天任务通常等于 T-2 日 bookingstarttime（当前观察值 07:30）；目标开放已过去而用户选择今天/明天剩余场地时，若当前每日窗口已开则可立即执行，否则等待下一个每日开放时刻。初始 `next_action_at_utc=max(now_utc, query_open_at_utc)`。二者分开存储，前者在任务创建后不可改，后者随 phase 推进而更新。
- 任务初始 `status=queued`、`phase=waiting_query_window`、`resolution_status=unresolved_future`。到查询窗口由同一 Worker 队列领取，执行只读准备后追加 ResolutionSnapshot；准备完成后转为 `phase=waiting_booking_open` 并释放 Credential 执行锁。开放时重新领取并使用新的实时响应解析，不能复用准备阶段坐标。
- 快照至少包含预约计划内容、revision 编号、credential_id、创建时的 Credential 执行策略版本、支付上限、创建方式和预约执行时间。不得包含解密后的 Token、支付密码、LLM Key 或其他明文秘密。
- 快照还要固定创建任务时是否允许自动支付、支付上限数值和币种；这些值只记录授权边界，不替代执行时对 Credential 当前状态和策略的重新校验。
- 上游请求还需要 Credential 账户的 reservationPerson、childrennum、accompanyPerson/followList 等执行资料。BookingJob 必须同时固定同一 user_id/Credential 下由用户确认的 CredentialBookingProfileRevision ID/hash；只在该 profile revision 中加密保存个人字段，不把明文复制进计划、Agent 上下文或普通 API。没有有效 profile 时拒绝创建可执行 Job，不能在开放时静默改用最新用户资料。
- Credential 的启用、删除状态及当前安全策略在 Worker 执行前仍需重新校验。安全策略变得更严格时立即生效；策略变得更宽松时，不自动扩大已有任务快照中的授权范围。
- 用户修改计划只产生新 PlanRevision，不修改任何已创建任务。用户要用新计划执行，必须显式创建一个新的 BookingJob。
- 任务创建后的执行时间和快照不可原地改写。需要改变时间、计划版本或 Credential 时，取消原任务并创建新任务。
- 立即任务、普通定时任务和长期提前预约任务均使用同一 BookingJob 表；Worker 按可变 `next_action_at_utc` 领取到期阶段，不建立第二套调度表或内存事实队列。`scheduled_for_utc` 与 `next_action_at_utc` 含义不同。

## 4. Agent 的职责与工具边界

Agent 负责把用户表达转为预约计划修改，不直接创建或执行预约：

1. 在当前登录用户范围内读取计划及必要的版本信息。
2. 查询窗口未开放时只读取 BookingPlan 和 BookingWindowPolicy，不能调用 bookingByTime，也不能自行估算未来 availability。查询窗口开放后才可通过用户选定的 Credential 查询；服务端只返回场馆、时间、硬排除原因和必要价格等语义字段。
3. 生成符合固定 Schema 的计划差异，说明新增、删除、替换的候选项。
4. 用户明确要求保存时，通过 PlanService 写入新 PlanRevision；遇到版本冲突必须重新读取并重新生成差异，不能静默覆盖。
5. 返回保存后的计划版本。Agent 不能创建、调度、取消或恢复 BookingJob。

Agent 可以理解任意未来目标日期并创建/修改语义候选；目标日未到 T-2 时，界面和 Agent 必须显示 unresolved_future，而不是伪造场地状态。T-2 查询窗口开启后，Agent 可查看当天、明天、后天的归一化状态并调整计划。Agent 不读取原始 conflictList、nodeList/timeList 下标、坐标字符串或原始 HTTP JSON，也不解释上游冲突代码。即使用户提前确认 BookingJob，Agent 也不能创建任务；必须由用户通过人工作用明确确认后创建。00:00 至正式预约开放期间只有查询、解析和 PlanService 写入能力，没有真实预约副作用能力。

Agent 的工具面只允许计划读取、可用信息查询和计划修改。它不能：

- 调用真实的 createBooking、支付或其他副作用上游接口。
- 创建立即任务或定时任务，或直接调用 Worker。
- 开启或修改自动支付、支付上限、Credential 启用/删除状态、并发策略、Provider 配置、会话、邀请码或其他敏感设置。
- 读取原始 Token、支付凭证、用户资料全量响应、原始 HTTP 响应或完整订单支付详情。
- 提供任意 URL、任意 HTTP 工具、SQL、shell 或数据库访问能力。
- 通过模型返回的 user_id、credential_id 或 plan_id 越权访问资源；所有工具调用从当前服务端会话取得 user_id，并在数据库查询中绑定该 user_id。

Agent 通过后端 LLM Provider Adapter 调用模型。首版协议采用 OpenAI Chat Completions 兼容格式和受限工具调用；工具参数经过 Schema 校验和业务权限校验。非兼容协议需增加独立适配器，不能把协议差异散落在 PlanService 或执行器中。来自上游、用户文档或模型的文本一律作为不可信数据，不得覆盖系统工具权限。

Agent Runtime 只注入 PlanService 与只读 AvailabilityService 等必要接口，不注入 JobService、支付服务、Credential 设置服务或任意 HTTP 客户端。Agent 工具表中不存在创建/取消/恢复任务和支付授权工具；即使模型输出相应字段，也会因工具 Schema 不接受而拒绝。

## 5. 预约执行与任务调度

### 5.1 BookingWindowPolicy：查询窗口与真实预约窗口

服务端统一配置业务时区 BOOKING_TIMEZONE，默认 Asia/Shanghai；必须是有效 IANA 时区。前端从服务端读取该配置，API、PlanService、AvailabilityService、BookingJob 创建服务和 Worker 使用同一 BookingWindowPolicy 与可注入时钟，禁止用浏览器时区、操作系统本地时区或分别散落的常量计算开放时间。

对当前业务日期 D 和语义目标预约日期 T，先按本地日历做日期运算，再在 BOOKING_TIMEZONE 中构造本地时刻并转换为 UTC：

- 默认推荐目标日为 D+2，即“后天/第三天”；00:00 起的常规查询窗口为 D、D+1、D+2。用户可以在更早时刻选择任意未来 T 并保存预约意图，但在 T-2 日 00:00 前不得调用上游查询。
- 已知查询开放策略是 T-2 日 00:00；上游 `bookingByTime` 响应的 `bookingstartdate`/`bookingenddate` 是当前实际可查询日期范围，Worker 必须确认 T 位于该范围内。实测返回三日范围与默认策略一致；范围长度、日期格式或边界与已验证契约不一致时暂停为 contract_drift。
- 已知预约开放基准是 T-2 日的 `bookingstarttime`，本地抓包观察值为 07:30；`bookingendtime` 是响应给出的预约时段截止时间。创建远期任务时用已验证的 07:30 计算暂定 scheduled_for_utc；到查询窗口后以当前 `bookingstarttime`/`bookingendtime` 复核。响应值不符合当前 Adapter 契约时不得自动挪动任务时间或发送副作用，必须暂停并报告 contract_drift。
- 例：星期一 00:00 后可查询星期一、星期二、星期三；预约星期日的 query_open_at 为星期五 00:00，当前抓包中的 bookingstarttime 为星期五 07:30。目标日是 T-2 天计算的结果，不从“第三天”字样推算偏移。
- `can_query(T)` 要求现在不早于 T-2 日 00:00、目标日期未过期，且上游响应实际覆盖 T。未到查询窗口时返回 query_not_open，不调用 `bookingByTime`。不能查询未来任意日期来提前探测上游场地。
- `can_book(T, slot)` 要求目标日当前受上游窗口支持、当前时刻不早于 T-2 的已验证 `bookingstarttime`，并且当前业务日期本地时刻落在当日 bookingstarttime 与 bookingendtime 之间。因此即使今天/明天的目标日期早已在 T-2 开放，当前每天 bookingstarttime 前仍不能创建预约。所选场次尚未开始，且实时 AvailabilityService 与 CandidateResolver 确认候选满足上游限制。已确认的 current response 是最终执行依据；`isNew` 原样保留，只能按有契约 fixture 覆盖的规则解释，不能单独放宽预约门禁。
- 今天或明天的剩余场地不被无依据地禁止：若上游当前响应覆盖目标日、场次未过时且实时状态允许，用户可明确选择并创建任务。D+2 只是默认目标日。
- BookingWindowPolicy 返回值至少包括 business_timezone、business_date、default_target_date、可查询日期、target_date、query_open_at_utc、target_booking_open_at_utc、current_daily_booking_open_at_utc、current_daily_booking_close_at_utc、window_status、can_query、can_book_by_time、按 action 计算的 can_mutate_upstream、contract_status 和 reason_code。状态至少区分 query_not_open、query_open_booking_not_open、booking_open、daily_write_window_closed、target_expired、outside_supported_window 和 contract_drift。Job 固定 policy/contract 版本；策略升级不得静默重解释已有任务。

T-2 日 00:00 到上游 `bookingstarttime` 之间允许只读查询、语义解析和计划编辑，禁止 `createBookingBytime`、支付单创建、支付或任何其他上游副作用。即使目标日 T-2 已在过去，创建预约仍须检查当前业务日的 bookingstarttime/bookingendtime。支付也不得早于当日 bookingstarttime，但 bookingendtime 是预约时段上限；没有支付端点证据时不把它套用为支付截止时间，支付还须通过已确认订单状态及其自身有效期检查。所有副作用只能由 BookingExecutionService 暴露，并在发送前再次检查 BookingWindowPolicy 和当前响应；时间字段不匹配、响应结构漂移或门禁不满足时 fail closed。

### 5.2 BookingJob、统一队列与状态机

所有任务放入 SQLite 的 BookingJob 表。Worker 按 `next_action_at_utc <= now_utc` 领取 queued 行；已过期租约的 running 任务和需要核对的 cancel_requested 任务也由同一 Worker 领取，但只能走恢复/取消核对流程。

创建 BookingJob 时服务端固定 PlanRevision、语义快照、Credential 和执行时刻。execution_mode=official_open 表示由 Policy 计算最早有效预约时刻，并将初始 next_action_at_utc 设为 max(now_utc, T-2 00:00)；允许在查询窗口前任意天创建。默认后天任务的 scheduled_for_utc 为 T-2 日 bookingstarttime（当前基准 07:30）。execution_mode=at 必须显式提供 scheduled_for_utc，且不早于目标日预约开放时刻、落入该时刻对应的每日写窗口，并早于候选场次开始时间。execution_mode=now 只允许在当下 can_book_by_time 为 true 时使用。无可用的每日写窗口、过早、过晚或过期请求返回 422 和明确边界，绝不静默改写用户显式指定的时间。省略执行时间的请求按 official_open 处理，不得把远期意图当成“立即执行”。

Worker phase 与 BookingJob status 分开保存。phase 至少包括 waiting_query_window、preparing、waiting_booking_open、resolving_at_open、getting_price、creating_booking、processing_payment 和 recovering；人工作用仍由 status=awaiting_human 表示。远期任务初始为 status=queued、phase=waiting_query_window、resolution_status=unresolved_future。查询窗口到达后执行一次只读准备并追加 ResolutionSnapshot；准备完成后设为 queued/waiting_booking_open 并释放租约和 Credential 锁。正式开放时重新领取、查询最新 bookingByTime 并解析；若 Worker 首次运行时预约窗口已开，则该次最新查询直接作为最终查询，无须为形式重复调用。

BookingJob 状态：

- queued：已持久化，等待执行时间到达或等待 Worker 领取。
- running：Worker 持有有效租约，正在执行或恢复核对。
- awaiting_human：已暂停并等待用户完成验证或确认具体金额等人工作用。
- cancel_requested：用户要求停止；Worker 需在安全边界处理并核对已经发出的上游操作。
- succeeded：预约流程已按要求完成，最终状态已确认。
- failed：已确认失败，且不存在需要继续核对的未知副作用。
- cancelled：本地执行器已停止继续执行。此状态不代表上游订单已取消或退款。
- needs_attention：上游副作用或订单状态无法安全确认，自动执行停止，需人工处理。

主要状态转换：

- queued -> running 或 cancelled
- running -> queued（只读准备完成、等待下一阶段）、awaiting_human、succeeded、failed、cancel_requested 或 needs_attention
- awaiting_human -> queued 或 cancel_requested
- cancel_requested -> cancelled 或 needs_attention
- needs_attention -> queued 仅限用户恢复操作已满足恢复前置条件且上游状态已核对；否则保持暂停。
- succeeded、failed 和 cancelled 为终态。若上游仍有未结订单，终态任务仍须展示独立的 ExternalOrder 状态，不能把本地终态解释为上游终态。

每次状态转换都追加带时间和操作者的 JobEvent。API 返回可供用户理解的错误摘要和状态，不返回堆栈、凭证或完整上游响应。

### 5.3 Worker 租约与 Credential 执行锁

Worker 领取任务和获取 Credential 锁必须在同一个 SQLite BEGIN IMMEDIATE 事务中完成：

- 在同一队列中选择到期的 queued 任务、租约已过期的 running 任务，以及需核对的 cancel_requested 任务；后两类只能恢复或取消核对，不能直接开始新的预约副作用。检查当前用户和 Credential 关系仍有效。
- 对每个任务写入持久化 lease：lease_owner、lease_expires_at_utc、lease_heartbeat_at_utc 和递增的 lease_epoch。
- 同一 Credential 同时只能关联一个执行任务；Credential 锁有独立持久化行和到期时间，不能只依赖 Python 进程内的 Mutex。
- 获取锁失败时任务保持 queued，稍后重试领取；不得让任务先进入 running 再无锁执行。
- 网络调用期间不持有 SQLite 写事务。Worker 定期续租，并在写入 JobStep、订单或任务状态前校验 lease_owner 和 lease_epoch。
- 网络超时必须短于租约时长，Worker 需在每个副作用请求前检查租约仍有效。接管过期的 running 任务时，原子递增 lease_epoch、标记 recovery_required，并先执行恢复核对。
- 如果旧 Worker 的网络副作用已在途或结果不明，数据库 fencing 不能撤销上游请求；新 Worker 必须按 JobStep 和 ExternalOrder 查询上游状态，不能因为旧租约过期就重发请求。
- 没有未决副作用的 awaiting_human 任务可释放执行锁；有未决外部订单或支付操作的任务保留 Credential 锁预留，直到上游状态核实或人工处理，防止同一 Credential 被另一任务误用。
- 删除、停用 Credential 时，禁止领取新任务。排队任务被安全取消；运行中任务进入 cancel_requested 并在安全边界完成核对。

全局 Worker 并发上限保持较小且可配置。不同 Credential 可并行；同一 Credential 串行。并发上限不由 Agent 或普通用户计划修改。

### 5.4 JobStep、外部副作用与崩溃恢复

每个 BookingJob 有多条持久化 JobStep，例如准备阶段 bookingByTime、开放时 bookingByTime、候选解析、getPayPrice、createBookingBytime、订单查询、支付下单和支付状态核验。JobStep 至少记录步骤类型、序号、状态、尝试次数、开始/结束时间、稳定的本地 operation_id、经脱敏的结果摘要和关联 ExternalOrder。每次准备/开放阶段解析追加一条 ResolutionSnapshot，记录 contract version、查询时间、候选 SlotKey 的解析结果及响应指纹；准备阶段结果标记 write_eligible=false，不得作为开放时下单输入。

JobStep 状态包括 prepared、in_progress、succeeded、failed_definitive、unknown 和 skipped：

- bookingByTime 和经契约确认只读的 getPayPrice 查询可以按有限次数和全局退避策略重试；重试不得更换 Credential 来规避限流。
- 每次 createBooking、创建支付单或支付等副作用操作，必须先在事务中持久化 in_progress 的 JobStep 和本地 operation_id，提交后才发送网络请求。
- 如果上游支持幂等键，使用稳定的 operation_id；未确认上游支持时，不能假设重复请求幂等。
- 成功响应、业务失败响应和关联订单 ID 必须在收到后尽快持久化。HTTP 200 本身不是成功依据，须按 endpoint-specific contract 检查 JSON success、message 和必要的 resultData 字段；成功 message 可能是 CORE10008 等代码，不能假设所有接口都返回“成功”。
- Worker 重启或租约过期后，所有未完成副作用先标记/视为 unknown 并恢复查询。只有上游明确证明副作用已成功或明确证明未发生，才更新 JobStep。
- 如果上游能证明成功，恢复本地状态而不重发；如果能证明未发生且接口契约允许安全重试，才可受限重试；无法查询、查询结果不完整或状态仍有歧义时转为 needs_attention。
- 当前抓包确认 createBookingBytime 返回 success=false、message 为“每人每天最多预约1次”时，这是 Credential/用户每日额度的终止性业务失败，不能换场地后继续。只有 Adapter 中逐条登记、明确证明“本次没有订单且仅该候选不可用”的错误才允许尝试快照中的下一项；超时、断连、成功字段与订单字段冲突或未登记 message 一律先对账，不能重发或换候选。
- JobStep 和 ExternalOrder 不保存完整 HTTP 请求/响应、Cookie、Token、支付密码、二维码或未经筛选的个人资料。

### 5.5 可用性归一化、节流与执行前核验

AvailabilityService 是所有人工页面、Agent、PlanService 和 Worker 获取场地状态的唯一入口。返回项采用语义 BookingCandidate/SlotKey、fetched_at_utc、occupancy_status、window_status、can_query、can_select_plan、can_book 和 reason_code。占用与时间窗口分开表达；正常候选在 00:00 查询后、正式开放前显示“可准备，预约尚未开放”。查询窗口前返回 unresolved_future，不调用上游。

- 00:00 后可以显示当天、明天、后天各场地和时间段的正常候选、已预订、体育课、体训队、艺术团、项目培训、工会活动、其他活动及其他硬性不可预约项。活动/社团等确认占用是硬排除项，UI 置灰，Agent Schema 拒绝新增，PlanService 在已知当前结果时再次拒绝。
- CandidateResolver 只使用当前一次响应：按候选 upstream_court_nodeid 在 nodeList[].nodeid 中精确找 courtIndex；按期望开始时间在 timeList[].time 中精确找 timeIndex；随后按官方协议生成 courtIndex-timeIndex。不得按名称、上次坐标或显示顺序猜测。重复 nodeid/时间值、响应数组长度不一致、未知冲突格式/代码或字段类型变化属于 contract_drift，任务暂停。
- 一小时候选解析为一个 timeList 项；两小时候选必须解析成连续、相邻且实际时间间隔符合已验证槽长的两个 timeList 项，再为同一场地生成两条坐标。发现时间缺口、非连续槽或时长不匹配时，该候选不可提交。每次提交前检查选择数量满足 mintimeselect/maxtimeselect，不同场地下标数不超过 maxAppointmentNodeNum；这些值按当前响应和契约解析，不写死为样例值。
- conflictList 的状态解释按第 8 节版本化契约。活动、已预订和通用不可预订一律 can_select_plan=false、can_book=false；未知冲突不当成正常候选。timeList[].status 保留原值，但已观察的官方前端没有用它判断网格可用性，因此不得沿用旧 Python 代码将“1”自行解释成硬占用；未来如要解释，必须有新抓包/官方代码和 fixture 证据。
- 查询窗口外 PlanService 只做语义校验并允许保存 unresolved_future；窗口内若拥有当前响应，确认硬排除的候选不能新增。未拿到响应时可保存语义意图但必须标示未解析，不能返回 can_book=true。人工临时可用性视图可复用按 user、Credential、场馆、日期隔离的语义缓存，初始 TTL 为 1000ms（与本地成功日志实测最短约 668ms 的 bookingByTime 请求间隔相比取较保守值）；不缓存 Token、个人字段或可重放请求。
- Worker 在 T-2 00:00 准备阶段调用 bookingByTime，校验响应结构和目标日期范围，解析用户明确候选并追加 write_eligible=false 的 ResolutionSnapshot，然后等待预约开放。它不能以准备快照发送 createBooking。
- 到 scheduled_for_utc/已验证 bookingstarttime，Worker 必须再次绕过缓存调用 bookingByTime，重新检查 BookingWindowPolicy、响应开放字段、conflictList、nodeList、timeList 和每个 SlotKey，再按冻结 priority 尝试。候选变成硬排除时记录并尝试下一个已授权候选；未知状态安全重试查询，仍未知转 needs_attention。目标日过期或场次已开始时确定失败。
- 每个候选的开放时执行链为最新 bookingByTime -> getPayPrice -> createBookingBytime。getPayPrice 使用这次响应中的 nodeList/timeList 和新生成 coordinatesList；不插入任意等待，不使用准备阶段价格或坐标。报价失败只有在已登记为候选局部且无副作用时才可尝试下一候选；用户/每日额度类失败是终止性业务错误。
- UpstreamRequestGate 持久化于 SQLite，所有 API、Worker 和 Credential 共用。根据本地成功日志，bookingByTime 曾有业务成功的 HTTP 200 调用，观测到的最短同端点启动间隔约 668ms，未见 HTTP 429 或 Retry-After；因此初始全局最小间隔设为可配置的 1000ms，而不是把观测值当上游保证。后续只能依据脱敏成功日志、上游限制或 Retry-After 调整。bookingByTime 同时最多一个在途请求；查询缓存初始 TTL 同为 1000ms。最终执行查询始终绕过缓存。
- gate 按上游端点共享，不因换 Token、Credential、Agent 或 Worker 获得独立额度；429/503、Retry-After 或明确上游退避信号设置跨 Credential 的冷却。开放时任务按 SQLite 队列与 gate 顺序执行；不并行扇出、不以高频重试追赶。getPayPrice 与 createBookingBytime 之间不加人为固定延迟，但必须通过同一全局 gate、端点在途锁和服务级退避。
- 查询类超时按有限次数（初始最多 3 次）指数退避并服从 Retry-After；任何副作用超时/断连先对账，不能重放。Agent 不拥有独立 HTTP 客户端。

### 5.6 awaiting_human、恢复与取消

暂停时保存明确的人工作用原因、关联 JobStep/ExternalOrder、提示内容和可执行的下一步。前端不能只显示笼统的“暂停”。

- 图片验证等需要用户操作的情况进入 awaiting_human。用户按上游允许的正规方式完成后，点击恢复；恢复 API 只记录人工作用，不接收自动破解材料或未经定义的上游凭证。
- 价格变化时，显示服务器重新查询到的金额、币种、原报价、支付上限和关联订单，要求用户对这个确定金额进行一次性确认。
- 普通恢复操作只表示用户已完成页面提示或要求继续核对，不构成付款授权；价格变化或自动支付关闭时，必须另行产生经过校验的一次性 JobApproval。
- 用户恢复后，Worker 先重新检查租约、Credential 状态、订单状态、当前价格和支付上限，再继续；不得从暂停前的网络调用位置盲目续跑。
- 上游订单或支付状态不确定时，普通“确认”不能代替对账。必须先有权威查询结果；无法取得时进入 needs_attention，不得重复创建预约单或支付单。
- POST /api/jobs/{id}/cancel 对 queued 任务可直接标为本地 cancelled；对 running/awaiting_human 任务只产生 cancel_requested。Worker 停止后续副作用并查询已产生的订单。
- cancelled 仅表示本地不再继续执行。只有上游明确支持且用户明确发起单独订单取消流程时，才记录上游取消结果；不得声称取消 Job 已取消订单、退款或支付。

### 5.7 支付与自动支付门禁

自动支付是 Credential 级人工作用设置，默认关闭；计划和 Agent 均不能开启或修改它。支付上限以最小货币单位整数存储，禁止使用浮点数。

- 每次 createBookingBytime 前将最新 getPayPrice 的 txamt 原始字符串及规范化金额写入 JobStep；实际金额来自 createBookingBytime 成功结果或权威订单查询。当前 req 未显示上游返回 currency 字段，因此币种必须来自单独验证过的部署级 BOOKING_CURRENCY 契约配置，不能伪称为上游响应字段；未验证币种或 txamt 格式时禁止自动支付。
- BOOKING_CURRENCY 是本应用部署配置，不是上游 JSON 字段；必须由维护者根据官方收费单位确认。配置缺失时仍可查询和准备计划，但不得自动支付或对金额作币种猜测。
- 对实际金额、部署级币种、当前 Credential 支付策略和上游订单号 orderno 做完整校验。金额以最小货币单位整数比较；txamt 缺失、格式异常、币种未配置、超过有效上限、价格相较本次报价变化或订单状态未知时进入 awaiting_human/needs_attention。
- 自动支付只有在 BookingJob 快照创建时记录为允许、当前 Credential 仍启用自动支付、订单状态已确认、金额不超过任务快照上限和当前 Credential 上限，并且价格未发生需用户确认的变化时才可执行。
- 人工确认价格变化时，只能通过服务端记录的一次性 JobApproval 授权指定的已知订单与精确金额；审批记录不可重复使用，且仍不得超过当前 Credential 支付上限。调整支付上限必须由用户在 Credential 设置中单独完成，Agent 不可代为调整。
- 调高 Credential 支付上限不会扩大已有任务快照中的自动支付授权。若已知订单金额高于快照上限但不高于用户后来设置的当前上限，只能经一次性人工 JobApproval 继续，不得转为自动支付。
- 自动支付关闭时，Worker 不得支付；用户如需针对某个已创建订单进行一次性支付，必须通过单独、明确的人工作用确认，并经过相同金额和订单状态校验。
- 支付及其他上游写操作也必须经过 BookingWindowPolicy 的当前响应 bookingstarttime 写操作门禁（当前已验证值为 07:30）；开放前的人工确认只保存为待处理授权，不得提前向上游提交。
- 支付调用前先持久化 JobStep/ExternalOrder 状态。崩溃后必须查询订单和支付状态；支付状态不确定时禁止再次支付，转为 needs_attention。
- 不在首版中自动支付超出用户当前支付上限的金额，不自动处理退款或不确定的付款结果。

## 6. 数据与隔离

主要实体与约束：

- **User**：唯一登录标识、密码哈希、角色、状态和 UTC 创建时间。
- **Session**：服务端会话 ID 的哈希、user_id、到期时间、撤销时间、CSRF 校验材料和创建/最近使用时间。
- **Invitation**：邀请码哈希、创建者、有效期、撤销时间、使用者和使用时间；单次使用。
- **Credential**：user_id、标签、加密 Token、加密支付凭证（如业务确需）、启用状态、自动支付开关、支付上限与部署级币种引用、策略版本、最近验证时间和 deleted_at。
- **CredentialExecutionLock**：credential_id、当前 job_id、lease owner/到期时间/epoch；同一 Credential 最多一条有效执行锁。
- **CredentialPolicyRevision**：Credential 敏感执行设置的版本化记录和操作者，供 BookingJob 快照审计。
- **CredentialBookingProfileRevision**：user_id、credential_id、revision、加密 reservationPerson/childrennum/accompanyPerson/followList、内容哈希、操作者与创建时间；只追加，供 BookingJob 固定具体上游参与人语义。普通读取只返回脱敏摘要，不给 Agent。
- **AvailabilityCache**：user_id、credential_id、目标日期/场馆的规范化查询键、脱敏后的语义场地状态/价格、fetched_at_utc 和 expires_at_utc；初始 TTL 为 1000ms。不得持久缓存原始 HTTP 响应、Token、个人字段或作为未来任务坐标使用的数组下标；执行前查询绕过缓存。
- **UpstreamRequestGate**：按上游服务/端点保存跨 Credential 的全局最小间隔、在途租约和 backoff_until_utc；不是用户数据，所有进程共用。
- **IdempotencyRecord**：user_id、API 操作名、请求级 idempotency_key、规范化请求哈希、创建的 job_id 和创建时间；同一 key 对应唯一结果。
- **UserLLMConfig**：user_id、模式（service_default/custom）、用户自定义 base URL、模型、协议、认证模式和加密 API key。自定义配置作为完整 Provider，不逐字段继承环境配置。
- **BookingPlan**：user_id、当前 revision 指针、创建/更新时间和归档状态；不含 Credential、支付或调度字段。
- **PlanRevision**：user_id、plan_id、版本号、来源、操作者、变更摘要、规范化计划内容和内容哈希；(plan_id, revision) 唯一且追加后不可更新/删除。
- **BookingJob**：user_id、plan_id、固定的 plan_revision_id、credential_id、固定的 booking_profile_revision_id、不可变语义 execution_snapshot_json/哈希、upstream_contract_version、scheduled_for_utc、可变 next_action_at_utc、status、execution_phase、resolution_status、租约字段、recovery_required、创建/开始/结束时间和安全错误摘要。execution snapshot 中没有 availability 或上游数组坐标。
- **ResolutionSnapshot**：user_id、job_id、contract version、fetched_at_utc、语义候选 SlotKey 到本次解析状态的映射、脱敏响应指纹、是否仅用于准备的 write_eligible 标记和创建时间；追加写入。准备阶段记录必须为 write_eligible=false，开放阶段重新请求，不得读取准备阶段下标执行预约。
- **JobStep**：user_id、job_id、步骤类型和序号、状态、operation_id、重试计数、时间、脱敏结果摘要和 external_order_id；不保存完整请求/响应或明文副作用凭证。
- **ExternalOrder**：user_id、credential_id、job_id、订单类型、上游订单标识、operation_id、状态、金额/币种、确认来源和时间；只保留恢复和展示所需字段。
- **JobApproval**：user_id、job_id、订单 ID、动作类型、精确金额/币种、批准人、过期时间、使用时间和幂等 ID；一次性、不可改写。
- **JobEvent**：user_id、job_id、状态变化、操作者、UTC 时间和脱敏摘要；追加写入。

所有用户数据表都带有 user_id。API 查询必须在 SQL 条件中绑定当前认证用户的 user_id，例如按 id AND user_id 查询，或通过带 user_id 条件的关联查询；禁止先按资源 ID 无范围读取、再只在 Python 层判断所有权。创建和更新时也要验证所有关联对象属于同一 user_id。

使用复合唯一键和复合外键约束用户归属，例如 (user_id, credential_id)、(user_id, plan_id, plan_revision_id)，防止错误关联其他用户数据。Worker 可按 BookingJob 的 user_id 读取，但仍须校验任务、revision、Credential 的归属关系。管理员跨用户操作须通过单独授权路径审计，不能复用普通用户的无范围查询。

SQLite 要求：

- 每个连接显式执行 PRAGMA foreign_keys = ON，并配置合理的 busy timeout。
- 数据库启用 WAL；WAL 文件及数据库备份纳入本机访问控制，不放入 Git。
- 用有序、版本化 migration 文件和 schema_migrations 表管理演进；启动时按顺序执行，禁止将 create_all 或删除数据库作为迁移。
- 迁移在可控事务中执行，变更前备份；迁移失败时保留原数据库并明确报错。
- 通过唯一约束、检查约束和必要索引落实状态、金额、版本、租约和所有权规则。
- PlanRevision、BookingJob 执行快照、JobStep、ExternalOrder、JobApproval 和 JobEvent 采用追加式审计语义；不可变性由应用服务和必要的 SQLite 约束共同保障。

时间与时区：

- 所有事件时间、租约、邀请码有效期和任务执行时间以 UTC Unix 毫秒整数存储；API 使用带 Z 的 RFC 3339 时间。
- 预约日期和场次按明确的业务时区解释，首版默认 Asia/Shanghai。前端显示业务本地时间并显式显示时区；LLM 的相对日期先按该时区解析，再转换成标准日期/时间。
- 业务时区由部署配置 BOOKING_TIMEZONE 提供，默认 Asia/Shanghai；不得按用户浏览器分别采用不同预约窗口。更换该值需经显式迁移，不能静默改变已有 revision 或 BookingJob 的时间含义。
- 对本地预约日期的字符串和实际执行时间分别建模；不得把“星期四下午 4 点”存成不带时区的机器时间。
- 若部署改用其他业务时区，需显式配置并在界面展示；不得依据浏览器时区静默改变已存计划。

## 7. 认证与凭证保护

- 初始管理员通过本地 CLI 创建，不开放默认管理员密码。
- 普通注册必须提交管理员创建的高熵、单次、可过期邀请码。邀请码只保存哈希；兑换时在事务内原子校验、标记使用并创建用户，避免并发重复兑换。
- 密码使用 Werkzeug 支持的 scrypt 哈希，不可逆存储。登录、邀请码兑换和密码操作做基本速率限制；限制状态可存 SQLite，不依赖 Redis。
- 使用真正可撤销的服务端 Session：Cookie 只带高熵不透明会话标识，SQLite 只保存其哈希和会话元数据。登录时轮换会话，注销、过期、管理员禁用用户或密码更换时撤销对应会话。不得只依赖 Flask 默认客户端签名 Cookie Session 保存登录态。
- Cookie 设置 HttpOnly、SameSite=Lax 或更严格策略；生产 HTTPS 下设 Secure。所有基于 Cookie 的状态变更 API 使用与会话绑定的 CSRF 防护，并校验 Origin/Referer。
- Token、支付凭证和用户 LLM API key 在 SQLite 中以应用密钥加密保存；密钥只来自本地环境变量或受保护的部署密钥文件，不存 SQLite、Git 或日志。字段分离加密、只在后端短时解密。
- CredentialBookingProfileRevision 中的 reservationPerson、childrennum、accompanyPerson/followList 以及任何身份/参与人资料同样按字段加密，仅用户本人设置与 Worker 在该 Job 执行时可读取；普通 API 只返回脱敏摘要，Agent、日志和错误响应不含明细。
- 使用经过审查的带认证加密方案（例如 Fernet），不自制密码算法；密文标记算法/密钥版本以支持轮换。应用加密密钥与上游协议可能使用的 AES 参数完全分离。
- Credential 删除采用软删除：立刻从列表隐藏并禁止新任务使用；未完成任务进入安全取消/核对流程。对仍有未决 JobStep 或 ExternalOrder 的 Credential 保留加密密文，仅供恢复核对，禁止创建新的副作用；无未决引用后可清除密文并保留不含秘密的审计墓碑。软删除不等于撤销上游 Token，用户须在上游单独撤销。
- 邀请码创建、Credential 策略修改、用户禁用和会话撤销均记录操作者与 UTC 时间。

LLM Provider URL 的 SSRF 防护：

- 只允许明确验证过的 HTTP(S) 根 URL；生产中的远程 Provider 必须使用 HTTPS。HTTP 仅可用于开发环境中管理员精确允许的 loopback Host/Port。拒绝 URL 用户名/密码、查询串、fragment、危险端口、非预期 scheme 和绕过校验的重定向。
- 对域名解析全部 A/AAAA 结果，拒绝解析到 loopback、link-local、私有、保留、多播、云元数据和 IPv4-mapped IPv6 等地址；禁止混合返回公网与内网地址。
- DNS 校验必须防止 DNS rebinding：请求连接要绑定到已校验地址，或通过受控出站代理/防火墙强制同等目标限制；不能只在保存配置时解析一次。TLS 证书和 SNI 仍按原始主机名校验。
- 禁止自动跟随重定向，或在每一跳重新完整执行 URL、DNS、地址和端口校验；不允许把 API key 转发到未校验的重定向目标。
- 只允许管理员明确配置的本地开发 Host/Port 和精确可信 tailnet Host/Port 作为私有地址例外。例外不能是任意网段；生产不允许用户自定义 localhost。tailnet 访问例外也不得省略认证、超时和响应大小限制。
- 配置测试与每次模型请求均执行校验；设置连接超时、读取超时、最大响应体和允许的协议路径。不能接受用户提供完整请求 URL 或任意代理地址。

日志采用字段白名单和统一脱敏器。禁止记录 Cookie、Authorization、Token、支付凭证、API key、完整 URL 查询参数、二维码、手机号、身份标识、原始 prompt/完整响应或原始订单详情。异常信息和上游业务摘要先过滤再写日志；安全审计日志仅记录不含秘密的主体、动作、资源 ID 和结果。需要诊断时使用脱敏 fixture，不能把 req 原始抓包放入日志或仓库。

## 8. 上游接口与 req 抓包观察

本节是版本化上游契约的当前事实来源。契约依据本机 req 抓包解密后的结构、同一来源中的官方前端脚本，以及脱敏汇总的本地成功日志。Python 代码、旧 README 和旧假设只能辅助理解；有冲突时更新 Adapter 与本规格，不得要求抓包去适配旧实现。当前 Adapter 标识为 bdtyg-court-v1。原始 req、解密后的真实字段值、Token、用户身份字段、支付口令和真实订单值均不进入 Git、fixture、日志、Agent 上下文或普通 API。

### 8.1 HTTP 封装与可见字段

- 上游接口使用 POST JSON；认证头为 token。外层请求体为 item 字段，内容是内层 JSON UTF-8 文本按本机环境密钥执行 AES-CBC/PKCS7 后的十六进制字符串。密钥、IV 和 Token 只由本机 env 提供，Adapter 运行时短暂读取；不打印、不写日志、不进入快照。解密只用于本地契约分析，不保存解密产物。
- 所有响应均需解析 HTTP 状态及 JSON。标准外层响应为 success、message、resultData。HTTP 200 不代表业务成功；Adapter 必须按 endpoint-specific 的 success/message/resultData 组合分类。

### 8.2 bookingByTime 与场地/时间坐标

- 请求路径为 /service/appointment/appointment/phone/bookingByTime；内层字段为 nodeid（上游场馆 nodeid）和 selectdate（目标日期）。
- 已观察的 bookingByTime 成功组合为 success=true、message=CORE10008，resultData 字段为 timeList、mintimeselect、conflictList、maxAppointmentNodeNum、bookingstartdate、bookingenddate、start、end、isNew、bookingstarttime、nodeList、priceList、maxtimeselect、bookingendtime、stepnumber。字段缺失、类型或结构发生未登记变化时返回 contract_drift，不猜测字段。
- nodeList 元素为 sitename 与 nodeid。顶层请求 nodeid 是场馆标识；nodeList[].nodeid 是该场馆内单个场地标识。PlanRevision 必须同时保存前者与后者的语义身份及可选名称快照。
- timeList 元素为 time 与 status；time 是当前响应中的可预约时间槽标记。官方前端直接把 timeList 传给报价和创建接口，但未用 status 判定网格空闲；status 当前只按原字符串保留，值 0/1 不能在后端被自行解释为可用/不可用。
- stepnumber 是官方前端用于网格行数的值，须与当前 timeList 结构按已验证规则一致。mintimeselect、maxtimeselect 是一次选择允许的最少/最多时间槽数；maxAppointmentNodeNum 是一次预约允许覆盖的不同场地数上限。数值类型可能以字符串返回，Adapter 需严格解析，缺失、非数值或越界时 fail closed。
- conflictList 元素使用 courtIndex-timeIndex[-type]。前两段是 nodeList 场地下标、timeList 时间下标；无第三段时官方前端标为已预订。带类型时官方前端将其映射到 courseN，并阻止选择：
  - 1：体育课。
  - 2：项目培训。
  - 3：体训队。
  - 4：艺术团。
  - 5：工会活动。
  - 6：其他活动。
  - 7：官方 UI 的 cannotSelect/不可预订状态。
  - 0 在前端有 qita-grid 样式但抓包代码未提供清晰图例；作为未分类硬性排除处理，直到新契约证据确认。
  未知类型、非整数下标、越界坐标、段数不是 2 或 3 都是 contract_drift。Agent 不接收这些原始代码。
- booking 坐标字符串固定为“场地下标-时间下标”，即 courtIndex-timeIndex。两小时预约由 CandidateResolver 从当前 timeList 找到精确起始时间与连续后续时间槽，为同一场地生成两条坐标；禁止跨缺口、按近似时间匹配或复用旧坐标。
- priceList 元素为 price、x、y。官方前端按网格行/列查询价格，其中 x=timeIndex、y=courtIndex；这与 booking 坐标 courtIndex-timeIndex 顺序相反。priceList 只用于当前可用性展示，不是支付金额的最终来源。
- bookingstartdate/bookingenddate 是当前响应声明的目标日期范围；bookingstarttime/bookingendtime 是上游给出的正式预约开放/截止时刻。当前样本观察到 bookingstarttime=07:30、bookingendtime=23:00。start/end 与 isNew 原样保留；start/end 不替代 booking 时间。官方客户端根据 isNew 和目标日是否等于 bookingenddate 对 UI 时间门禁作条件判断，但服务端执行门禁不得由未验证的 isNew 组合放宽。当前三日策略或时刻与上游值冲突时暂停为 contract_drift。

### 8.3 报价、创建与业务结果

- getPayPrice 路径为 /service/appointment/appointment/phone/getPayPrice。当前解密请求字段为 nodeList、nodeid、reserveTime、reserveDate、accompanyPerson、reservationPerson、appointmentType、timeList；当前捕获值和官方前端均显示 appointmentType 为字符串 2。reserveTime 使用当前生成的 coordinatesList 字符串数组，nodeList/timeList 必须来自同一次最新 bookingByTime 响应。reservationPerson 来自上游账户资料，只能由后端 Credential 上下文提供，不能进入 Agent 或普通 API。
- 已观察的成功 getPayPrice 响应为 success=true、message=“成功”、resultData 含 pricemap 与 txamt；txamt 是字符串报价。成功字段缺失、金额无法安全解析或响应不符合该组合时不得创建订单。
- createBookingBytime 路径为 /service/appointment/appointment/phone/createBookingBytime。当前真实解密请求字段为 nodeList、payprice、isLastDay、appointmentDate、timeList、coordinatesList、booktype、nodeid、childrennum、followList、txamt、payway；捕获的收费预约路径中 booktype 为数值 2、payway 为字符串 77。官方前端代码对免支付分支设置 payway=72，但当前 req 没有该分支的线上请求证据；Adapter v1 不得据此自动发送免支付请求，需等新 req 和契约 fixture 确认。booktype 是上游预约类别代码，不等于 one_hour/two_hour；时长由 coordinatesList 中连续 timeList 项数量表达。各字段类型由脱敏 fixture 固定。官方前端还有 unitPrice/id 等局部字段，但它们未出现在当前真实解密请求样本中，Adapter v1 不得因前端临时对象含有这些字段就把它们添加到线上请求；只有新 req 证据和契约升级后才能增加。
- 已观察到 createBookingBytime 的成功组合为 success=true、message=CORE10008、resultData 含 orderno 与 txamt；CORE10008 在该组合下不是失败。已观察的业务失败组合为 success=false、message=“每人每天最多预约1次”，属于用户/每日额度终止错误，不能换场地重试。其他 message/字段组合一律 unknown/contract drift，先按订单接口对账，不得尝试下个候选。
- 预约副作用只用刚才实时 bookingByTime 的 nodeList、timeList 与刚解析的 coordinatesList；getPayPrice 与 createBookingBytime 之间不再查询其他无关数据，不加入没有证据的固定 sleep。
- openPlatFormPayOrder 当前抓包的内层字段含 txamt、orderno、payway、password。password 是支付秘密，只可按原有支付安全策略短时解密使用；任何 snapshot、JobStep、ExternalOrder、日志、Agent 和响应均不得保存或返回该值。已观察支付响应为 success=true/message=“支付成功”，但支付结果仍须通过 payOrderForPhone/payOrderDetails 权威核对，HTTP 状态或单条提交响应都不代表最终已支付。
- payOrderForPhone 的请求字段为 pageNumber、pageSize、ordertype；payOrderDetails 的请求字段为 bookingno、id。订单核对只投影匹配所需的 orderno、bookingno/id、status、paytime、金额等字段；完整结果含身份、联系方式、二维码和其他个人字段，禁止向 UI/Agent/日志透传。图片验证接口/图片资源说明流程存在人工验证；不破解、不模拟、不绕过。

### 8.4 UpstreamContractAdapter 与 fixture

- Adapter 将外层加密传输、endpoint-specific Schema、业务结果分类、冲突码映射与 CandidateResolver 隔离；版本升级时保留旧版本解释已创建任务的快照和审计数据。
- 在本机成功日志中，bookingByTime 有成功业务响应记录；观测到同端点请求最短启动间隔约 668ms，未发现 429 或 Retry-After。该观测不能证明上游承诺的最大频率，因此初始全局最小间隔取较保守的 1000ms 并保持服务端可配置；收到 Retry-After/429 后统一提高冷却时间。
- 契约 fixture 必须人工合成并脱敏，包含 bookingByTime 的完整字段形状、数组顺序变化、冲突类型 1-7/未知值、时间缺口、getPayPrice 成功与失败、createBooking 成功及每日额度终止失败、HTTP 200 但业务失败、响应结构漂移等情形。使用虚构 nodeid、姓名和订单号；不得复制原始 item 密文、Token、电话、身份标识、支付口令、二维码、真实预约时间/价格或可重放值。
- 任何真实响应只允许以脱敏、字段白名单摘要用于内存分析；不将原始 req 文件、解密结果或运行日志加入 Git。真实预约和支付不作为自动化测试对象。

userAddress/getUserInfo 响应含身份标识、电话和用户名字段；payOrderDetails 含订单标识、联系方式、二维码及支付详情字段。服务端只投影执行需要的字段，不将完整响应传给 Agent、前端或普通日志。ExternalOrder 只存订单核对所需最小字段。

执行器不能依赖用户保存计划时的旧 availability。每次正式 createBookingBytime 前都重新查询并解析；查询类接口超时或断连可按全局退避策略有限重试。createBookingBytime、创建支付单、支付等副作用接口超时、断连或无法确定业务结果时属于结果未知，必须先对账，不能直接重试或切换下一个候选。

验证相关步骤若要求用户操作，Worker 暂停为 awaiting_human 并提供清晰状态；不识别、不求解、不模拟用户操作、不绕过验证码或频率限制。实施时如需要契约样本，应先生成不含凭证、个人数据、二维码和可重放值的脱敏 fixture。真实预约和支付不作为自动化验证对象。

## 9. API 草案

认证和邀请：

- POST /api/admin/invitations：管理员创建单次邀请码及有效期；只返回一次性邀请码。
- GET /api/admin/invitations、DELETE /api/admin/invitations/{id}：管理员查询不含邀请码明文的状态、撤销未使用邀请码。
- POST /api/auth/register：使用邀请码注册。兑换和用户创建原子完成；可选择返回新建会话。
- POST /api/auth/login、GET /api/auth/session、POST /api/auth/logout：服务端会话登录、状态读取和撤销注销。

Credential 与 LLM：

- GET/POST /api/credentials：读取当前用户 Credential 的脱敏摘要或添加一个 Credential。
- PATCH/DELETE /api/credentials/{id}：仅由用户修改非秘密标签/启用状态/自动支付上限，或发起软删除。支付设置修改需明确确认并递增策略版本；Agent 没有调用此 API 的工具。
- GET/PUT /api/credentials/{id}/booking-profile：由 Credential 所属用户查看脱敏参与人摘要或创建新的 CredentialBookingProfileRevision；明文身份/参与人资料不返回给 Agent 或普通读接口。
- POST /api/credentials/{id}/validate：用户主动验证当前 Credential；响应不包含 Token。
- GET/PUT/DELETE /api/llm/settings：读取模式和脱敏配置、设置完整的用户自定义 Provider、或改用服务级默认。读取时只返回安全的 base URL、模型、协议、认证类型和 key 是否已配置。
- POST /api/llm/test：用户主动测试当前完整 Provider；记录脱敏结果，不返回或记录 key。

场地窗口与 availability：

- GET /api/booking-window?target_date=YYYY-MM-DD：返回服务端业务时区、当前业务日期、默认目标日、当前三日查询窗口、任意目标日 T-2 的 query_open_at/预约开放基准、当前响应验证状态及 can_query/can_book_by_time。前端不得自行重算。
- GET /api/availability?credential_id=...&target_date=YYYY-MM-DD：目标日未进入查询窗口时返回 query_not_open/unresolved_future，不调用上游；已进入窗口后由 AvailabilityService 返回语义候选、硬排除原因及窗口状态。响应包含 fetched_at_utc、occupancy_status、window_status、can_select_plan、can_book 和 reason_code，不返回 coordinatesList 或原始 conflictList。省略 target_date 时只查当前三日窗口；请求按全局 UpstreamRequestGate 执行。

计划与 Agent：

- GET/POST /api/plans、GET/PATCH /api/plans/{id}：创建、读取或追加计划版本。PATCH 必须携带 base_version 或 If-Match；冲突返回 409 和当前版本摘要。
- GET /api/plans/{id}/revisions：读取当前用户自己的历史 revision。
- POST /api/plans/{id}/agent-edits：提交 Schema 化的计划差异，使用相同乐观锁和 PlanService；不得接受 job、支付、Credential 策略或调度字段。
- POST /api/plans 和 POST /api/plans/{id}/agent-edits 保存时始终执行语义 Schema 校验。查询窗口前不要求 validation_credential_id，也不发上游查询；保存结果标记 unresolved_future。窗口内可选择 validation_credential_id 请求实时预览/校验；已明确硬排除的候选拒绝保存，未取得实时结果的候选不能标为可用。Agent 不能自行指定或替换 validation Credential。

任务与订单：

- POST /api/jobs：仅用户明确确认后创建，必须携带请求头 Idempotency-Key。请求体含 plan_id、可选 plan_revision_id、credential_id、booking_profile_revision_id 和 execution_mode（official_open、at、now）；at 模式需传 scheduled_for_utc。official_open 模式可在目标日查询窗口前任意天创建；服务端按 BookingWindowPolicy 计算 earliest_valid_booking_at 写入 scheduled_for_utc，初始 next_action_at_utc=max(now_utc,T-2 00:00)，返回 queued/waiting_query_window/unresolved_future。now 仅在当前 can_book_by_time=true 时接受。服务端事务内校验 profile 与用户/Credential 归属并固定 profile revision、快照和 PlanRevision；客户端不能传坐标、执行快照、个人资料明文、自动支付授权、任意上游请求或 source=agent。
- 同一用户对同一创建操作重放相同 Idempotency-Key 和相同规范化请求时，返回原 BookingJob，不再创建任务；key 相同但请求内容不同返回 409。并发重复请求也只能创建一个 Job。IdempotencyRecord 至少保留到其 BookingJob 及重试窗口结束，不能用短 TTL 让延迟网络重试创建重复任务。
- GET /api/jobs、GET /api/jobs/{id}：查询当前用户自己的任务、status、phase、next_action_at_utc、resolution_status、快照摘要和 JobStep 状态；只返回语义候选及原因，不返回上游坐标。
- POST /api/jobs/{id}/cancel：发出本地取消请求；运行中只产生 cancel_requested，响应明确说明上游订单状态需单独核对。
- POST /api/jobs/{id}/resume：用户确认验证已完成或请求恢复；Worker 重新获取锁并对账后决定是否继续，不直接跳过校验。
- POST /api/jobs/{id}/payment-approvals：对服务器显示且已核实的一个订单和精确金额创建一次性人工授权。服务端校验订单归属、金额、币种、当前支付上限和状态；模型工具不能访问。
- GET /api/external-orders、GET /api/external-orders/{id}：只展示当前用户的最小订单状态和金额。除非上游取消接口已确认支持且另有明确授权，不提供将本地取消映射成上游取消的行为。

除登录、注册和公开的健康检查外，所有接口均需登录并在 SQL 查询中绑定当前 user_id。管理员接口另做角色校验和审计。客户端不得提交 Token 作为上游调用参数；只传当前用户 Credential ID，由后端按 user_id 读取并短时解密。所有修改端点还要校验 CSRF 和幂等要求。

## 10. 前后端体验

前端提供：

- 登录和邀请码注册；无公开自助注册入口。
- Credential 标签、启停状态、验证结果和自动支付设置；支付上限用明确币种和金额展示。
- 计划日期选择器默认选中业务日期后天，但允许提前选择任意未来目标日并编辑语义候选。实时场地查询仍只允许当前三日窗口；窗口外显示 unresolved_future。00:00 查询开放和实际预约开放时刻由后端返回，前端不自行计算。
- 场地结果分别显示 occupancy_status 与 window_status。查询开放后、正式 bookingstarttime 前的正常候选仍可加入计划；活动、社团和其他硬性占用显示具体原因且不可选择。用户明确选择今天/明天时，仅显示仍未过时且当前上游窗口覆盖的候选。
- 场地网格、两小时/一小时计划队列、人工排序、删除、保存版本和冲突提示。
- Agent 修改预览、队列差异、版本历史和冲突后重新生成提示；Agent 界面没有真实任务创建、支付策略或执行设置控制。
- LLM Provider 设置：服务级默认/个人自定义模式切换、base URL、API key、模型和兼容协议；已保存的 key 只显示配置状态，可替换或清除。
- BookingJob 创建表单：选择计划版本、Credential 和“预约开放时执行”或明确时间；明确时间早于目标开放或不在当前每日写窗口时拒绝，不自动更改。长期任务显示初始查询时刻 T-2 00:00、预约目标开放时刻 T-2 bookingstarttime、Policy 计算的最早有效执行时刻，以及未解析/准备/等待开放阶段。
- 创建任务时确认 Credential 对应的预约参与人 profile revision；界面只显示必要的脱敏摘要。后续修改 profile 产生新 revision，不影响已创建任务；Agent 不读取或选择参与人明细。
- 00:00 准备完成后展示当前解析摘要，但注明该结果不是最终预约坐标。正式开放时 Worker 重新查询并解析；界面显示最新候选状态、当前步骤和跳过原因，永不显示或要求用户编辑 courtIndex/timeIndex。
- 统一任务列表：到期时间、状态、当前步骤、可读错误、取消/恢复操作和 awaiting_human 提示。
- 价格待确认时明确显示已核实的订单、实际金额、币种、支付上限及一次性确认内容；未知状态不得出现可直接支付的确认按钮。
- 上游订单摘要与本地 Job 状态分开显示；本地取消不显示为“上游订单已取消”。
- 所有时间按业务时区展示，并在需要时标出 UTC 或时区名称。

本地开发阶段前后端分别启动，Vite 代理 API；上线到 Tailscale 时使用同源 HTTPS 访问。CORS 不允许任意来源，开发和生产来源分别明确配置。反向代理只信任显式配置的代理地址；不信任客户端伪造的 forwarded headers。

## 11. LLM 接口配置

配置字段采用以下名称：

- LLM_BASE_URL：服务级默认 OpenAI 兼容 API 根地址，通常包含 /v1，不填写完整 chat/completions 路径。
- LLM_API_KEY：服务级默认 API key；服务端必须与同一组环境配置中的 base URL 和模型配套使用。
- LLM_AUTH_MODE：服务级认证模式，明确为 bearer 或 none；为空的 API key 不得被静默解释为继承其他来源的密钥。
- LLM_MODEL：服务级默认模型 ID。
- LLM_PROTOCOL：首版固定为 openai-chat-completions。

服务级配置校验必须按完整 Provider 处理：base URL、模型、协议和认证模式为必需字段；认证模式为 bearer 时必须有 API key，为 none 时明确不发送 Authorization。任一必需字段缺失时标记为未配置，不从用户配置补值。

Provider 配置按一整组选择，禁止逐字段回退或混合：

- service_default 模式使用部署者配置的完整环境 Provider 对象：base URL、API key/无认证模式、模型和协议全部从同一服务级配置解析。
- custom 模式只使用当前用户保存的完整 Provider 对象：用户 base URL、用户自己的 API key 或明确的无认证模式、用户模型和协议。用户配置的 API key 为空时必须视为“明确无认证”或“配置不完整”，绝不能补入服务级 LLM_API_KEY。
- bearer 模式必须有该用户自己的 API key；none 模式明确不发送 Authorization。不得因 API key 为空而自动切换认证模式。
- 用户切换模式时整体切换 Provider；某个必需字段缺失就返回配置错误，不从另一模式继承该字段。
- 服务级环境变量不复制到用户配置表。用户配置只对所属用户生效。
- 用户自定义 API key 加密保存，数据库和 API 不返回明文；用户可以替换或清除。服务端调用日志不记 key、完整 Authorization 或提示词。
- 没有可用 Provider 时，Agent 功能显示“尚未配置”，不影响人工预约流程。连接测试只在用户明确点击后调用。
- 非 OpenAI Chat Completions 兼容协议需后续增加专用 Provider Adapter；配置 base URL、key 和模型名本身不保证任意厂商接口兼容。
- 所有 Provider 调用都应用第 7 节的 SSRF 校验、连接和读取超时、响应体限制与 TLS 校验；不关闭证书验证。

## 12. Tailscale 接入

- 仅授权 tailnet 成员可通过私有 Tailscale Serve/ACL 访问；不启用面向所有互联网用户的 Funnel 或公开注册。
- Tailscale ACL 限制可访问的成员或组及服务端口；服务绑定私有接口或由受控代理转发。
- Tailscale 只作为网络访问边界，不等同于应用认证、角色授权、CSRF 防护或数据库租户隔离。
- 应用登录和 user_id 数据隔离继续生效；不以来源 IP 或 tailnet 身份替代应用会话。
- 生产关闭 Flask debug，启用 HTTPS、安全 Cookie、CSRF 和精确 CORS；只信任显式配置的反向代理头。
- 确认 SQLite、WAL、备份、日志和部署密钥不会被 tailnet 以外访问；备份同样加密或按本机敏感数据保护。
- 本地开发阶段不要求安装或启用 Tailscale；后续接入前先完成认证、CSRF、CORS、日志和密钥配置。

## 13. Git 与实施阶段

当前仓库已初始化在 main，但没有应用代码基线提交；现有应用文件仍未跟踪，且混有重复打包目录、Windows 二进制、日志和抓包文件。

本次已新增项目级 .gitignore，明确排除 env、req/、运行日志、个人 booking_plan.json 和 SQLite 数据/WAL。实施开始前仍需挑选可维护源码并提交干净的源代码基线；Windows 可执行文件、打包压缩包和重复发布目录也不进入基线。当前 .git/info/exclude 只是本机规则，不能替代项目级忽略文件。脱敏 fixture 必须人工合成。基线提交完成后，建立一个 feature worktree（建议分支名 codex/multitenant-booking）；所有实现阶段在该 worktree 内按垂直功能分批提交，完成后本地合并回 main，不需要配置远程。

实施阶段：

1. **源码与启动基线**：确定唯一后端源码、恢复或建立前端源码、补充 Conda test 依赖和启动说明；确认敏感文件排除规则。
2. **SQLite 与认证基础**：WAL、外键、migration、User、服务端 Session、邀请创建/兑换、CSRF 和所有权查询约束。
3. **Credential 与 Provider 安全**：密文存储、软删除、策略版本和支付上限；完整 LLM Provider 模式、密钥隔离和 SSRF 防护。
4. **统一计划**：Plan/PlanRevision、语义 BookingCandidate/内部 SlotKey、明确 fallback_policy、查询窗口外 unresolved_future、追加式修订、optimistic locking、人工编辑和 Agent 计划差异。
5. **任务模型与队列**：BookingWindowPolicy、BookingJob 不可变语义快照、execution_phase/next_action_at_utc、waiting_query_window -> preparing -> waiting_booking_open -> running、请求级幂等；远期/立即/定时任务进入同一队列；状态机、lease 和 Credential 执行锁。
6. **上游契约与可靠执行器**：按脱敏 req 和官方前端建立版本化 UpstreamContractAdapter/CandidateResolver；验证冲突映射、坐标顺序、getPayPrice/createBookingBytime 字段与业务失败分类；JobStep、ResolutionSnapshot、ExternalOrder、副作用恢复、bookingstarttime 最终门禁、实时 availability、证据驱动的全局节流/短缓存/退避、awaiting_human、取消/恢复和支付门禁。
7. **前端闭环**：Credential 和 Provider 设置、计划编辑与 Agent 预览、Job 创建/调度、订单摘要与人工作用确认。
8. **本地安全验证**：双用户隔离、邀请码竞态、计划并发更新、远期任务阶段恢复、00:00 预解析与开放时重新解析、数组顺序变化、候选缺失/活动硬排除、Worker 重启恢复、租约过期、同 Credential 锁、重放保护、LLM SSRF 边界及日志脱敏；上游只用模拟服务和人工合成的脱敏 fixture。
9. **Tailscale 私有接入**：关闭 debug，配置 Serve/ACL，验证授权成员可访问、未授权成员不可访问且均需应用登录。

每阶段先按已审阅规格编写实现计划；不把该规格本身视为已授权实施。实施中若发现上游接口无法提供可靠订单查询或任务恢复所需字段，先记录限制和安全降级方式，不盲目重试副作用。

## 14. 验收标准

- 邀请码只能兑换一次且可过期、可撤销；并发兑换最多创建一个用户。
- 用户登录态由可撤销的服务端 Session 管理；注销后旧 Cookie 不能继续访问业务接口。
- 用户 A 不能读取或修改用户 B 的 Credential、计划、revision、Job、订单、会话或 LLM 设置；SQL 查询本身始终绑定 user_id。
- Credential 软删除后不可创建新任务；有未决副作用时保留恢复所需密文且禁止新副作用，无未决引用后清除密文。
- BookingJob 固定同一用户/ Credential 的 CredentialBookingProfileRevision；之后修改参与人资料不改变已创建任务。缺少 profile 或跨用户/Credential 关联时拒绝创建/执行，个人字段不会进入 Agent、日志或普通 API。
- Token、支付凭证和 LLM API key 在 SQLite 中不可读；日志、Agent 输入、API 错误和前端响应不含原始凭证。
- 自定义 LLM Provider 始终使用同一用户的 base URL、key/无认证、模型和协议；用户缺失 key 不会继承服务级 key。
- SSRF 测试覆盖 loopback、私有/链路本地、元数据地址、IPv4-mapped IPv6、混合 DNS 结果、DNS rebinding 和重定向。
- 没有 LLM 配置时，人工预约功能仍可用；连接测试只在用户主动操作后发起。
- 人工 UI 和 Agent 修改同一份计划，产生不可变 revision；并发修改能返回版本冲突。
- 创建 BookingJob 时固定 plan_revision_id 和执行快照哈希；之后编辑计划不能改变已创建任务；修改时间或 revision 需新建任务。
- Agent 无法调用创建 Job、取消/恢复 Job、修改支付策略或发起真实 createBooking/支付请求。
- 立即与定时任务都在同一 BookingJob 表和 Worker 队列调度；不同 Credential 可在全局限制内并行，同 Credential 不并发。
- 两个 Worker 同时领取同一任务或同 Credential 任务时，事务和持久化租约/锁只允许一个执行者。
- 在 createBooking、支付调用前崩溃、网络断开、租约过期或 Worker 重启后，先核对 JobStep/ExternalOrder 与上游状态；状态不确定时不会重复提交。
- 每个正式 createBookingBytime 前重新 bookingByTime 查询并解析实时 availability；00:00 准备阶段的 ResolutionSnapshot 明确 write_eligible=false，不能作为开放时坐标。HTTP 200 的业务失败不会被当成成功。
- 星期一提前创建星期日目标任务时不调用上游，状态为 queued/waiting_query_window/unresolved_future；星期五 00:00 自动查询、解析并追加准备快照，之后 queued/waiting_booking_open；星期五当前 bookingstarttime（已验证样本 07:30）到达时再查询、重新解析，按冻结 priority 执行 getPayPrice -> createBookingBytime。
- 星期一 00:00 的 BookingWindowPolicy 精确返回星期一、星期二、星期三可查询；星期日目标日 T 的 query_open_at 为星期五 00:00，已验证 booking_open_at 为星期五 07:30。测试覆盖日期边界和 07:29:59/07:30:00；当前响应与已验证时刻不一致时进入 contract_drift。今天/明天目标的 T-2 已过去时，也必须在当前本地日 07:30 前阻止所有副作用。
- 任意远期目标日可保存语义 BookingPlan 并创建 execution_mode=official_open Job；任何 T-2 查询窗口前，API/Worker/Agent 均不调用 bookingByTime 或上游写接口。查询开放至当前 bookingstarttime 之间只读准备；开放前及窗口结束/场次已开始后，所有副作用均由后端最终门禁阻断。
- POST /api/jobs 在正式开放前允许创建 execution_mode=official_open 的远期任务，scheduled_for_utc 为 Policy 计算的最早有效执行时刻，next_action_at_utc 为 max(now_utc,T-2 query_open_at)；明确传入早于目标开放或不在每日写窗口的 execution_mode=at 返回 422，不会静默更改。now 模式只在当前每日写窗口与目标预约窗口均已开时接受。
- 对今天/明天目标，即使其 T-2 目标开放时刻已过去，每日 bookingstarttime 前仍不能发出预约或支付请求；bookingendtime 后不能创建预约。支付在开放后按已确认订单状态和支付端点有效期判断，不得误用 bookingendtime 作为支付截止。若存在场次开始前的下一个有效预约窗口，official_open 才可排到该时刻，否则任务创建明确拒绝。
- 每个目标日按 T-2 天计算查询和预约开放时刻；默认 D+2，但在上游允许时今天/明天未过时场次也可由用户明确选择，不存在把“第三天”误算成 D+3 的偏移。
- PlanRevision 使用语义 BookingCandidate 字段（target_date、上游场馆 nodeid、nodeList 场地 nodeid、名称快照、开始时间、时长、预约类型、priority、内部 SlotKey）；无 upstream slot_id 时不构造假 ID。计划和 Job 快照无任何旧 court/time 下标或 coordinatesList。
- CandidateResolver 只以最新 nodeList[].nodeid 和 timeList[].time 精确求下标；场地/时间缺失、ID 重复、时间不连续或契约结构异常均 fail closed，不按名称/近似时间/旧下标猜测。两小时坐标必须为同一场地的两个连续有效时段并满足 mintimeselect、maxtimeselect、maxAppointmentNodeNum。
- conflictList 无类型后缀映射为已预订；类型 1-6 依官方前端映射体育课、项目培训、体训队、艺术团、工会活动、其他活动；类型 7 为不可预订，类型 0 和未知类型 fail closed。timeList.status 原样保留，不用旧 Python 的 status=1 过滤逻辑误判候选。priceList.x 为 timeIndex、y 为 courtIndex，与预约坐标顺序相反。
- bookingByTime 请求内层字段为 nodeid/selectdate；getPayPrice 与 createBookingBytime 的字段集合与响应结构由版本化 Adapter fixture 验证。getPayPrice 成功要求 success=true、message=“成功”及 txamt；createBookingBytime 的已验证成功组合包含 success=true、message=CORE10008、orderno/txamt。success=false 且 message=“每人每天最多预约1次”是终止性业务失败，不切换场地；未知业务 message 先对账。
- Availability 查询缓存与全局 gate 跨 API、Agent、Credential 和 Worker 生效；不使用任意 2s/15s 常量。本地成功日志最短同端点观测约 668ms，初始配置为 1000ms；收到 429/Retry-After 跨 Credential 冷却，最终开放查询绕过缓存。更换 Token/Worker 不能规避限流。
- 查询超时可有限重试；createBooking 或支付超时/断连不重放，并先对账。createBooking 结果未知时不能转向下一候选。
- POST /api/jobs 相同 Idempotency-Key 和请求体的并发/网络重试只创建一个任务；相同 key 携带不同内容返回 409。
- 用户取消运行中 Job 时先显示 cancel_requested；本地 Job 取消不会被表示成上游订单取消或退款。
- 图片验证进入 awaiting_human；用户恢复后先核对状态再继续。
- 自动支付默认关闭；金额缺失、币种不符、超限、价格变化或订单状态不确定时暂停，不发生支付。
- 用户对特定订单/金额的一次性确认可追溯、过期且只能使用一次；Agent 不能生成此授权。
- SQLite 每个连接启用外键，数据库使用 WAL，schema migration 可重复运行且不删除用户数据。
- 事件时间按 UTC 持久化，预约日期和 UI 按配置的业务时区解释与显示。
- 日志采用脱敏白名单，不含密钥、Token、个人资料、Cookie、二维码或完整上游响应。
- 项目级 .gitignore 确保 env、req/、日志、booking_plan.json、SQLite 数据及 WAL 不会被新 clone 意外加入 Git；契约 fixture 为人工合成，不包含真实 ID、价格、日期、请求密文或个人字段。
- Tailscale 未授权成员不能访问服务；授权成员仍需通过应用登录。
- 验证使用模拟上游或脱敏 fixture，不对真实预约和支付接口发起自动化测试。

## 15. 不在首版范围

- 公网匿名访问、开放自助注册、公开 Funnel。
- Redis/Celery、多节点调度、PostgreSQL 或微服务架构。
- LLM 直接访问 Token、支付凭证、任意 HTTP 客户端、数据库或 Worker。
- Agent 创建真实任务、触发真实预约、控制自动支付或执行策略。
- 非 OpenAI Chat Completions 兼容协议的 Provider Adapter。
- 验证码识别/绕过、反复高速轮询或规避上游限额。
- 未经查询确认就重放 createBooking、支付或其他副作用请求。
- 自动处理上游取消、退款、未知支付结果或超出支付上限的金额。
- 服务器休眠时仍保证自动任务运行；本地机器休眠期间 Worker 无法执行任务。
