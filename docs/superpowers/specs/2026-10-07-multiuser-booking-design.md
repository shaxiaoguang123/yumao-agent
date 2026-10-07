# 羽毛球预约系统：多用户与 Agent 计划设计

- 日期：2026-10-07
- 状态：最终规格修订版，等待用户审阅
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

Flask 后端提供唯一的 BookingWindowPolicy、AvailabilityService、PlanService 和 BookingExecutionService。BookingWindowPolicy 集中计算可查询日期和预约开放时刻；AvailabilityService 统一查询、归一化、缓存和节流；PlanService 在保存计划时复核候选；BookingExecutionService 是唯一可调用真实预约副作用接口的服务。Vue、Agent、API 路由和 Worker 不得各自复制时间规则或绕过领域服务。

API 和 Worker 可以在同一台本地机器运行，逻辑上分离即可。Worker 可作为独立命令或受控后台线程运行；同一时刻只允许一个进程初始化数据库迁移。SQLite 是唯一持久化队列和状态来源，不另建内存任务队列作为事实来源。

当前目录只有前端构建产物，没有 Vue 源码或构建清单。实施前需要恢复前端源码或建立新的 Vue/Vite 源目录，并明确唯一维护版本。后端的可读源码位于打包目录内，另有一份重复副本；实施前需要选定唯一源文件位置。

Flask 开发服务和前端开发服务可以分别运行。前端开发服务通过代理访问 Flask API；生产访问时由同源服务路由或 Tailscale 私有代理提供页面和 API。公网入口、反向代理与应用的信任边界必须显式配置。

## 3. 人工与 Agent 共用的预约计划

### 3.1 单一事实来源与版本

系统不保存“人工队列”和“AI 队列”两份互不关联的数据。每份 BookingPlan 属于一个用户，只描述预约业务内容，例如场馆、预约日期、预约类型、时间段和有序候选队列。队列继续表达两小时和一小时场次及各自候选顺序，以保留现有优先级语义。

计划中的每个场地候选使用结构化 BookingCandidate，而不是把“7号场19:00-21:00”一类展示文本作为业务主键。候选 Schema 至少包含：target_date（YYYY-MM-DD 业务本地日期）、venue_id、court_id、slot_id（稳定 ID 字符串）、start_time_local/end_time_local（HH:MM）、duration_minutes（正整数）、session_type（one_hour 或 two_hour）、priority（正整数，在对应 session_type 队列内唯一）；可选 venue_name_snapshot/court_name_snapshot 仅用于展示。PlanService 校验日期、时长、场次类型和时间字段互相一致。ID 使用上游稳定标识或经验证的稳定映射，不能从展示字符串反解析核心字段。候选队列以结构化对象数组保存，数组顺序或 priority 明确表达优先级；同一 PlanRevision 内候选的目标日期须一致。实时 occupancy/window 状态属于 AvailabilityService 响应，不写入 PlanRevision 作为长期事实。

Plan 不包含 Credential 选择、自动支付开关、支付上限、Worker 状态或执行时间。用户在创建 BookingJob 时选择自己的执行 Credential；任务调度也由 BookingJob 管理。因此一个用户可以将同一份计划用于不同 Credential，也可以修改计划而不隐式提交任务。保存计划前如需验证可用性，用户在 UI 选择一个仅供查询的 validation Credential；PlanService 校验它属于当前用户，但不把它写入 BookingPlan/PlanRevision，也不将它自动用作后续 Job 的执行 Credential。

人工界面和 Agent 使用同一个 PlanService：

- 人工保存场地和队列选择时，PlanService 创建新的 PlanRevision。
- Agent 读取当前计划和经筛选的场地可用信息后，生成结构化修改；只有用户明确要求保存时才提交给 PlanService。
- 修改支持追加、删除和替换；Agent 必须展示会移除或替换的候选项。意图含糊且会造成破坏性修改时，先请求用户确认。
- 每个版本记录来源（manual 或 agent）、操作者、时间、变更摘要和不可变计划内容。
- 更新必须携带期望的当前版本号。服务在一个 SQLite 写事务中检查并推进版本；版本不匹配返回 409，要求重新读取后再编辑。
- PlanRevision 只追加，不允许更新或删除。BookingPlan 的当前版本指针通过比较并交换方式更新；不能覆盖历史版本。
- PlanService 保存 revision 前，通过 AvailabilityService 校验完整候选列表：已确认的活动占用、社团占用和其他硬性不可预约状态不能出现在保存后的计划中；未知状态或无法确认数据时拒绝新增该候选并要求刷新。预约窗口尚未到 07:30 本身不是场地硬性占用，正常候选仍可提前加入和排序。

### 3.2 计划与 BookingJob 执行快照

执行时间不属于 BookingPlan。立即执行与未来定时执行统一创建 BookingJob，使用同一张持久化任务表和同一个 Worker 队列：

- 创建任务必须由已登录用户通过明确的人工作用触发，例如点击“立即执行”或“保存定时任务”。Agent 工具没有创建 BookingJob 的能力。
- 创建请求必须明确指定当前用户的 plan、PlanRevision、Credential 和执行时间。若客户端省略 revision，只能由服务端在同一个事务内读取并固定当时的当前 revision，不能留待 Worker 开始时再读取。
- BookingJob 创建成功时，固定 plan_revision_id，并把该 revision 的完整执行所需内容复制到 execution_snapshot_json，同时保存规范化后的快照哈希。快照还要固定 BOOKING_TIMEZONE、BookingWindowPolicy 版本、目标预约日期及该目标日的 booking_open_at_utc。计划快照和任务快照均不可变。
- 快照至少包含预约计划内容、revision 编号、credential_id、创建时的 Credential 执行策略版本、支付上限、创建方式和预约执行时间。不得包含解密后的 Token、支付密码、LLM Key 或其他明文秘密。
- 快照还要固定创建任务时是否允许自动支付、支付上限数值和币种；这些值只记录授权边界，不替代执行时对 Credential 当前状态和策略的重新校验。
- Credential 的启用、删除状态及当前安全策略在 Worker 执行前仍需重新校验。安全策略变得更严格时立即生效；策略变得更宽松时，不自动扩大已有任务快照中的授权范围。
- 用户修改计划只产生新 PlanRevision，不修改任何已创建任务。用户要用新计划执行，必须显式创建一个新的 BookingJob。
- 任务创建后的执行时间和快照不可原地改写。需要改变时间、计划版本或 Credential 时，取消原任务并创建新任务。
- 立即任务和未来任务均以 queued 存储，通过同一字段 scheduled_for_utc 区分何时可领取；不另建计划调度表、内存队列或第二套调度状态。

## 4. Agent 的职责与工具边界

Agent 负责把用户表达转为预约计划修改，不直接创建或执行预约：

1. 在当前登录用户范围内读取计划及必要的版本信息。
2. 使用用户在界面选定的 Credential 查询预约信息；服务端只返回场馆、时间、可用状态和必要价格等最小化字段。
3. 生成符合固定 Schema 的计划差异，说明新增、删除、替换的候选项。
4. 用户明确要求保存时，通过 PlanService 写入新 PlanRevision；遇到版本冲突必须重新读取并重新生成差异，不能静默覆盖。
5. 返回保存后的计划版本。Agent 不能创建、调度、取消或恢复 BookingJob。

00:00 查询窗口开启后，Agent 可以通过 AvailabilityService 查看当天、明天和后天的场地状态，并把正常候选加入计划；活动、社团及其他确定不可预约的候选会被服务端标记为硬排除。00:00 至 07:30 的 Agent 工具只有查询和 PlanService 写入能力，没有创建预约或调用副作用接口的能力。

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

以当前业务时区日期 D 和明确的目标预约日期 T 计算：

- 默认目标日期为 D + 2 天，即通常所说的“后天/第三天”。可查询日期范围为 D、D + 1、D + 2；不允许把“第三天”当成 D + 3。
- 目标日期 T 的查询开放时刻固定为 T - 2 天的 00:00；正式预约开放时刻固定为 T - 2 天的 07:30。先对日历日期做减法，再在 BOOKING_TIMEZONE 中构造本地时刻，最后转换为 UTC 比较和持久化。
- 例：星期一 00:00 后可查星期一、星期二、星期三；星期三（后天）的查询开放时间是星期一 00:00，预约开放时间是星期一 07:30。要预约星期日，应在星期五 00:00 后查询并排队，BookingJob 的最早预约时间为星期五 07:30。
- can_query(T) 要求 T 在当前业务日期 D 至 D + 2 的窗口内，且当前时刻不早于 query_open_at(T)。过期日期、窗口外日期和查询尚未开放的日期均返回明确原因。
- can_book(T, slot) 是时间策略判断：T 位于支持窗口内，当前时刻不早于 booking_open_at(T)，当前业务日期的本地时刻也已到 07:30，且当前时刻早于所选场次的本地 start_time。这样即使今天/明天的目标日期开放时间早已过去，凌晨 00:00 至 07:30 仍不会产生预约副作用，场次开始后也不会提交过期预约。实际是否可下单还要同时满足 AvailabilityService 的正常可预约状态和上游实时结果。
- 今天或明天的剩余场地不被无依据地禁止：若它们在当前三日窗口内、场次未过时、上游明确允许且实时状态正常，用户可明确选择并创建任务。默认只把 D + 2 天作为建议目标日。
- BookingWindowPolicy 的统一返回值至少包括 business_timezone、business_date、default_target_date、可查询日期列表、target_date、query_open_at_utc、booking_open_at_utc、window_status、can_query、can_book_by_time、can_mutate_upstream 和 reason_code。窗口状态至少区分 query_not_open、query_open_booking_not_open、booking_open、target_expired 和 outside_supported_window。已创建任务始终按自身快照中的时区、目标日和 policy 版本核对；系统时区/策略变更不得静默重解释已有任务，变更需显式迁移和 active-job 审查。

00:00 到 07:30 期间允许查询和编辑本地计划，但禁止任何真实上游写操作，包括创建预约单、支付单、支付及其他预约副作用。所有上游写操作只能由 BookingExecutionService 暴露，并在发出请求前再次调用 BookingWindowPolicy；API 路由和 Agent 工具没有直接调用底层预约客户端的路径。任何层发现 can_mutate_upstream 为 false，或 createBooking 时 can_book_by_time 为 false，都必须 fail closed，不发送请求。

### 5.2 BookingJob、统一队列与状态机

所有任务放入 SQLite 的 BookingJob 表。scheduled_for_utc 不晚于当前 UTC 时间的 queued 任务才可由 Worker 领取；未来定时任务仍是同一张表中的 queued 行。已过期租约的 running 任务和需要核对的 cancel_requested 任务也由同一 Worker 从 BookingJob 表领取，但只能走恢复/取消核对流程。

创建 BookingJob 时，服务端按快照中的目标日期计算正式预约开放时刻，并要求 scheduled_for_utc 不早于该时刻，也不早于 scheduled_for 所在业务日期的 07:30；同时要求它早于候选场次的本地开始时间，且不能把即时任务排入过去。若请求过早或过晚，API 返回 422、明确的 BOOKING_WINDOW_NOT_OPEN/BOOKING_SLOT_EXPIRED 错误码及服务端计算出的边界，不能静默改成 07:30，也不能只依赖前端校验。要在 00:00 创建抢后天任务，应明确将 scheduled_for_utc 设为目标日期对应 T - 2 日的 07:30。省略 scheduled_for 表示立即执行，仅当当前时刻已达到当日和目标日期的正式开放时间才接受。

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
- running -> awaiting_human、succeeded、failed、cancel_requested 或 needs_attention
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

每个 BookingJob 有多条持久化 JobStep，例如 availability 查询、createBooking、订单查询、支付下单和支付状态核验。JobStep 至少记录步骤类型、序号、状态、尝试次数、开始/结束时间、稳定的本地 operation_id、经脱敏的结果摘要和关联 ExternalOrder。

JobStep 状态包括 prepared、in_progress、succeeded、failed_definitive、unknown 和 skipped：

- 查询类步骤可以按有限次数和退避策略重试。
- 每次 createBooking、创建支付单或支付等副作用操作，必须先在事务中持久化 in_progress 的 JobStep 和本地 operation_id，提交后才发送网络请求。
- 如果上游支持幂等键，使用稳定的 operation_id；未确认上游支持时，不能假设重复请求幂等。
- 成功响应、业务失败响应和关联订单 ID 必须在收到后尽快持久化。HTTP 200 本身不是成功依据，须按 JSON 的业务字段分类。
- Worker 重启或租约过期后，所有未完成副作用先标记/视为 unknown 并恢复查询。只有上游明确证明副作用已成功或明确证明未发生，才更新 JobStep。
- 如果上游能证明成功，恢复本地状态而不重发；如果能证明未发生且接口契约允许安全重试，才可受限重试；无法查询、查询结果不完整或状态仍有歧义时转为 needs_attention。
- 对 createBooking 失败候选的自动切换，仅在上游业务响应明确证明本次没有创建订单时允许；超时、断连或未知业务响应时不得继续尝试下一候选，以免重复预约。
- JobStep 和 ExternalOrder 不保存完整 HTTP 请求/响应、Cookie、Token、支付密码、二维码或未经筛选的个人资料。

### 5.5 可用性归一化、节流与执行前核验

AvailabilityService 是所有人工页面、Agent、PlanService 和 Worker 获取场地状态的唯一入口。每个返回项采用结构化结果，至少包括 BookingCandidate 字段、fetched_at_utc、occupancy_status、window_status、can_query、can_select_plan、can_book 和 reason_code。occupancy_status 至少区分 normal_candidate、event_occupied、club_occupied、other_hard_unavailable 和 unknown；window_status 至少区分 query_not_open、query_open_booking_not_open、booking_open、target_expired 和 outside_supported_window。占用状态与时间窗口状态分开表达：正常场地在 00:00 后、07:30 前应显示为“正常候选，预约尚未开放”，而不是“场地不可预约”。

- AvailabilityService 在 00:00 查询开放后，可以返回当天、明天和后天所有场地/时间段，包括正常候选、活动、社团活动及其他确定不可预约状态；查询结果只用于准备计划，不代表预约已经开放。
- 活动、社团活动和其他被上游明确标识为不可预约的状态都是硬排除项：can_select_plan=false、can_book=false。前端置灰，Agent 工具拒绝加入，PlanService 保存 revision 时再次检查。unknown 或无法确认的数据也不能被当成正常候选；须刷新或等待查询恢复。
- 对正常候选，can_select_plan 可在正式预约尚未开放时为 true；最终 can_book 还必须同时满足 BookingWindowPolicy 的时间门禁和实时上游状态。前端不得用一个模糊的 available 布尔值合并这两类含义。
- PlanService 保存时必须重新向 AvailabilityService 校验最终候选队列。仅可复用 fetched_at 距保存时不超过 5 秒的上游状态；更旧时请求受全局节流的实时刷新，若正处于冷却且拿不到足够新的状态，则不保存并返回可重试错误及 retry_after，不绕过全局限流。保存结果覆盖整个最终候选队列，发现任何硬排除项时拒绝保存并返回具体候选和 reason_code，用户可移除后再次提交。
- Worker 到 scheduled_for_utc 后、每次 createBooking 前，先调用 BookingWindowPolicy 做最终门禁，再强制重新查询实时 availability；此预约校验必须绕过所有旧缓存，包括 00:00 得到的缓存。窗口未开或快照不合法时不调用 createBooking 并进入 needs_attention；候选变成硬排除时记录并跳过；状态未知时先安全重试查询，仍未知则进入 needs_attention。任务被延迟到目标日过期或场次已开始时，标记为确定失败并停止执行。
- 候选选择严格使用 BookingJob 不可变快照中的 priority。实时结果若明确表明该候选不可约，可记录并尝试快照中下一个候选；查询超时/断连可有限重试查询，但 createBooking 超时、断连或无明确业务结果属于副作用结果未知，必须先按 JobStep/ExternalOrder 对账，不能直接重试或切换候选。
- 上游 availability 查询经过全局 UpstreamRequestGate，不因更换 Credential、启动额外 Worker 或由 Agent 调用而获得独立频率额度。默认对同一上游 availability 端点最多一个在途查询、全局最小间隔 2 秒；可用配置调得更保守，不能配置为高于上游允许的请求频率。07:30 到期任务可以同时变为可执行，但实际查询/提交仍由此全局门禁按序节流，必要时会略晚于开放时刻；系统绝不通过提高并发或切换 Credential 来追赶。Availability 的上游 occupancy/price 缓存默认 15 秒，按用户、Credential 和规范化查询参数隔离，只缓存脱敏结果；每次响应都根据当前时钟重新计算 window_status、can_query 和 can_book。缓存不得用于 Worker 的 createBooking 前最终核验。
- 所有请求入口共享持久化的 SQLite 节流状态，避免多进程绕过。查询超时可有限重试，默认最多 3 次并使用指数退避及抖动；遇到 429/503 或 Retry-After 时以 Retry-After 或更长退避为准，并设置跨 Credential、跨 Worker 的上游全局冷却。冷却期间不允许通过另一个 Token、Agent 工具或新 Worker 继续发相同查询。
- 所有上游调用均经过 UpstreamRequestGate；预约和支付副作用还遵守各自端点限流。Agent 不得有独立 HTTP 客户端。对 createBooking 或支付的超时/断连结果未知时，只执行状态核对查询；核对仍不确定则 needs_attention。

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

- 在每次 createBooking 前，将 getPayPrice 或其他可信的实时估价结果及币种作为预估写入对应 JobStep。实际金额必须来自 createBooking 成功结果或权威订单查询；缺少金额、币种不一致或无法确认订单状态时，不支付。无法取得可信预估时，实际金额按价格变化处理并等待用户确认。
- 对实际金额、币种、当前 Credential 支付策略和上游订单 ID 做完整校验。超过有效上限、价格相较本次已确认报价变化、订单状态未知或金额字段异常时进入 awaiting_human/needs_attention。
- 自动支付只有在 BookingJob 快照创建时记录为允许、当前 Credential 仍启用自动支付、订单状态已确认、金额不超过任务快照上限和当前 Credential 上限，并且价格未发生需用户确认的变化时才可执行。
- 人工确认价格变化时，只能通过服务端记录的一次性 JobApproval 授权指定的已知订单与精确金额；审批记录不可重复使用，且仍不得超过当前 Credential 支付上限。调整支付上限必须由用户在 Credential 设置中单独完成，Agent 不可代为调整。
- 调高 Credential 支付上限不会扩大已有任务快照中的自动支付授权。若已知订单金额高于快照上限但不高于用户后来设置的当前上限，只能经一次性人工 JobApproval 继续，不得转为自动支付。
- 自动支付关闭时，Worker 不得支付；用户如需针对某个已创建订单进行一次性支付，必须通过单独、明确的人工作用确认，并经过相同金额和订单状态校验。
- 支付及其他上游写操作也必须经过 BookingWindowPolicy 的当日 07:30 写操作门禁；00:00 至 07:30 的人工确认只保存为待处理授权，不得提前向上游提交。
- 支付调用前先持久化 JobStep/ExternalOrder 状态。崩溃后必须查询订单和支付状态；支付状态不确定时禁止再次支付，转为 needs_attention。
- 不在首版中自动支付超出用户当前支付上限的金额，不自动处理退款或不确定的付款结果。

## 6. 数据与隔离

主要实体与约束：

- **User**：唯一登录标识、密码哈希、角色、状态和 UTC 创建时间。
- **Session**：服务端会话 ID 的哈希、user_id、到期时间、撤销时间、CSRF 校验材料和创建/最近使用时间。
- **Invitation**：邀请码哈希、创建者、有效期、撤销时间、使用者和使用时间；单次使用。
- **Credential**：user_id、标签、加密 Token、加密支付凭证（如业务确需）、启用状态、自动支付开关、支付上限、策略版本、最近验证时间和 deleted_at。
- **CredentialExecutionLock**：credential_id、当前 job_id、lease owner/到期时间/epoch；同一 Credential 最多一条有效执行锁。
- **CredentialPolicyRevision**：Credential 敏感执行设置的版本化记录和操作者，供 BookingJob 快照审计。
- **AvailabilityCache**：user_id、credential_id、规范化查询键、脱敏的上游 occupancy/price 结果、fetched_at_utc 和 expires_at_utc；按用户和 Credential 隔离，短时缓存，不缓存时间窗口判定。
- **UpstreamRequestGate**：按上游服务/端点保存跨 Credential 的全局最小间隔、在途租约和 backoff_until_utc；不是用户数据，所有进程共用。
- **IdempotencyRecord**：user_id、API 操作名、请求级 idempotency_key、规范化请求哈希、创建的 job_id 和创建时间；同一 key 对应唯一结果。
- **UserLLMConfig**：user_id、模式（service_default/custom）、用户自定义 base URL、模型、协议、认证模式和加密 API key。自定义配置作为完整 Provider，不逐字段继承环境配置。
- **BookingPlan**：user_id、当前 revision 指针、创建/更新时间和归档状态；不含 Credential、支付或调度字段。
- **PlanRevision**：user_id、plan_id、版本号、来源、操作者、变更摘要、规范化计划内容和内容哈希；(plan_id, revision) 唯一且追加后不可更新/删除。
- **BookingJob**：user_id、plan_id、固定的 plan_revision_id、credential_id、执行快照 JSON/哈希、执行时间、状态、租约字段、recovery_required、创建/开始/结束时间和安全错误摘要。
- **JobStep**：user_id、job_id、步骤类型和序号、状态、operation_id、重试计数、时间、脱敏结果摘要和 external_order_id。
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

抓包目录按参考资料使用，仅汇总字段名、接口顺序和业务状态，没有将原始值写入本规格。

观察到的主要接口包括：

- bookingByTime：返回 timeList、nodeList、conflictList、priceList 及预约开放时间等元数据。
- getPayPrice：返回 txamt 和 pricemap，作为金额预估来源之一。
- createBookingBytime：成功响应可能带 orderno 和 txamt；捕获的 4 个响应中有 3 个 JSON success=false、1 个成功，HTTP 均为 200。
- openPlatFormPayOrder、payOrderForPhone、payOrderDetails：用于支付请求与订单状态核对；每个副作用接口的幂等和查询能力须在实施时单独确认。
- getPictureCheckFlag、getPictureCheckInfo 及图片资源请求：表明上游流程存在图片验证相关交互。

userAddress/getUserInfo 响应含身份标识、电话和用户名字段；payOrderDetails 含订单标识、联系方式、二维码及支付详情字段。服务端只投影执行需要的字段，不将完整响应传给 Agent、前端或普通日志。ExternalOrder 只存订单核对所需最小字段。

执行器不能依赖用户保存计划时的旧 availability。每个 createBooking 前都重新调用上游查询接口；HTTP 200 必须结合 JSON 业务状态判定。查询类接口超时或断连可按全局退避策略有限重试；createBooking、创建支付单、支付等副作用接口超时、断连或无法确定业务结果时属于结果未知，必须先对账，不能直接重试或切换下一个候选。

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
- POST /api/credentials/{id}/validate：用户主动验证当前 Credential；响应不包含 Token。
- GET/PUT/DELETE /api/llm/settings：读取模式和脱敏配置、设置完整的用户自定义 Provider、或改用服务级默认。读取时只返回安全的 base URL、模型、协议、认证类型和 key 是否已配置。
- POST /api/llm/test：用户主动测试当前完整 Provider；记录脱敏结果，不返回或记录 key。

场地窗口与 availability：

- GET /api/booking-window：返回服务端业务时区、当前业务日期、默认目标日期、当前可查询的三天、每个目标日的查询/预约开放时刻及 can_query/can_book_by_time 状态。前端不得自行重算开放时间。
- GET /api/availability?credential_id=...&target_date=YYYY-MM-DD：经 AvailabilityService 获取指定业务日期的结构化候选和占用/窗口状态；省略 target_date 时请求当前三日窗口。响应包含 fetched_at_utc、occupancy_status、window_status、can_select_plan、can_book 和 reason_code。若上游需要多次请求，服务端按全局 UpstreamRequestGate 顺序获取，不并行扇出规避限流。

计划与 Agent：

- GET/POST /api/plans、GET/PATCH /api/plans/{id}：创建、读取或追加计划版本。PATCH 必须携带 base_version 或 If-Match；冲突返回 409 和当前版本摘要。
- GET /api/plans/{id}/revisions：读取当前用户自己的历史 revision。
- POST /api/plans/{id}/agent-edits：提交 Schema 化的计划差异，使用相同乐观锁和 PlanService；不得接受 job、支付、Credential 策略或调度字段。
- POST /api/plans 和 POST /api/plans/{id}/agent-edits 保存前，调用方须提供当前用户已选择的 validation_credential_id；PlanService 通过 AvailabilityService 校验完整候选，且只把该 ID 用作本次验证上下文，不保存到计划。禁止保存硬排除项或状态未知项。Agent 不能自行指定或替换 validation Credential。

任务与订单：

- POST /api/jobs：仅人工作用创建 BookingJob，必须携带请求头 Idempotency-Key。客户端为一次明确创建动作生成一个 key，并在该动作的所有网络重试中重复使用；请求体包含 plan_id、可选的明确 plan_revision_id、credential_id 和 scheduled_for_utc。服务端在同一 SQLite 事务中校验预约窗口、生成不可变快照并记录 IdempotencyRecord；客户端不能传执行快照、自动支付授权、任意上游请求或 source=agent。
- 同一用户对同一创建操作重放相同 Idempotency-Key 和相同规范化请求时，返回原 BookingJob，不再创建任务；key 相同但请求内容不同返回 409。并发重复请求也只能创建一个 Job。IdempotencyRecord 至少保留到其 BookingJob 及重试窗口结束，不能用短 TTL 让延迟网络重试创建重复任务。
- GET /api/jobs、GET /api/jobs/{id}：查询当前用户自己的任务、状态、快照摘要和 JobStep 状态摘要。
- POST /api/jobs/{id}/cancel：发出本地取消请求；运行中只产生 cancel_requested，响应明确说明上游订单状态需单独核对。
- POST /api/jobs/{id}/resume：用户确认验证已完成或请求恢复；Worker 重新获取锁并对账后决定是否继续，不直接跳过校验。
- POST /api/jobs/{id}/payment-approvals：对服务器显示且已核实的一个订单和精确金额创建一次性人工授权。服务端校验订单归属、金额、币种、当前支付上限和状态；模型工具不能访问。
- GET /api/external-orders、GET /api/external-orders/{id}：只展示当前用户的最小订单状态和金额。除非上游取消接口已确认支持且另有明确授权，不提供将本地取消映射成上游取消的行为。

除登录、注册和公开的健康检查外，所有接口均需登录并在 SQL 查询中绑定当前 user_id。管理员接口另做角色校验和审计。客户端不得提交 Token 作为上游调用参数；只传当前用户 Credential ID，由后端按 user_id 读取并短时解密。所有修改端点还要校验 CSRF 和幂等要求。

## 10. 前后端体验

前端提供：

- 登录和邀请码注册；无公开自助注册入口。
- Credential 标签、启停状态、验证结果和自动支付设置；支付上限用明确币种和金额展示。
- 日期选择器默认选中业务日期后天，并显示“后天/第三天”的明确日期；00:00 后可查看当天、明天、后天。星期一/星期日示例和“查询开放”“预约尚未开放（07:30）”状态由后端返回，前端不自行计算。
- 场地结果分别显示 occupancy_status 与 window_status。正常候选在 00:00 后、07:30 前仍可加入计划；活动、社团和其他硬性占用项显示具体原因且不可选择。用户明确切换到今天/明天时，只显示仍未过时且服务端判定允许的候选。
- 场地网格、两小时/一小时计划队列、人工排序、删除、保存版本和冲突提示。
- Agent 修改预览、队列差异、版本历史和冲突后重新生成提示；Agent 界面没有真实任务创建、支付策略或执行设置控制。
- LLM Provider 设置：服务级默认/个人自定义模式切换、base URL、API key、模型和兼容协议；已保存的 key 只显示配置状态，可替换或清除。
- BookingJob 创建表单：选择计划版本、Credential、立即执行或具体定时执行时间。计划保存不代表已创建任务。
- 对默认后天任务，界面可预填目标日对应 T-2 日 07:30；用户在 00:00 至 07:30 创建时必须创建这个未来时刻的 BookingJob。过早的即时执行或早于开放时刻的计划时间会被服务端拒绝并解释原因，不自动更改。
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

本规格修订后，实施开始前先挑选可维护源码、创建项目级 .gitignore 并提交干净的源代码基线。凭证、个人 booking_plan.json、日志、req 抓包、Windows 可执行文件、打包压缩包和重复发布目录不进入源码基线。基线提交完成后，建立一个 feature worktree（建议分支名 codex/multitenant-booking）；所有实现阶段在该 worktree 内按垂直功能分批提交，完成后本地合并回 main，不需要配置远程。

实施阶段：

1. **源码与启动基线**：确定唯一后端源码、恢复或建立前端源码、补充 Conda test 依赖和启动说明；确认敏感文件排除规则。
2. **SQLite 与认证基础**：WAL、外键、migration、User、服务端 Session、邀请创建/兑换、CSRF 和所有权查询约束。
3. **Credential 与 Provider 安全**：密文存储、软删除、策略版本和支付上限；完整 LLM Provider 模式、密钥隔离和 SSRF 防护。
4. **统一计划**：Plan/PlanRevision、结构化 BookingCandidate、硬排除校验、追加式修订、optimistic locking、人工编辑和 Agent 计划差异。
5. **任务模型与队列**：BookingWindowPolicy、BookingJob 创建时固定 revision/开放窗口/执行快照、请求级幂等；立即/定时任务进入同一队列；状态机、lease 和 Credential 执行锁。
6. **可靠执行器**：JobStep、ExternalOrder、副作用恢复、07:30 最终门禁、实时 availability、全局节流/缓存/退避、awaiting_human、取消/恢复和支付门禁。
7. **前端闭环**：Credential 和 Provider 设置、计划编辑与 Agent 预览、Job 创建/调度、订单摘要与人工作用确认。
8. **本地安全验证**：双用户隔离、邀请码竞态、计划并发更新、Worker 重启恢复、租约过期、同 Credential 锁、重放保护、LLM SSRF 边界及日志脱敏；上游用模拟服务或脱敏 fixture。
9. **Tailscale 私有接入**：关闭 debug，配置 Serve/ACL，验证授权成员可访问、未授权成员不可访问且均需应用登录。

每阶段先按已审阅规格编写实现计划；不把该规格本身视为已授权实施。实施中若发现上游接口无法提供可靠订单查询或任务恢复所需字段，先记录限制和安全降级方式，不盲目重试副作用。

## 14. 验收标准

- 邀请码只能兑换一次且可过期、可撤销；并发兑换最多创建一个用户。
- 用户登录态由可撤销的服务端 Session 管理；注销后旧 Cookie 不能继续访问业务接口。
- 用户 A 不能读取或修改用户 B 的 Credential、计划、revision、Job、订单、会话或 LLM 设置；SQL 查询本身始终绑定 user_id。
- Credential 软删除后不可创建新任务；有未决副作用时保留恢复所需密文且禁止新副作用，无未决引用后清除密文。
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
- 每个 createBooking 前重新查询实时 availability；HTTP 200 的业务失败不会被当成成功。
- 星期一 00:00 的 BookingWindowPolicy 精确返回星期一、星期二、星期三可查询；星期日目标日 T 的 query_open_at 为星期五 00:00，booking_open_at 为星期五 07:30。测试覆盖日期边界和 07:29:59/07:30:00。
- 00:00 至 07:30 期间，无论经 UI、API、Agent 还是 Worker 都不能调用 createBooking、支付或其他上游写操作；伪造或历史错误的 Job 时间也会被 Worker 最终门禁阻断。00:00 后允许创建 scheduled_for 为当日 07:30 或之后的未来 Job。
- POST /api/jobs 拒绝早于目标日 T-2 日 07:30 或早于 scheduled_for 所在本地日 07:30 的任务，也拒绝已经过时的场次；不会自动改写请求时间。07:30 前的即时任务请求明确失败。
- 每个目标日按 T-2 天计算查询和预约开放时刻；默认 D+2，但在上游允许时今天/明天未过时场次也可由用户明确选择，不存在把“第三天”误算成 D+3 的偏移。
- PlanRevision 使用有类型的 BookingCandidate 字段（日期、场馆/场地/时段 ID、本地开始/结束时间、时长、场次类型、优先级）；展示文本不能替代核心业务数据或从字符串反解析。
- 活动、社团和其他确定不可预约状态在 UI、Agent Schema 和 PlanService 三处一致硬排除；正常候选在预约未开放时仍能进入计划。
- BookingJob 开始时绕过旧 availability 缓存查询实时状态，并依照不可变快照 priority 尝试候选；旧的 00:00 结果不能直接触发预约。
- Availability 查询的缓存、全局节流、单在途请求和 429/Retry-After 冷却跨 API、Agent、Credential 和 Worker 生效；更换 Credential 或 Worker 不能规避限流。
- 查询超时可有限重试；createBooking 或支付超时/断连不重放，并先对账。createBooking 结果未知时不能转向下一候选。
- POST /api/jobs 相同 Idempotency-Key 和请求体的并发/网络重试只创建一个任务；相同 key 携带不同内容返回 409。
- 用户取消运行中 Job 时先显示 cancel_requested；本地 Job 取消不会被表示成上游订单取消或退款。
- 图片验证进入 awaiting_human；用户恢复后先核对状态再继续。
- 自动支付默认关闭；金额缺失、币种不符、超限、价格变化或订单状态不确定时暂停，不发生支付。
- 用户对特定订单/金额的一次性确认可追溯、过期且只能使用一次；Agent 不能生成此授权。
- SQLite 每个连接启用外键，数据库使用 WAL，schema migration 可重复运行且不删除用户数据。
- 事件时间按 UTC 持久化，预约日期和 UI 按配置的业务时区解释与显示。
- 日志采用脱敏白名单，不含密钥、Token、个人资料、Cookie、二维码或完整上游响应。
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
