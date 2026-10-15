# 人工小时候选队列

## 交互与边界

选择预约使用官方读取的全部场地**显示名称**；当前占用状态不限制人工意向。
默认两小时模式：点击开始格加入同一场地的两个完整连续小时。切换一小时后维护独立队列，不转换已有两小时候选。点击已选区间取消对应候选；预览可移除、上移和下移。
分组顺序固定为 120 分钟 → 60 分钟，组内保留用户顺序。候选逐项表示单场地意向，不表示同时预订多块场地。
当前网格的整点一小时单位是人工意向编辑规则，不证明官方原子时段长度。全部名称仍是未核验人工偏好。

## 组件

- `ManualQueueGrid`：小时网格与完整区间选取，事件只含场地名称/起止时间/时长。
- `ManualQueuePreview`：两组候选的排序、移除和只读历史展示。
- `ManualQueueWorkspace`：时长切换与保存状态，不渲染旧日期/时长/场馆/场地文本表单。
- `useManualQueue`：450ms 合并改动、串行写入、Session 与请求隔离、网络不确定及 409 恢复。
- `PlanCredentialControl`：公开到期信息、账户内凭据切换、密码输入更换 Token；复用现有凭据 CAS/账户验证接口。
- `PlanManager`：四个工作区组合。旧单意向与 Agent 计划在“当前计划”保留原编辑/保存契约。

## 持久化

新增 JSON 契约 `kind=manual_queue_draft / queue_contract_version=1`，由 **PlanService** 唯一写入现有 `booking_plans/booking_plan_revisions`。没有新增 Migration。
一个用户/日期对应一个确定的 UUIDv5 队列身份，首次 `base_version=0`，以后必须使用返回版本；响应遗失不会重复创建另一份计划。
每项 `candidates` 是完整语义 Intent（日期、单场地、单开始时间、60/120 时长、严格 fallback、无新增价格上限），共享未绑定解释上下文。**不把候选组合折叠为开始时间×场地的笛卡尔积**。
新建队列没有扩大备用范围；已有单意向的 fallback/预算保留在旧修订中，不自动导入或改写。
移除、清空、排序生成新修订；相同内容不生成重复修订。服务器校验整点、起止时长一致、同日、候选唯一与最多32项。最多16KB请求；Session/CSRF/Origin复用现有防护。
普通 `/api/plans` 列表/get/update 与单意向 Matcher/Agent 隔离队列类型，避免误读旧契约。

API（均仅操作当前登录用户）：

- `GET /api/plans/manual-queues`
- `GET /api/plans/manual-queues/<YYYY-MM-DD>`：不存在时 `queue=null`。
- `PUT /api/plans/manual-queues/<YYYY-MM-DD>`：`base_version, entries`，每项仅 `court_preference,start_time,end_time,duration_minutes`。
- `GET /api/plans/manual-queues/<YYYY-MM-DD>/revisions`

## 失败与恢复

自动保存仅写意向。保存中继续点选会串行保存后续改动；未保存时日期切换暂停。
网络结果不确定或 409 会暂停自动写入、保留本地队列。读取最新版本匹配本地时确认成功；不匹配时用户明确选择“采用最新版本”或“保留本地队列，另存新版本”。后者仍使用最新 CAS，竞争再次发生则继续409。
Session失效时丢弃旧请求回写；仅在同一应用 Session 对象的内存中保存语义草稿，同用户重登录可核对恢复，其他账户不可见，不写localStorage。
未保存时离开页面先尝试保存；硬刷新提示避免丢失内容。新 Token 输入在取消、账户切换及请求结束后清理；没有凭据明文读取接口。

## 未实现

队列排序是意向契约；没有执行前库存过滤、真实抢票、订单、支付或Job。可信物理 VenueCatalog仍为空；不能把预约类别或场地名称解释为可信上游绑定。历史/当前观察不升级为已验证库存。


## 当日界面与计划管理完善

- 人工网格默认00:00～24:00，24个整点小时；网格滚动区域上限520px，日期与库存状态不影响人工时段偏好。午夜边界仍由服务器检查。
- 两个队列分别在200px列表内滚动，选择页、抢票计划和历史共用同一预览组件。
- “当前计划”更名“抢票计划”，日期筛选支持任意天；只有服务端当前三天窗口内且时区一致的队列可跳转选择预约。
- 已存在的历史意向可以修改原日期的语义内容；禁止新建过去日期意向。历史修改不构成执行授权。
- DELETE普通计划与日期队列由PlanService追加软删除修订；不可变历史保留。队列删除后为空且从列表隐藏；再次选择使用当前版本重新生成修订，不重复创建身份。普通删除计划不能被常规PATCH恢复。
- 查询日期DTO提供plan_status（expired/draft/outside_window/deleted）、execution_state=not_started以及can_open_selection；没有Job/执行记录，因此不伪造“已执行”状态。
- 查询网格采用与选择页一致的紧凑边框、文字和滚动容器，保留官方状态调色板。本版不再承诺官方格子的原像素尺寸。
- AI模型设置精简重复说明/标题；DeepSeek/OpenAI/通义千问预设只预填可修改字段，切换预设清空待提交Key，用户主动保存和测试。官方参数来源见modelPresets.js中的链接（2026-10-15核对）。

新增API：DELETE `/api/plans/<plan_id>`，DELETE `/api/plans/manual-queues/<YYYY-MM-DD>`，均要求Session/CSRF/Origin和当前base_version。没有新增Migration或真实执行。
