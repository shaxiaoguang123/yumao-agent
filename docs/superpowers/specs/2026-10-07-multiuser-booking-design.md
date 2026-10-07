# 羽毛球预约系统：多用户与 Agent 计划设计

- 日期：2026-10-07
- 状态：加入 Preparation Agent、动态开放时间与 Token 生命周期后的规格修订版，等待用户审阅
- 目标：在现有预约流程上构建本地开发的前后端分离多用户应用，后续仅向授权的 Tailscale 网络成员开放。

## 1. 已确认的目标与约束

- 保留人工选择场地、编辑预约计划和定时执行的使用方式，并增加邀请制注册、应用登录、多用户数据隔离和多个 Credential。
- 保留 Flask API + Vue 前端 + SQLite + 轻量 Worker；不引入 Redis、Celery、PostgreSQL、多节点调度或微服务。
- 人工界面与 Planning Agent 共用 BookingPlan 和 PlanRevision。计划只保存用户表达的预约意图，不保存按某一天查询得出的 availability、历史场地 nodeid、数组坐标或历史价格。
- 长期提前预约以不可变 ReservationIntent 为核心。用户可在目标日 T-2 查询窗口前任意天创建意图；Job 固定该意图和 PlanRevision。后续计划修改不得改变已创建任务。
- T-2 日 00:00 起进入 Preparation Window。Worker 在统一 UpstreamRequestGate 约束下，可按低频调度多次获取该目标日的真实 bookingByTime；每次查询可产生新的 PreparedQueueRevision。准备数据只用于当天排序建议和展示，不能作为开放时下单证据。
- `official_open` 表示跟随上游该目标日当前响应中的 `bookingstarttime` 自动执行。创建任务时显示的 07:30 只是已知规则下的预计时间；T-2 真实查询后以结构合法的当前上游时间更新调度。合法时间值变化不等于 contract drift。
- 正式开放时必须绕过缓存重新查询 bookingByTime，基于该次响应生成 FinalExecutionQueue，再按确定性的 CandidateResolver、QueuePolicyValidator、getPayPrice、createBookingBytime 路径执行。准备阶段的场地坐标、数组下标、价格和可用性不得进入最终请求。
- 上游协议以本地 `req/` 真实抓包及同目录官方前端代码为最高事实来源。不同目标日的 `nodeList`、`timeList`、`conflictList`、`priceList`、价格和开放时刻均视为动态数据；历史结果只能辅助展示，不能作为未来目标日的执行事实。旧 Python 实现仅作次级参考。
- `req/` 和 `.env` 可能包含 Token、密钥和个人数据。只允许在本机内存中做必要的协议核对；不把原始内容、完整 JWT payload、解密结果或真实请求/响应写入 Git、日志、Agent 上下文或普通 API。
- 保留 Planning Agent，并新增受限 Preparation Agent。后者只处理经 AvailabilityService 和 UpstreamContractAdapter 归一化的当天数据，输出队列提案；所有提案须通过 QueuePolicyValidator。LLM 不可用时，确定性基线队列仍可运行。
- Agent 不能创建 BookingJob、调用真实预约或支付副作用、改变 Credential 或支付安全设置。正式开放关键路径不依赖 LLM 实时推理。
- Credential 的 Token 以加密形式保存，任务固定 Credential 身份与用户授权，但执行时使用该 Credential 当前最新且已验证的 Token。JWT `exp` 只提供本地过期提醒；真实有效性由安全的只读上游验证确认。
- Credential Token 替换必须确认仍属于同一上游账户。不同账户必须新建 Credential；任务在执行前检查账户指纹、Token 有效性、预约资料和 Credential 启用状态。
- 私有 Tailscale 只作为网络访问边界；应用独立登录、服务端可撤销 Session、邀请码注册和 SQL 层 `user_id` 隔离仍然生效。
- 自动支付默认关闭；支付金额必须同时满足 ReservationIntent 价格上限、Job 创建时冻结的用户授权、当前 Credential 支付上限和订单状态校验。金额变化或状态不确定时暂停。
- 不执行验证码绕过、频率规避或通过多个用户/Token 绕过上游限流。需要人工验证时暂停并交由用户处理。
- 先在本地开发和验证，完成认证、CSRF、CORS、日志和密钥保护后再接入授权 Tailscale 网络。

## 2. 系统边界

应用由三个逻辑部分组成：

1. **Vue 前端**：登录、邀请码注册、Credential 与 Token 状态、预约意图编辑、Agent 提案预览、任务阶段、准备队列历史、订单摘要和人工作用确认。
2. **Flask API 与领域服务**：服务端 Session、用户与 Credential 授权、ReservationIntent/PlanRevision、BookingWindowPolicy、AvailabilityService、UpstreamContractAdapter、CandidateResolver、QueuePolicyValidator、CredentialTokenService、LLM Provider Adapter 和 BookingJob 服务。
3. **SQLite 与 Worker**：保存用户数据、不可变意图、任务、租约、步骤和订单；Worker 领取到期任务，执行 T-2 准备刷新及正式开放时的确定性预约流程。

Planning Agent 负责理解自然语言并修改语义预约意图；Preparation Agent 是同一应用内部的受限规划能力，不是独立微服务。Worker 可调用它生成 PreparedQueueProposal，但只能由确定性 QueuePolicyValidator 接收或拒绝结果。Agent 不持有上游 Token、任意 HTTP 客户端、JobService、支付服务或 Credential 设置能力。

Flask API 和 Worker 可以同机运行，逻辑上分离即可。SQLite 是任务与恢复状态的唯一持久化来源。任务等待时间通过 `next_action_at_utc` 调度，不建立第二套预约任务系统或以内存队列作为事实来源。只有一个进程负责数据库迁移。

所有上游读写均通过 UpstreamContractAdapter 和 UpstreamRequestGate。AvailabilityService 为用户页面和两个 Agent 提供语义化信息；CandidateResolver 仅对当前某一次 bookingByTime 响应生成运行时坐标；BookingExecutionService 是唯一可以调用真实预约/支付副作用的服务。

当前目录的前端源码和后端可维护源码位置仍需在实施前确认；本规格不改变该基线梳理事项。前后端本地开发可分进程运行，生产访问使用受控同源 HTTPS/Tailscale 入口。

## 3. 人工与 Agent 共用的预约计划

### 3.1 ReservationIntent 与 PlanRevision

BookingPlan 只描述用户想预约什么。每个 PlanRevision 保存一个不可变的 ReservationIntent；不保存某次查询时的可用性或执行坐标。ReservationIntent 的最小结构包括：

```json
{
  "target_date": "YYYY-MM-DD",
  "venue_scope": {
    "venue_key": "用户选择的场馆语义键",
    "venue_query_nodeid": "bookingByTime 请求所需的场馆标识",
    "venue_label_snapshot": "仅用于展示"
  },
  "preferred_start_times": ["18:00"],
  "duration_minutes": 120,
  "booking_type": "契约支持的语义预约类型",
  "court_preferences": [
    {"semantic_key": "court-label:6", "label": "6号场", "priority": 1},
    {"semantic_key": "court-label:5", "label": "5号场", "priority": 2}
  ],
  "fallback_policy": {
    "allow_any_court_in_venue": false,
    "allow_time_shift": false,
    "allowed_start_time_range": null
  },
  "price_ceiling_minor": 5000
}
```

以上仅表达结构，不要求存在上游 `slot_id`。`venue_query_nodeid` 是调用 `bookingByTime` 所需的查询范围标识；它不能被解释成某场地的身份。`court_preferences` 使用用户选择的语义偏好和优先级，不保存历史 `nodeList[].nodeid`、`courtIndex`、`timeIndex`、`coordinatesList` 或历史价格。稳定场地目录只帮助用户识别和选择标签，不代表未来目标日该场地仍存在或可预约。

目标日、场馆范围、开始时间偏好、时长、预约类型、场地排序、可换场范围、可浮动时间范围、价格上限和用户明确授予的其他 fallback 范围共同构成 ReservationIntent。目标日期不可由 Agent 或执行器在任务中改变。时间浮动必须明确界定可接受的开始时间范围或有序时间偏好；时长不得自动变化。场地优先偏好可以按当前响应中明确匹配的语义名称解析；无法唯一匹配时跳过该偏好并记录原因，不使用模糊名称或历史 ID 猜测。

`price_ceiling_minor` 以最小货币单位整数表达当前 ReservationIntent 的最高可接受报价；币种由已验证的部署配置给出，不伪称为上游字段，也不作为用户自由输入的币种。缺少价格上限时仍可准备与报价，但不得因缺少上限而扩大自动支付授权；支付仍须通过 Credential、Job 和 ExternalOrder 的独立安全门禁。

计划使用 optimistic locking：用户或 Planning Agent 写入时携带期望版本；SQLite 事务检查版本后追加新 PlanRevision。版本冲突返回 409 并要求重新读取。PlanRevision 只追加，BookingPlan 仅推进当前版本指针。BookingPlan/PlanRevision 不包含 Credential、自动支付设置、Worker 状态或运行时 availability。

人工界面与 Planning Agent 通过同一个 PlanService：Agent 输出 Schema 化差异，用户确认后才能保存。Agent 必须展示新增、删除、改序和时间/场地 fallback 变化；破坏性或含糊修改需要用户确认。目标日尚未进入 T-2 查询窗口时，PlanService 仅校验语义结构并允许保存 `unresolved_future`；不调用上游、不将 UI 目录当作真实可用性。进入查询窗口后，页面可以显示当前观察结果，但保存的意图仍不固化该观察结果。已知硬排除项不能进入当次 PreparedQueueRevision 或 FinalExecutionQueue。

### 3.2 BookingJob 快照与执行授权

BookingPlan 与任务执行彻底分离。用户通过明确的人工作用创建 BookingJob；Planning Agent 和 Preparation Agent 都没有创建 Job 的工具。

创建 Job 时服务端固定 `plan_revision_id`、完整 ReservationIntent 的 `intent_snapshot_json` 和规范化哈希、`credential_id`、用户确认的 CredentialBookingProfileRevision、已建立的账户指纹、执行模式、支付授权边界及当时的 Policy/Adapter 版本。尚未通过只读验证或未建立账户指纹的 Credential 不能用于创建 Job，用户需先完成 Credential 验证。快照不含 Token 密文、JWT payload、实时 availability、价格、场地 nodeid、数组下标或上游坐标。修改计划只产生新 PlanRevision，不改变已创建 Job；要改变日期、时长、价格上限或授权范围，必须创建新 Job。

执行模式定义如下：

- `official_open`：用户授权在上游目标日期当前正式开放时执行。创建时可显示预计时间（当前已知常见值为 T-2 日 07:30），该预计值不是固定授权时间。`scheduled_for_utc` 为空；T-2 第一次合法查询返回开放时间后，Job 保存 `resolved_official_open_at_utc` 并据此更新 `next_action_at_utc`。后续有效查询若显示开放时刻变化，可以继续更新该字段和下一动作。
- `at`：用户明确指定精确的 `scheduled_for_utc`。创建时按当前 BookingWindowPolicy 校验；查询窗口已开时使用当前响应，否则使用已验证的预计开放基准作初步校验。该值不可自动修改。运行时若当前上游开放时刻晚于用户指定时间，Job 不得静默改到新时刻；转入 `awaiting_human`，要求用户取消并按新意图创建任务，或由用户明确采取新的任务创建动作。
- `now`：仅当服务端当前 BookingWindowPolicy 和最新 availability 都允许真实预约时接受；否则返回明确拒绝，不将请求排队成另一个执行模式。

所有模式的初始 `next_action_at_utc` 在目标日 T-2 之前指向 `query_open_at_utc`。若目标日 T-2 已过去，Job 立即进入只读准备/窗口复核，不重复等待 T-2。`official_open` 只用于尚未到达的正式开放时刻；开放已发生时，用户应选择当前允许的 `now` 或明确 `at`，不能把过去的开放时刻伪装成未来计划。`at` 保留精确时间但须在正式执行前复核窗口。API 不得将远期意图解释成“立刻执行”。

任务固定 Credential 身份和预约资料 revision，但不固定旧 Token 密文。Worker 每次上游操作前读取该 Credential 当前最新 Token，并确认该 Token 最近通过安全只读验证、尚未过期、账户指纹与 Job 创建时一致、Credential 未软删除/停用。用户轮换同一账户的 Token 不改变 Job 授权；账户指纹变化或无法证明连续性时暂停，不得用新账户代替原账户。

BookingJob 创建使用请求级 `Idempotency-Key`。相同用户、操作、key 和规范化请求体只创建一个 Job；相同 key 携带不同请求体返回 409。记录至少保留到任务与客户端重试窗口结束。

### 3.3 状态与用户授权快照

Job 创建时固定用户意图和支付授权。当前 Credential 策略收紧时立即生效；后续放宽不能扩大旧 Job 的授权。预约价格上限、支付上限和币种均使用最小货币单位整数和显式币种；有效门槛取用户 Intent、Job 快照和当前 Credential 策略中最严格的值。

## 4. Agent 的职责与工具边界

### 4.1 Planning Agent

Planning Agent 将用户自然语言转换为 ReservationIntent 的结构化差异，例如“星期日 18:00–20:00，6 号场优先、5 号场第二”。它只读取当前用户的计划、版本、BookingWindowPolicy 和必要的 AvailabilityService 语义结果；查询窗口外不得探测未来 availability。Agent 生成的修改必须由用户确认并经 PlanService 保存为新的 PlanRevision。它不能创建或修改 BookingJob。

### 4.2 Preparation Agent

T-2 查询窗口开启后，Worker 可以把当前 Job 的不可变 ReservationIntent，以及 AvailabilityService/UpstreamContractAdapter 已归一化的当日候选状态，交给受限 Preparation Agent。它可生成 `PreparedQueueProposal`：在合法范围内重新排序候选、按用户预先授权的场地范围扩展备用场地，或比较和排列用户允许的时间浮动方案。`priceList` 只能提供准备阶段的参考价格；最终可否预约和金额上限必须在正式开放时重新检查，并以当前 getPayPrice/订单结果为准。

Preparation Agent 只看到语义化目标、候选显示标签/稳定内部偏好键、占用类别、时间段、当前窗口状态和必要的价格区间；不读取原始 req、Token/JWT payload、个人资料、原始 HTTP JSON、原始 `conflictList`、node/time 数组下标或 `coordinatesList`。它没有任意 HTTP 客户端、Credential 写入、JobService、支付服务或数据库能力，也不能调用 createBooking、getPayPrice、支付或其他上游接口。

所有提案必须由确定性的 QueuePolicyValidator 对照不可变 ReservationIntent、当前目标日响应和服务端规则校验。校验至少覆盖日期、场馆、时间浮动范围、时长、场地 fallback 授权、价格上限、重复项、上游冲突/硬排除、`mintimeselect`、`maxtimeselect` 和 `maxAppointmentNodeNum`。越界提案不落入可执行队列，标记为 `awaiting_user_confirmation` 并解释边界；改变已冻结 Intent 的建议需用户另建 PlanRevision 和 BookingJob。

Preparation Agent 不在正式开放关键链路内同步运行。准备阶段 Agent 超时或不可用时，QueuePolicyValidator 仍从 ReservationIntent 构建确定性基线队列；只要至少一个用户明确授权候选合法，Job 就可以在正式开放时继续。开放时不等待 LLM，也不使用 LLM 解释原始冲突代码或决定是否发送副作用。

### 4.3 共享权限隔离

Planning Agent 和 Preparation Agent 均由后端以当前 Session 的 `user_id` 限定数据范围；模型不能提交或覆盖 `user_id`、`credential_id` 或 `job_id` 所有权。用户 A 的意图、PreparedQueueRevision、Agent 上下文、Credential、Job、订单与 Token 状态不得进入用户 B 的上下文。Agent 输出是非可信提案，必须过 Schema、权限和 QueuePolicyValidator 校验。

Agent 工具面不包含创建、调度、取消或恢复 BookingJob，修改 Credential、自动支付、支付上限、Token、Provider、邀请或会话设置，以及真实预约/支付副作用。上游文本也按不可信输入处理，不能改变工具权限。

## 5. 预约执行与任务调度

### 5.1 BookingWindowPolicy：查询窗口与动态正式开放

服务端使用唯一的 `BookingWindowPolicy` 和配置的 IANA 业务时区 `BOOKING_TIMEZONE`（默认 `Asia/Shanghai`）。所有日期先按业务时区本地日历计算，再转换为 UTC；浏览器和操作系统时区不参与开放判定。

对目标预约日期 T：

- 目标日首次查询时间基准为 T-2 日 00:00。每天 00:00 的通常可查范围为当天、明天、后天；“后天”是 D+2。用户可在任意更早日期保存未来 ReservationIntent，但 T-2 00:00 前不得调用 bookingByTime。
- T-2 00:00 后，Worker 以任务 Credential 查询 bookingByTime。`bookingstartdate`/`bookingenddate` 必须按当前契约校验并确认 T 在响应范围内。不同日期返回的合法日期范围和列表内容可以变化，不将旧响应沿用到新日期。
- 正式预约开放时间由当前目标日响应的 `bookingstarttime` 决定。远期任务创建时的已知 07:30 仅为预计展示值；首次 T-2 查询后，系统把该值与业务日期组合得到实际 `resolved_official_open_at_utc`，并调整 official_open Job 的 `next_action_at_utc`。之后任一新的合法准备响应若给出另一个有效时刻，继续更新调度。若确认的开放时刻已到或已过，但当前窗口和目标场次仍有效，official_open 立即进入最终实时查询；如果窗口/场次已失效，则暂停或结束，不能按旧时刻盲目执行。时间值变化本身不构成 contract drift。
- `bookingendtime` 和每日预约窗口按当前有效响应解释。预约副作用同时要求当前业务时刻落在有效写窗口、目标日期仍被当前上游支持、场次尚未开始、实时场地仍可预约。支付另按订单状态与支付端点有效期校验，不无证据地把预约截止套给支付。
- `execution_mode=at` 的精确时间不可被 `bookingstarttime` 变化自动改写。若实时开放晚于精确时间或目标时段已不可预约，任务暂停要求用户处理，不替用户更改授权。
- `can_query`、`can_book`、`can_pay` 和 `can_mutate_upstream` 由该服务按当前时间和动作统一返回。Vue、API 路由、Agent 和 Worker 不得各自重写门禁。
- 只有字段缺失、类型/结构变化，或已验证字段语义发生无法解释的变化时才进入 `contract_drift`。`nodeList` 顺序、`timeList`、冲突、价格、合法开放时刻和合法日期范围在不同目标日期间变化属于业务数据变化，不能仅因值不同就判为协议漂移。

`BookingWindowPolicy` 的返回至少包括业务时区/日期、默认目标日期、目标日、query_open_at、预计及已解析正式开放时间、当前每日预约窗口、`can_query`、`can_book`、`can_pay`、contract 状态和 reason_code。示例：星期一 00:00 后可查星期一/二/三；星期日目标日 T 的查询基准为星期五 00:00。T-2 日基于明确日期计算，禁止由“第三天”文字推导日期偏移。

### 5.2 BookingJob、Preparation Window 与执行队列

所有任务使用同一个 SQLite BookingJob 表、状态机、租约和 Worker 调度器。Job 状态与执行 phase 分开：

- phase：`waiting_query_window`、`credential_preflight`、`preparing`、`waiting_booking_open`、`final_resolving`、`getting_price`、`creating_booking`、`processing_payment`、`recovering`。
- status：`queued`、`running`、`awaiting_human`、`cancel_requested`、`succeeded`、`failed`、`cancelled`、`needs_attention`。

长期任务生命周期：

1. 用户任意提前天数创建 Job；状态为 `queued/waiting_query_window`，保留不可变 Intent 快照，不调用上游。
2. 到 T-2 日 00:00，Worker 领取任务并取得 Credential 执行锁，执行只读 Credential preflight（当前 Token、账户指纹、Credential 状态、预约资料完整性），随后调用 bookingByTime 获取该目标日真实数据。
3. 每次成功查询都经 Adapter 归一化，并生成当次 PreparationObservation。QueuePolicyValidator 先按 Intent 生成确定性基线队列；Preparation Agent 可异步给出提案。有效提案通过校验后，追加一条 `PreparedQueueRevision`，只保存语义候选顺序和引用的 observation，不保存可复用的下单坐标/价格。Agent 提案绑定产生它的 observation；如果结果返回时该 observation 已不是 Job 最新 observation，该结果只留作审计，不能成为 active queue。
4. 00:00 到实际 `bookingstarttime` 之间，`PreparationRefreshPolicy` 可安排多次低频刷新。每次新鲜查询可追加新的 observation 和 PreparedQueueRevision；历史 revision 不覆盖，Job 只推进“最新准备版本”指针。刷新间隔是服务级可配置策略，需依据 req、脱敏成功运行日志及 Retry-After/429 证据设置；不得使用 1 秒全局请求门禁作为轮询频率，不允许用户或多个 Credential 规避门禁。只要初始查询与开放时刻之间有足够窗口且未被上游退避阻断，策略至少安排一次开放前中间刷新；间隔不足时服从 gate/backoff，并保证开放时的最终刷新。Worker 每次只做一轮受控查询，释放锁后等待下一次 `next_action_at_utc`。
5. 每次响应都重新读取并解释合法 `bookingstarttime`。如果开放时刻改变，official_open Job 更新 `resolved_official_open_at_utc` 和下一动作；用户选了 `at` 时保持精确时间并在不兼容时暂停。
6. 到官方开放时，Worker 再次绕过缓存调用 bookingByTime，使用该次响应重算 occupancy、court/time 映射和所有价格相关状态；QueuePolicyValidator 以不可变 Intent 和最新合法 PreparedQueueRevision 的语义顺序生成本次 `FinalExecutionQueue`。准备阶段的任何 nodeid、下标、坐标、价格或可用性都不能直接复制到最终队列。
7. 最终队列通过门禁后，按 `bookingByTime → CandidateResolver → QueuePolicyValidator → getPayPrice → createBookingBytime` 的确定性路径执行；不等待 LLM，不添加无证据固定 sleep。CandidateResolver 只在此时从当前 `nodeList` 和 `timeList` 生成坐标。

`PreparedQueueRevision` 是 BookingJob 的派生准备状态，不修改 `PlanRevision` 或 `intent_snapshot_json`。没有有效 Agent 提案时，用用户明确的候选顺序和已授权 fallback 构建队列。只有通过授权校验的候选能进入队列；硬排除、协议未知或超出用户范围的提案不能被执行。

`FinalExecutionQueue` 绑定最新查询的响应指纹、Adapter 版本、Job lease epoch 和本次执行 attempt，只服务于当前开放时尝试。租约丢失、进程在副作用开始前崩溃或需要重新查询时，旧 FinalExecutionQueue 失效，Worker 必须再获取实时响应和重新解析。它可以用于审计本次实际下单坐标，但不得被后续尝试或另一个目标日重用。

### 5.3 Worker 租约与 Credential 执行锁

Worker 领取任务和获取 Credential 锁必须在同一个 SQLite `BEGIN IMMEDIATE` 事务中完成。记录持久化 lease owner、到期时间、heartbeat 和递增 epoch；同一 Credential 同时最多执行一个任务。网络调用期间不持有 SQLite 写事务；每次写回状态前校验 owner/epoch。接管过期任务先进入 `recovering`，不能因租约过期重发任何副作用。

同一 Job 的一次低频准备查询完成后可以释放 Credential 锁，等待时不占锁；每次刷新和正式执行都重新取得锁并使用 Credential 当前最新 Token。无未决副作用的 `awaiting_human` 可以释放锁；存在未知订单/支付副作用时保留恢复所需锁定，直到状态核实。停用或软删除 Credential 后不领取新任务；运行中任务在安全边界取消并核对。

服务级 Worker 并发上限较小且可配置。不同 Credential 可在该上限内并行；同一 Credential 串行。全局上游 gate 跨所有用户和 Token 共享。

### 5.4 JobStep、外部副作用与崩溃恢复

每个 Job 的只读检查、PreparationObservation、Agent 提案校验、CandidateResolver、getPayPrice、createBookingBytime、订单核对和支付都写入 JobStep。步骤记录稳定的本地 operation_id、状态、尝试次数、lease epoch、时间、脱敏结果摘要和关联 ExternalOrder，不保存原始 HTTP 请求/响应或凭证。PreparedQueueRevision 追加保存每次有效准备结果；FinalExecutionQueue 记录最终 attempt 使用的响应指纹和运行时解析。

JobStep 至少有 `prepared`、`in_progress`、`succeeded`、`failed_definitive`、`unknown`、`skipped`：

- bookingByTime、Token 只读验证、订单查询和契约允许的报价查询可按有限次数及全局退避策略重试；刷新查询按 PreparationRefreshPolicy 调度，不采用高速重试。
- createBooking、支付单创建、支付等副作用每次发送前先持久化 `in_progress` 和 operation_id。只有上游明确支持幂等时才传稳定幂等键，不能推定上游可安全重放。
- 副作用超时、断连、Worker 崩溃或结果字段冲突均视为 `unknown`：先查询上游订单状态。确认成功则恢复本地记录；明确证明未发生且契约允许时才能重试；无法确定则 `needs_attention`。
- createBooking 结果未知时不切换下一候选。只有 Adapter 已登记并能证明“本候选失败且未产生订单”的候选级业务失败才允许继续；每日预约额度等用户级终止错误不切换场地。
- HTTP 200 仍须按 endpoint-specific JSON success/message/resultData 判定。JobStep 和 ExternalOrder 不保存完整响应、Token、支付口令、二维码或未筛选个人资料。

### 5.5 可用性、CandidateResolver 与上游请求门禁

AvailabilityService 是页面、Planning Agent、Preparation Agent 和 Worker 读取场地状态的唯一入口。它返回业务语义状态、目标日期、查询时间、当前窗口和 reason_code；不返回原始 HTTP JSON、原始 `conflictList` 或 `coordinatesList`。不同日期的结果严格按日期/用户/凭证隔离，过期缓存只允许用于历史展示。

CourtResolver 根据 ReservationIntent 中用户选择的场地语义偏好，检查**本次** `nodeList[].sitename` 的精确规范化匹配，并取该当前数组项的 `nodeid` 和下标；名称规范化规则由版本化 Adapter 固定，只允许明确的空白/Unicode 规范化或显式别名，不做模糊匹配、相似度推断或跨日期复用旧 ID。相同语义标签匹配多个当前场地时 fail closed。若用户允许同场馆任意可用场地，执行器可按本次 `nodeList` 逐项扩展，并仍受用户范围和上游 `maxAppointmentNodeNum` 限制。

TimeResolver 只按当前 `timeList[].time` 精确匹配用户授权的开始时间。一个时间段必须由当前列表中的连续槽组成，且满足本次响应的 `mintimeselect`、`maxtimeselect`、`stepnumber` 与时长规则。解析完成后才生成 `${courtIndex}-${timeIndex}`。上游坐标只存在于本次 FinalExecutionQueue 和调用栈，不写入 ReservationIntent、PlanRevision、PreparedQueueRevision 或 AvailabilityCache。

已确认的活动、体育课、体训队、艺术团、项目培训、工会活动、其他活动、已预订和不可预约状态均为硬排除项。活动代码按第 8 节官方前端映射处理；未知代码、重复 ID/时间、响应类型异常或无法唯一映射均 fail closed。不能把未知状态解释为可用。

目标日 T-2 00:00 以前，PlanService 只保存语义 Intent 并显示 `unresolved_future`；不会用 UI 场地目录、旧价格或历史 availability 做验证。00:00 后用户看到的查询数据仍是当时观察值；PreparedQueueRevision 明确标为准备信息，历史准备数据不能作为未来或正式开放时下单证据。正式开放查询始终绕过缓存。

`UpstreamRequestGate` 以 SQLite 持久化全局端点间隔、在途锁和 Retry-After/backoff，跨 API、Worker、Agent、所有用户和 Token 生效。已观察的成功运行最短同端点间隔可作为门禁配置证据，但门禁最小间隔不是 PreparationRefreshPolicy 的刷新间隔。所有刷新遵守服务级低频策略；收到 429/503 或 Retry-After 时跨 Credential 退避。查询超时可有限重试；副作用未知时必须对账而非重试。

### 5.6 awaiting_human、恢复与取消

`awaiting_human` 必须保存具体原因、关联 JobStep/订单、提示和允许的用户动作。Token 即将过期、Token 验证失败、资料缺失、用户验证码操作、精确 `at` 时间与真实开放变化不兼容、报价超出 Intent 价格上限或自动支付关闭，均显示明确原因。

恢复请求只记录用户完成人工作用或要求继续核对，不代替支付授权。Worker 恢复后重新取得锁并检查 Credential 最新 Token、指纹、资料、Job 快照和订单状态；不得从旧步骤盲目续跑。订单/支付状态未知时继续 `needs_attention`，不发起重复副作用。

用户取消 queued Job 可置本地 `cancelled`；取消 running 或存在外部不确定操作的 Job 先写 `cancel_requested`，Worker 在安全边界停止后续副作用并核对已创建订单。`cancelled` 只说明本地执行器停止，不表示上游订单取消或退款。

### 5.7 支付与自动支付门禁

自动支付仍由用户在 Credential 设置中单独开启，默认关闭；Intent 或 Agent 不能开启。支付前比较当前 getPayPrice/订单实际金额、ReservationIntent 价格上限、Job 冻结授权、当前 Credential 上限和有效币种，取最严格限制。金额变化、字段缺失、币种未知、订单未确认或状态不确定时暂停。

实际金额使用最小货币单位整数；当前 req 未显示 currency 字段时，币种只来自经过确认的部署级契约配置，不冒充上游响应字段。若 getPayPrice 返回金额超过当前 Intent 价格上限，该候选在 createBooking 前被安全跳过，可按用户授权尝试下一个候选；全部候选均超限时等待用户决定是否创建新 Intent/Job。自动支付要求 Job 快照允许、当前 Credential 仍允许、订单状态已核实、价格符合用户上限且没有需确认变化。一次性人工支付批准必须绑定同一订单、精确金额/币种、操作者和过期时间，只能用一次。调高 Credential 上限不扩大旧 Job 快照授权。

每个预约和支付副作用发送前都重新检查 BookingWindowPolicy 和实时执行条件；准备窗口内绝不调用 createBooking、支付单创建或支付。支付状态不确定时先对账，不能再次支付。

## 6. 数据与隔离

主要实体与约束：

- **User / Session / Invitation**：用户、可撤销服务端 Session 和单次邀请码；会话 ID 与邀请码只存哈希，兑换原子完成。
- **Credential**：`user_id`、标签、当前加密 Token、Token revision、`token_expires_at_utc`、到期/验证状态、`last_validated_at_utc`、`last_validation_result`、不向用户/Agent 暴露的 `upstream_account_fingerprint`、启停状态、支付策略、`deleted_at`。Credential 持久化到期状态；`will_expire_before_job` 是按 Credential+Job 计算的状态投影。不得将多个 Job 的风险混成一个全局 Credential 结论。不保存完整 JWT payload；轮换成功后当前密文替换，不把旧 Token 密文写入 Job。
- **CredentialTokenRevision**：仅保留 Token 版本号、不可逆本地指纹、解析到期时间、验证结果/时间和操作者等审计元数据，不保留旧 Token 或 payload。
- **CredentialExecutionLock / CredentialPolicyRevision**：每 Credential 一个持久化执行锁；策略修改保留版本和审计。
- **CredentialBookingProfileRevision**：加密的预约参与人字段、内容哈希和版本。Job 固定用户确认的 profile revision；普通 API 只返回脱敏摘要，Agent 不可读取。
- **BookingPlan / PlanRevision**：用户计划与不可变版本。PlanRevision 的规范化内容是 ReservationIntent，不含运行时 availability、历史场地 nodeid、坐标或价格。
- **BookingJob**：`user_id`、`plan_id`、`plan_revision_id`、`credential_id`、Job 创建时账户指纹、固定 profile revision、不可变 Intent 快照/哈希、Adapter/Policy 版本、`execution_mode`、`scheduled_for_utc`（只用于 at/now 的用户指定时刻）、预计/已解析开放时间、可变 `next_action_at_utc`、status/phase、最新 PreparedQueueRevision 指针、lease/recovery 字段及安全错误摘要。快照不含 Token 密文或运行时场地/时间坐标。
- **PreparationObservation**：某 Job/用户/目标日期的一次已归一化只读查询摘要，包括 contract version、fetched_at、响应指纹、目标日范围、开放时间、候选状态摘要和必要价格显示信息；不保存原始请求/响应、个人资料或可执行坐标。带 `write_eligible=false`，过期后只用于审计/展示。
- **PreparedQueueRevision**：`user_id`、`job_id`、递增版本、源 PreparationObservation、Intent 哈希、确定性/Agent 来源、语义候选顺序与时间备选、QueuePolicyValidator 结果、创建时间。追加不可变，不含可复用的 court/time 数组下标、coordinatesList 或可作为正式成交报价的价格。
- **FinalExecutionQueue**：每个开放执行 attempt 的响应指纹、Adapter 版本、lease epoch、解析后的当前坐标和语义候选顺序。只用于该 attempt 的审计和即时执行；租约/attempt 失效后不得重用，副作用未开始且恢复时需重新查询。
- **AvailabilityCache / UpstreamRequestGate**：AvailabilityCache 只服务短时 UI 展示且按 user/credential/date/venue 隔离；Gate 是跨用户、跨 Token 的服务级 SQLite 状态，记录端点间隔、在途锁和退避时间。历史缓存不得被当作未来执行事实。
- **IdempotencyRecord**：`user_id`、API 操作、请求 key、规范化哈希、Job ID 和保留时间；同一 key 与内容唯一。
- **UserLLMConfig**：按用户隔离的完整 Provider 配置；API key 加密，不做跨 Provider 字段回退。
- **JobStep / ExternalOrder / JobApproval / JobEvent**：副作用步骤、最小订单状态、一次性人工作用授权和追加式状态审计；不保存完整 HTTP 响应、Token、支付口令或二维码。

所有用户数据表带 `user_id`。API SQL 必须在数据库查询中绑定当前 Session 的 `user_id`，关联对象使用复合外键/唯一约束防止跨用户引用；禁止先按资源 ID 无范围读取后再在 Python 层校验。Worker 处理任务时继续校验 Job、PlanRevision、Credential、profile、PreparedQueueRevision 和订单归属。Service 级 gate 不属于某一用户，Agent 不能读取或修改它。

SQLite 每个连接启用 `PRAGMA foreign_keys=ON` 和 busy timeout；数据库用 WAL；迁移使用有序版本文件和 schema_migrations 表，失败不删除用户数据。不可变快照、Revision、JobStep、订单审批与事件采用追加式语义，并以应用校验及必要约束共同保证。

所有事件时间、租约和到期时间用 UTC Unix 毫秒存储，API 用 RFC 3339 UTC；预约目标日期与本地时间按冻结的 `BOOKING_TIMEZONE` 解释。更换业务时区必须显式迁移，不能改变已保存意图和 Job 的含义。

## 7. 认证与凭证保护

- 初始管理员通过本地 CLI 创建；普通注册必须使用管理员创建的高熵、单次、可过期邀请码。密码用 scrypt 哈希；登录与兑换做基于 SQLite 的速率限制。
- 使用真正可撤销的服务端 Session：Cookie 仅含高熵不透明 ID，SQLite 保存其哈希和用户、到期、撤销、CSRF 元数据。登录轮换 Session；注销、过期、管理员禁用用户或密码变更撤销 Session。不能仅依赖 Flask 默认客户端 Cookie Session。
- Cookie 设置 HttpOnly、SameSite=Lax 或更严格策略；生产 HTTPS 下 Secure。基于 Cookie 的修改请求使用会话绑定 CSRF，并校验 Origin/Referer。
- Token、支付凭证、Credential profile 与 LLM API key 以应用密钥加密存储；密钥来自受保护环境配置/密钥文件，绝不进 SQLite、Git、日志或 LLM。只在后端短时解密。
- Credential profile 中的 reservationPerson、childrennum、accompanyPerson/followList 等字段只允许用户本人维护和 Worker 执行时读取；不进入 Agent、普通 API、日志或错误响应。
- 使用经过审查的认证加密方案和密钥版本，不自制算法。上游 AES 参数与本应用密文密钥完全分离。
- Credential 软删除后立刻从列表隐藏并禁止新任务；有未知 JobStep/ExternalOrder 时保留恢复所需的当前密文并禁止新副作用，无未决引用后可清除密文并保留无秘密审计墓碑。软删除不等于在上游撤销 Token。

### 7.1 Token 到期元数据与验证

本地 req 中的上游 Token 观察为 JWT 且有 `exp` 声明。CredentialTokenService 仅在 Token 新增/替换时解析必要的 `exp` 并转换成 `token_expires_at_utc`；本地解析不验证签名，也不代表 Token 真正有效。不得保存或展示完整 JWT payload、payload 副本或非必要 claim。畸形/无 `exp` 的 Token 将到期状态设为 `unknown`，仍需只读验证。

Credential 的 `token_expiry_status` 与 Job 关联风险显示以下状态：

- `valid`：最近一次安全只读验证成功且预计过期时间不在提醒阈值内。
- `expiring_soon`：预计在服务端配置的提醒窗口内到期；提醒窗口为服务配置，默认 7 天。
- `will_expire_before_job`：对某个排队 Job 而言，`token_expires_at_utc` 早于该 Job 的 T-2 preflight 或实际执行时刻；这是 Credential+Job 关联风险，不能误作所有 Job 共用的 Token 固有状态。
- `expired`：本地 `exp` 已到或过去；立即禁止上游预约/报价/支付写操作，先要求用户更新并验证。
- `invalid`：安全只读验证明确返回凭证无效/未授权；禁止该 Credential 的所有上游业务操作，直到重新验证成功。
- `unknown`：无可解析 `exp`，或当前只读验证状态不足以确认有效性。产生副作用前必须完成并通过最新的安全只读验证；如果验证成功但 `exp` 仍不可解析，继续显示到期未知并提示用户，但可按 T-2 preflight 和其他门禁结果判断是否执行。

`last_validated_at_utc` 只记最近一次成功的只读验证时刻；`last_validation_result` 使用白名单状态码和脱敏摘要，不保存完整响应。可在新增/替换 Token、用户主动点击验证、以及 T-2 `credential_preflight` 时验证。只读验证必须来自 req 已确认的安全端点/流程；不可用预约写接口做 Token 探测。

### 7.2 Token 替换、账户连续性与 Job preflight

新 Token 先作为待验证输入在内存中处理：解析 exp、执行安全只读验证并从经过白名单的稳定上游账户标识生成服务端 HMAC 指纹。原始标识只在内存中用于计算，指纹不得展示给用户或 Agent。首次验证成功才建立 Credential 指纹。

替换已有 Token 时，后端必须确认新 Token 的账户指纹与 Credential 既有指纹相同，验证成功后才原子替换当前加密密文、增加 Token revision、更新 expiry/validation 元数据。若指纹不同，拒绝覆盖现 Credential，提示用户创建新的 Credential；若上游不能提供足以确认同一账户的身份字段，连续性为 unknown，不能自动替换。旧 Token 密文不复制到 BookingJob，也不因创建 Job 而冻结。

BookingJob 固定 `credential_id`、用户授权和账户指纹，不固定 Token 密文。Worker 每次请求前使用 Credential 最新 Token，并确认 Token 最近只读验证成功、账户指纹仍匹配、Credential 未停用/软删除。T-2 preflight 同时检查 profile revision、必要字段、Token 状态和账号连续性；失败则在正式开放前设置 `awaiting_human` 或 `needs_attention`，不执行后续预约。若预计 Token 会在准备/执行前到期，Job 创建时允许保留计划，但前端必须突出风险并提示更新。

### 7.3 到期提醒与隐私

用户登录后的主要页面显示只属于该用户的高优先级汇总提醒，列出 Credential 标签、预计过期/风险时间、关联 Job 和可操作的验证/替换入口。Token 已过期、验证失败或即将在 Job 前到期时使用醒目提示；不能显示 JWT、完整 payload、账户指纹或其他用户数据。提醒可暂时收起，但风险继续显示在 Credential 和 Job 状态中。

### 7.4 LLM Provider SSRF 与日志

LLM Provider 必须作为完整配置使用。custom base URL 与 custom API key 同属一个 Provider，不得混入服务级密钥。只允许受校验的 HTTP(S) 根 URL；生产远程 Provider 使用 HTTPS。拒绝 URL 用户名/密码、查询串、fragment、危险端口、非预期 scheme 和绕过校验的重定向。解析所有 A/AAAA 结果并拒绝 loopback、私有、link-local、保留、多播、云元数据、IPv4-mapped IPv6 等地址；不得接受公网与内网混合结果。防 DNS rebinding：每次请求都校验 DNS，并将连接绑定到已校验地址或通过等价受控出站策略限制目标；TLS 证书与 SNI 仍按原始主机名校验。禁止自动跟随重定向，或每一跳完整重新校验 URL/DNS/地址/端口；不能把 API key 转发到未经校验的目标。开发环境的 loopback 和 tailnet 私有例外仅限管理员配置的精确 Host/Port，不接受任意私有网段或用户自定义 localhost。Provider 保存与每次模型请求均须校验，并设置连接/读取超时、响应体大小限制和允许的协议路径。

统一日志采用字段白名单。禁止记录 Cookie、Authorization、JWT、Token、账户指纹、支付凭证、LLM key、完整 URL 查询参数、二维码、电话/身份标识、原始 prompt/响应或原始订单详情。诊断只使用人工合成 fixture 和脱敏摘要。

## 8. 上游接口与 req 抓包观察

本节以当前项目本地 `req/` 抓包和其中官方前端代码作为上游协议最高事实来源，辅以脱敏成功运行日志；旧 Python 实现、README、注释和历史规格不能覆盖这些证据。冲突时修改规格与 Adapter，不反向解释抓包。当前 Adapter 标识为 bdtyg-court-v1。不同目标日期的列表、价格和开放时间都是动态业务数据。原始 req、完整 JWT payload、解密值、个人字段和真实订单值均不进入 Git、fixture、日志、Agent 上下文或普通 API。

### 8.1 HTTP 封装与可见字段

- 上游接口使用 POST JSON；认证头为 token。Token 当前观察为带 `exp` 声明的 JWT；本地仅解析 `exp` 形成到期提醒，不保存/展示 payload，不以未验签解析结果当作有效性证明。Token 的真实有效性必须通过安全只读验证。外层请求体为 item 字段，内容是内层 JSON UTF-8 文本按本机环境密钥执行 AES-CBC/PKCS7 后的十六进制字符串。密钥、IV 和 Token 只由本机 env 提供，Adapter 运行时短暂读取；不打印、不写日志、不进入快照。解密只用于本地契约分析，不保存解密产物。
- 所有响应均需解析 HTTP 状态及 JSON。标准外层响应为 success、message、resultData。HTTP 200 不代表业务成功；Adapter 必须按 endpoint-specific 的 success/message/resultData 组合分类。

### 8.2 bookingByTime 与场地/时间坐标

- 请求路径为 /service/appointment/appointment/phone/bookingByTime；内层字段为 nodeid（上游场馆 nodeid）和 selectdate（目标日期）。
- 已观察的 bookingByTime 成功组合为 success=true、message=CORE10008，resultData 字段为 timeList、mintimeselect、conflictList、maxAppointmentNodeNum、bookingstartdate、bookingenddate、start、end、isNew、bookingstarttime、nodeList、priceList、maxtimeselect、bookingendtime、stepnumber。字段缺失、类型或结构发生未登记变化时返回 contract_drift，不猜测字段。
- nodeList 元素为 sitename 与 nodeid。顶层请求 nodeid 是用户所选场馆查询范围；nodeList[].nodeid 是当前响应中单个场地的身份。ReservationIntent 可固定用户选择的场馆查询范围，但不能固定场地 nodeid。每个目标日期都必须重新读取 nodeList，并以当前 `sitename` 的版本化精确语义匹配解析场地偏好；目录和旧响应只用于 UI/审计，不是执行事实。
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
- booking 坐标字符串固定为“场地下标-时间下标”，即 courtIndex-timeIndex。该下标只对生成它的那一次响应有效。两小时预约由 CandidateResolver 从当前 timeList 找到精确起始时间与连续后续时间槽，为同一场地生成两条坐标；禁止跨缺口、按近似时间匹配或复用旧坐标。最终开放时重新查询后重新生成坐标。
- priceList 元素为 price、x、y。官方前端按网格行/列查询价格，其中 x=timeIndex、y=courtIndex；这与 booking 坐标 courtIndex-timeIndex 顺序相反。priceList 只用于当前可用性展示，不是支付金额的最终来源。
- bookingstartdate/bookingenddate 与 bookingstarttime/bookingendtime 是本次响应声明的范围和窗口。当前样本中曾观察到 bookingstarttime=07:30、bookingendtime=23:00；其他目标日期可以返回不同的合法时刻/范围。只要字段结构、类型和已验证语义保持一致，值变化时 BookingWindowPolicy 更新 official_open 调度，不判为 contract_drift。start/end 与 isNew 原样保留；start/end 不替代 booking 时间。服务端不得由未验证的 isNew 组合放宽门禁。

### 8.3 报价、创建与业务结果

- getPayPrice 路径为 /service/appointment/appointment/phone/getPayPrice。当前解密请求字段为 nodeList、nodeid、reserveTime、reserveDate、accompanyPerson、reservationPerson、appointmentType、timeList；当前捕获值和官方前端均显示 appointmentType 为字符串 2。reserveTime 使用当前生成的 coordinatesList 字符串数组，nodeList/timeList 必须来自同一次最新 bookingByTime 响应。reservationPerson 来自上游账户资料，只能由后端 Credential 上下文提供，不能进入 Agent 或普通 API。
- 已观察的成功 getPayPrice 响应为 success=true、message=“成功”、resultData 含 pricemap 与 txamt；txamt 是字符串报价。成功字段缺失、金额无法安全解析或响应不符合该组合时不得创建订单。
- createBookingBytime 路径为 /service/appointment/appointment/phone/createBookingBytime。当前真实解密请求字段为 nodeList、payprice、isLastDay、appointmentDate、timeList、coordinatesList、booktype、nodeid、childrennum、followList、txamt、payway；捕获的收费预约路径中 booktype 为数值 2、payway 为字符串 77。官方前端代码对免支付分支设置 payway=72，但当前 req 没有该分支的线上请求证据；Adapter v1 不得据此自动发送免支付请求，需等新 req 和契约 fixture 确认。booktype 是上游预约类别代码，不等于 one_hour/two_hour；时长由 coordinatesList 中连续 timeList 项数量表达。各字段类型由脱敏 fixture 固定。官方前端还有 unitPrice/id 等局部字段，但它们未出现在当前真实解密请求样本中，Adapter v1 不得因前端临时对象含有这些字段就把它们添加到线上请求；只有新 req 证据和契约升级后才能增加。
- 已观察到 createBookingBytime 的成功组合为 success=true、message=CORE10008、resultData 含 orderno 与 txamt；CORE10008 在该组合下不是失败。已观察的业务失败组合为 success=false、message=“每人每天最多预约1次”，属于用户/每日额度终止错误，不能换场地重试。其他 message/字段组合一律 unknown/contract drift，先按订单接口对账，不得尝试下个候选。
- 预约副作用只用刚才实时 bookingByTime 的 nodeList、timeList 与刚解析的 coordinatesList；getPayPrice 与 createBookingBytime 之间不再查询其他无关数据，不加入没有证据的固定 sleep。
- openPlatFormPayOrder 当前抓包的内层字段含 txamt、orderno、payway、password。password 是支付秘密，只可按原有支付安全策略短时解密使用；任何 snapshot、JobStep、ExternalOrder、日志、Agent 和响应均不得保存或返回该值。已观察支付响应为 success=true/message=“支付成功”，但支付结果仍须通过 payOrderForPhone/payOrderDetails 权威核对，HTTP 状态或单条提交响应都不代表最终已支付。
- payOrderForPhone 的请求字段为 pageNumber、pageSize、ordertype；payOrderDetails 的请求字段为 bookingno、id。订单核对只投影匹配所需的 orderno、bookingno/id、status、paytime、金额等字段；完整结果含身份、联系方式、二维码和其他个人字段，禁止向 UI/Agent/日志透传。图片验证接口/图片资源说明流程存在人工验证；不破解、不模拟、不绕过。

### 8.4 UpstreamContractAdapter、准备刷新与 fixture

- Adapter 将外层加密传输、endpoint-specific Schema、业务结果分类、冲突码映射与当前响应的 CandidateResolver 隔离。版本升级保留旧版本用于审计，不允许旧任务把历史运行数据当作新日期执行依据。
- bookingByTime 的 `nodeList`、`timeList`、`conflictList`、`priceList`、开放日期/时刻和价格均按每次目标日期查询重新取得。PreparationObservation 只保存脱敏归一化摘要；正式开放 FinalExecutionQueue 必须引用当次绕过缓存的响应。
- 成功日志曾观测到约 668ms 的最短同端点启动间隔，未发现 429/Retry-After；该观测只支持 UpstreamRequestGate 的最低端点间隔设置，不代表上游承诺，也不是准备轮询间隔。准备刷新间隔由服务级 PreparationRefreshPolicy 配置并依据成功日志/上游响应调整；必须是低频、跨 Credential 共用 gate，受 429/Retry-After 冷却约束，用户和 Agent 无权缩短。
- 脱敏 fixture 必须人工合成。覆盖同一契约下不同目标日期的 node/time/conflict/price 顺序变化、合法 bookingstarttime 变化、可用性和价格变化、场地名称无法唯一匹配、时间缺口、冲突类型 1-7/未知值、报价业务结果、创建成功/失败及结构漂移。合法业务值变化应刷新运行时解析而非触发 contract_drift。
- fixture 不复制真实 nodeid、用户日期、价格、姓名、订单号、JWT、item 密文、Token、支付口令、二维码或可重放值。只允许字段白名单、类型和结构进入测试素材。
- 每个 fixture 只证明其覆盖的契约边界。未知类型、字段类型/结构变化、业务 message 未登记等 fail closed；不得通过 LLM 猜测并继续执行。真实预约和支付不作为自动化测试对象。

## 9. API 草案

认证与邀请：

- `POST /api/admin/invitations` 创建单次邀请码；`GET/DELETE` 只读取状态或撤销未使用邀请码。
- `POST /api/auth/register` 原子兑换邀请码并创建账户；`POST /api/auth/login`、`GET /api/auth/session`、`POST /api/auth/logout` 管理服务端 Session。

Credential 与 LLM：

- `GET/POST /api/credentials` 查询脱敏状态或创建 Credential；`PATCH/DELETE /api/credentials/{id}` 修改标签/启停/支付策略或软删除。
- `POST /api/credentials/{id}/token` 添加 Token；`POST /api/credentials/{id}/rotate-token` 验证并轮换同一账户 Token。请求体只在 TLS/服务端短时处理 Token；响应只含状态、预计过期时间和脱敏验证结果。
- `POST /api/credentials/{id}/validate` 只读验证当前 Token；`GET/PUT /api/credentials/{id}/booking-profile` 获取脱敏摘要或追加 profile revision。
- `GET/PUT/DELETE /api/llm/settings` 读写当前用户完整 Provider；`POST /api/llm/test` 仅由用户主动调用，并执行 SSRF 校验。

预约窗口与可用性：

- `GET /api/booking-window?target_date=YYYY-MM-DD` 返回业务时区、默认目标日、三日查询窗口、T-2 查询时间、预计开放值、已由当前响应确认的开放值以及服务端 `can_query/can_book/can_pay`。开放值可随新合法响应更新。
- `GET /api/availability?credential_id=...&target_date=...` 在 T-2 前返回 `unresolved_future` 而不调用上游；进入窗口后返回语义场地/时段状态、来源查询时刻、窗口状态和硬排除原因，不返回数组坐标或原始冲突数据。查询受全局 gate 约束。

计划与 Agent：

- `GET/POST /api/plans`、`GET/PATCH /api/plans/{id}` 和 `GET /api/plans/{id}/revisions` 管理 BookingPlan/ReservationIntent；更新必须携带 base_version/If-Match。
- `POST /api/plans/{id}/agent-edits` 提交 Planning Agent 的语义差异，经用户确认、Schema、权限和 optimistic locking 后由 PlanService 保存；不接受 job、Credential、支付、Token、坐标或调度字段。
- Preparation Agent 仅由 Worker 内部以隔离工具面调用；没有可由浏览器直接调用的创建队列接口。

任务与订单：

- `POST /api/jobs` 仅在用户明确确认时创建，要求 `Idempotency-Key`；请求含 plan/revision、credential、profile revision、`execution_mode`（`official_open`、`at`、`now`）和支付授权。`at` 必须给精确 `scheduled_for_utc`。`official_open` 可任意提前创建，初始 `next_action_at_utc` 指向 T-2 00:00，并返回预计开放时间与 `unresolved_future`；开放预计值不冻结。
- `GET /api/jobs`、`GET /api/jobs/{id}` 仅返回当前用户状态、phase、下一动作、Credential 到期风险、语义快照摘要和 JobStep 摘要。
- `GET /api/jobs/{id}/preparations` 返回用户自己的 PreparedQueueRevision 历史、刷新时间、Agent 提案摘要和 validator 结果；不返回历史 coordinatesList、下标或原始响应。
- `POST /api/jobs/{id}/cancel` 运行中先写 `cancel_requested`；`POST /api/jobs/{id}/resume` 只记录用户人工作用，恢复前重新检查 Token、订单和安全门禁。
- `POST /api/jobs/{id}/payment-approvals` 创建绑定订单/精确金额/币种的一次性人工批准；`GET /api/external-orders` 只返回当前用户最小订单状态。

除注册、登录及必要健康检查外，所有查询与修改必须要求应用登录并在 SQL 条件中绑定当前 `user_id`。管理员端点单独授权审计。客户端不能提交上游 Token、coordinatesList、原始请求、执行快照或账户指纹。所有 Cookie 修改操作校验 CSRF。

## 10. 前后端体验

前端应提供：

- 登录、邀请码注册，以及登录后只针对当前用户的高优先级 Token 风险汇总提示。
- Credential 列表展示标签、启停状态、预计过期时间/剩余时间、`valid/expiring_soon/will_expire_before_job/expired/invalid/unknown` 风险、最近安全验证时间和结果；不显示 Token、完整 JWT payload 或账户指纹。提供新增、只读验证和同账户 Token 轮换入口。
- 任意未来目标日的 ReservationIntent 编辑器：目标日、场馆语义范围、时间/时长、用户场地排序、是否允许同场馆备用、是否允许限定范围内时间浮动、最高可接受价格和币种。场地目录只用于帮助用户选语义偏好，界面明确标注“尚未按目标日期验证”。
- 日期窗口和开放时间由后端返回；前端不自行计算 T-2、午夜或 bookingstarttime。目标日未进入查询窗口显示 `unresolved_future`，不能把上次查询状态或历史价格当作当前可用。
- T-2 后的准备界面展示每次 PreparedQueueRevision 的查询时刻、数据新鲜度、候选增删/重排、硬排除原因、Preparation Agent 建议与 QueuePolicyValidator 结果。清楚标示为准备数据，绝不向用户显示可编辑/可复用的上游坐标。
- Agent 不可用时继续展示确定性队列；越出用户授权范围的 Agent 建议标为等待用户确认，并引导用户创建新的计划版本和 Job，不静默扩大当前 Job 授权。
- Job 创建页区分 `official_open`（跟随上游正式开放，展示预计值及“实际开放时间以 T-2 当前响应为准”）、`at`（用户精确时刻）和 `now`。预计开放时间被合法上游响应更新时，展示旧预计值/新确认值和调度变更原因。`at` 不被自动更改。
- 正式开放执行时显示当前查询/解析/报价/创建步骤和候选跳过原因；最终队列只对应本次最新查询，UI 不暴露 court/time 下标供用户编辑。
- 支付待确认时显示已核实订单、实际金额、币种、Intent 价格上限、Job 授权和 Credential 支付上限；不确定的状态没有可直接支付按钮。
- 统一任务列表显示 status、phase、next action、最新准备版本、Credential 过期风险、恢复/取消操作。Job 本地取消与上游订单取消分开呈现。
- 所有预约日期/时刻按业务时区展示，并显示该时区。

本地开发前后端分别运行，Vite 代理 API。生产使用同源 HTTPS/Tailscale 私有访问；CORS 仅允许明确来源，反向代理只信任明确配置的地址。

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

当前项目在本地 `main`，项目级 `.gitignore` 排除 `.env`、`req/`、运行日志、个人预约计划和 SQLite 数据/WAL。实施前仍需挑选唯一可维护源码、恢复或建立 Vue/Vite 源码并提交干净基线；重复打包目录、Windows 二进制、压缩包和个人数据不得进入基线。脱敏 fixture 必须人工合成。

完成干净基线后再建立功能 worktree（建议 `codex/multitenant-booking`），按以下垂直阶段实现；worktree 仅用于隔离开发，不改变应用技术路线：

1. **源码和启动基线**：确定唯一后端源码、前端源码位置、Conda `test` 环境依赖、启动与本地配置。
2. **数据库与认证**：SQLite WAL/foreign keys/migrations、用户、服务端 Session、邀请码、CSRF、所有权查询和日志脱敏。
3. **Credential Token 生命周期**：加密 Token、JWT `exp` 元数据、只读验证、账户指纹、同账户轮换、expiry 风险与登录提醒、T-2 preflight。
4. **语义预约计划**：ReservationIntent、PlanRevision、optimistic locking、用户场地语义偏好、明确 fallback/time-float/price ceiling、Agent 计划差异。
5. **任务与阶段调度**：BookingJob 不可变授权快照、`official_open` 动态开放、精确 `at` 模式、请求幂等、phase/next_action、lease 和 Credential 锁。
6. **契约与准备队列**：版本化 UpstreamContractAdapter、PreparationObservation、PreparedQueueRevision、受限 Preparation Agent、QueuePolicyValidator、多次低频 refresh policy、数组重排/值变化 fixture。
7. **最终执行与恢复**：开放时 uncached bookingByTime、FinalExecutionQueue、当前坐标解析、JobStep/ExternalOrder、副作用未知对账、awaiting_human、取消和支付安全。
8. **前端闭环**：预约意图、T-2 多次准备状态、Token 风险提示、official_open/at 区别、订单摘要和恢复操作。
9. **本地安全验证**：租户隔离、Token 过期/轮换/错账户、Job immutable snapshot、队列刷新和进程恢复、最新数据重新解析、限流共享、SSRF 和脱敏 fixture；不对真实预约/支付端点自动化测试。
10. **Tailscale 私有接入**：完成应用认证与 CSRF/CORS 后配置 Serve/ACL，仅授权 tailnet 成员可到达服务。

每个实施阶段须先有经用户审阅的实施计划；本规格不等同于实施授权。遇到上游缺少可靠对账能力时，采用 `needs_attention` 安全暂停，不盲目重放。

## 14. 验收标准

- 邀请码单次兑换、过期和撤销可用；并发兑换最多创建一个用户。登录态使用可撤销服务端 Session，注销后旧 Cookie 失效。
- 所有用户表、Credential、ReservationIntent、PreparedQueueRevision、Agent 上下文、BookingJob、订单和 API 查询按 `user_id` 隔离；用户 A 无法读取用户 B 任何资源。
- JWT `exp` 解析只保存到期时间和安全状态，不保存完整 payload；日志/API/Agent/UI 不含 Token、payload 或账户指纹。JWT 本地解码不能替代真实只读验证。
- Token 状态区分 valid、expiring_soon、will_expire_before_job、expired、invalid、unknown；expired/invalid 禁止真实上游预约与支付副作用。用户登录后看到仅含本人 Token 风险的高优先级提示。
- 同账户 Token 轮换先只读验证并核对账户指纹，成功后 Job 使用最新 Token；不同账户不能覆盖旧 Credential，必须建立新 Credential。无法确定账户连续性时 fail closed。
- Job 创建时固定 credential_id、账户指纹、profile revision 和用户授权，但不固定旧 Token 密文；T-2 preflight 在正式开放前发现 Token 失效、profile 缺失/无效或 Credential 禁用并暂停。
- 任意提前天数创建未来 ReservationIntent/Job 不调用 bookingByTime；PlanRevision 和 intent snapshot 不含历史场地 nodeid、数组下标、coordinatesList、availability 或价格。
- “星期一提前设置星期日 18:00–20:00，6 号场优先、5 号场第二”保存为语义偏好；本地场地目录仅供 UI 选项，不会使系统宣称场地已验证可用。
- T-2 00:00 开始调用目标日真实 bookingByTime；若开放前窗口足够且无上游退避，准备阶段至少再进行一次服务级低频刷新，并在开放时进行最终刷新。每次有效响应均可追加 PreparationObservation 和 PreparedQueueRevision，不覆盖旧 revision，也不改 PlanRevision/ReservationIntent/用户授权。
- 同目标日不同 refresh 的 nodeList/timeList/conflictList/priceList 顺序、可用性、价格和开放时间变化时，产生新准备状态，不把旧数组位置或旧价格当作事实。
- PreparedQueueRevision 只含语义候选顺序、来源、验证摘要及源 observation；其任何历史价格、坐标或状态都不能作为最终创建请求输入。
- Preparation Agent 只收到归一化数据，不接触 req 原文、Token、完整 JWT payload、个人资料、原始 JSON、conflictList 原码或 coordinatesList；不能调用 JobService、createBooking、支付或 Credential 设置。
- QueuePolicyValidator 拒绝日期、时长、场馆、场地、时间浮动或价格超出用户授权的提案；越界建议不生效并等待用户明确确认/创建新的授权 Job。
- Preparation Agent 不可用时，确定性 Intent 队列仍能执行；正式开放关键链路不等待 LLM。
- 00:00 至正式开放之间只做允许的只读查询、preflight、语义解析和队列准备，Worker/API/Agent 不调用 createBooking、创建支付单或支付。
- 正式开放时强制绕过缓存重新 bookingByTime；CandidateResolver 只用该响应的 nodeList/timeList 和当前冲突状态生成 FinalExecutionQueue 与坐标，再通过 QueuePolicyValidator、getPayPrice、createBookingBytime 执行。
- 开放时响应中 bookingstarttime 从已知预计 07:30 改为另一合法时刻，official_open 的 `resolved_official_open_at_utc/next_action_at_utc` 随之更新，不触发 contract_drift。字段结构/类型/语义异常才暂停为 drift。
- `execution_mode=at` 的精确 `scheduled_for_utc` 在开放时间变化后不被修改；不兼容时等待用户处理。Worker 睡眠或延迟恢复后仍须重新查询；只有窗口和场次仍有效才可迟到执行。
- 6 号场在新 nodeList 中名称唯一匹配时映射到新 nodeid/下标；旧 nodeid/数组下标变化不影响意图。名称缺失、重复、模糊或目标时间不在新 timeList 时 fail closed 或按明确授权继续下一个候选，不按旧目录猜。
- 一/两小时槽只由当前 timeList 精确解析并检查连续性、mintimeselect、maxtimeselect、maxAppointmentNodeNum；活动、社团、已预订、其他硬性占用始终不能加入最终队列。
- Prep Agent 队列重排只能在授权候选范围内；用户允许同场馆任意场地或时间浮动时才可在该范围内扩展。没有明确授权的 fallback 不自动发生。
- 重复 POST /api/jobs 在相同 Idempotency-Key/请求体下只生成一个任务；key 内容冲突返回 409。
- 不同用户/Token 共享 UpstreamRequestGate；429/Retry-After 跨 Credential 退避，不能通过多用户、Agent 或 Worker 绕过。准备刷新频率与最低 request gate 分开配置。
- 同一 Credential 的持久化执行锁保证不并行；lease 过期/Worker 崩溃后先对账。createBooking/支付结果未知时不重试、不切换候选。
- 已知“每人每天最多预约1次”类账户额度失败是终止性业务错误，不能换场地继续。HTTP 200 业务失败不视为成功。
- 自动支付默认关闭；价格超过 Intent/Job/Credential 最严格上限、币种未知、金额变化或订单状态不确定时暂停，不发送支付。
- 取消运行中任务产生 `cancel_requested`；本地 `cancelled` 不等于上游订单取消或退款。
- SQLite 外键、WAL、迁移、UTC 时间和业务时区展示规则生效；迁移不删除用户数据。
- Tailscale 仅允许授权 tailnet 成员到达服务；每个成员仍需应用登录。`.env`、`req/`、日志、个人计划和 SQLite 文件不进入 Git，fixture 使用人工合成数据。
- 验证只通过模拟上游和脱敏合成 fixture；不自动请求真实预约或支付副作用接口。

## 15. 不在首版范围

- 公网匿名访问、开放自助注册或公开 Tailscale Funnel。
- Redis/Celery、多节点调度、PostgreSQL 或微服务。
- Planning/Preparation Agent 直接创建真实 BookingJob、调用预约或支付、修改 Credential/Token/支付策略，或使用任意 HTTP/数据库/shell 工具。
- LLM 在正式开放关键链路中实时决策或读取原始上游冲突数据。
- 通过场地名称模糊猜测、历史 nodeid、旧坐标或旧价格执行未来日期预约。
- 验证码识别/绕过、反复高速轮询、通过多 Token/多用户规避上游限额。
- 未经上游对账就重放 createBooking、支付或其他副作用。
- 自动处理上游取消、退款、未知支付结果或超出用户授权范围的场地/时间/价格。
- 保证本地机器休眠、断网或 Worker 关闭时仍准时执行任务。
