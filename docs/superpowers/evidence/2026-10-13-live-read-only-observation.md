# 官方真实只读时段观察（2026-10-13）

## 已完成与授权

用户在本轮会话明确授权使用本机测试 Token 开发和验证查询，并要求禁止支付。本轮实现只读 `getUserInfo` 凭据验证、`getBookingNode` 类别读取和 `bookingByTime` 时段读取；不调用报价、创建订单、预约执行或支付接口。

本机官方 `req/1.js` 字节 SHA-256 仍为 `d0709c88bb7fb7e156a023cb32b0938253aea84f108fbf3dfc499b846813411e`。文件解码时的换行归一化会产生不同哈希，因此版本比较使用原始字节。没有提交真实抓包、Token、私有查询 ID、原始响应或可重放请求。

## 直接证据与边界

- 官方 `getBookingNode.resultData[].nodename` 用于显示预约类别，所选 `id` 被用于 `bookingByTime.nodeid`。本轮受控查询实际返回四个类别，并成功读取羽毛球类别的时段响应。
- 目标日期为 2026-10-15 的响应有十个场地列和六个时间行。本轮只记录字段结构和数量，不将动态上游 ID 发布或写入计划。
- 官方客户端按 `nodeList` 顺序显示列、按 `timeList` 顺序显示行；冲突坐标先场地后时间，同坐标重复项按 `conflictList` 顺序覆盖，最后一条决定客户端显示状态。
- `req/1.js` 的渲染条件直接证明：`timeList.status == 0` 时绘制场地格子，`status == 1` 时只保留另一种时间标签，不绘制场地格子。后者不能投影成没有冲突的可用区域。此规则同时修正了既有历史预览。其他状态不展示可选格子。
- 双段冲突保留“已预订显示”，三段冲突保留官方活动/不可预订显示分类。客户端显示规则不能替代服务端库存授权。
- 仍未证明实体场馆名与查询范围的映射、场地实体归属、原子时长、状态完整业务含义、价格币种/单位和执行有效期。可信 `VenueCatalog` 保持空，计划保持 `unbound_draft / unverified_manual`。

## API 与数据来源

- `GET /api/availability/live/options`：返回显式配置开关和禁用的执行能力。
- `POST /api/availability/live/categories`：使用当前用户已验证凭据，返回显示名和短期查询引用。引用绑定用户、Session、凭据，真实上游 ID 只保留在服务端内存。
- `POST /api/availability/live/grid`：接受凭据、查询引用与目标日期，经过 BookingWindowPolicy、共享 UpstreamRequestGate 和有界 HTTP Transport 后返回只读 DTO。
- 开关 `LIVE_AVAILABILITY_ENABLED` 默认关闭，仅 `APP_ENV=development` 且服务端配置官方请求加密参数时可启用。生产配置始终关闭。
- 回传来源为 `live_observed_unverified / display_only_unverified`。实际读取时间有记录；60 秒只是本地 UI 过期提示阈值，不代表平台保证的库存有效期。
- 未标记占用的格子只表示没有冲突标记，不能视为已验证 available。DTO 不生成可用于 Matcher 的 Snapshot；`can_select/can_match/can_bind/can_book/can_pay/can_create_job` 均为 false。
- 查询失败清除旧观察，未使用旧响应冒充新库存；修改日期、计划上下文、凭据或 Session 会使观察失效。

## 本轮验证

- 全新临时 SQLite 初始化至 Schema 6，未新增 Migration，未迁移业务库。
- 后端 unittest 359 PASS；Vitest 207 PASS；Vite production build PASS。
- 既有 Flask/SQLite 人工计划 E2E 24/24 PASS，包括语义网格、历史、409 和账户隔离回归。
- Codex 内置浏览器实际登录合成账户、保存计划、读取官方类别和时段、查看历史。只读查询没有新增 PlanRevision；日期越界返回错误并保留未保存表单，观察过期提示实际出现。
- 1440×900 和 390×844 无页面横向溢出；手机网格局部横向滚动，时间列保持固定。真实格子无交互按钮。

## 下一阶段最少证据

在官方客户端取得一条“实体场馆显示名 → 选择动作 → 查询范围 → 场地归属”的完整关联；确认同一版本的原子时长/时间边界、库存状态契约和价格币种/单位。然后才能生成经过核验的 Snapshot、接入 Matcher 和显式计划绑定。报价、下单、预约执行与支付仍是后续独立能力。
