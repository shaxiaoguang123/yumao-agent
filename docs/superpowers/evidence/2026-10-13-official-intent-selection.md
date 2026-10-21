# 官方显示选格与人工意向（2026-10-13）

本次针对日期切换、羽毛球单一查询和人工选格，复核本机 `req/1.js`，指纹仍为 `d0709c88bb7fb7e156a023cb32b0938253aea84f108fbf3dfc499b846813411e`。未解密未知 item、未提交抓包或私有标识。

## 直接确认的客户端规则

- `resetSeat` / 日历 `confirm` 清理选择并调用 bookingByTime。页面选择日期后可自动读取，不需要再点击查询。
- `timeList.status=0` 绘制格子，`1` 不绘制；未知值禁用。客户端初始状态1、选中2、已预订3；冲突类别映射 course0～course7。同坐标重复冲突按 `conflictList` 顺序覆盖，以最后一条还原官方显示；执行复核仍将任一显式冲突坐标视为不可选。
- `initVenueArray` / `handleChoose` 有 `isNew`、日期与 bookingstarttime/bookingendtime 门控。服务端复现显示门控；缺少必要字段时不允许选择意向，不能用无冲突代替可用性证据。
- 官方 CSS：未选择 `#fff`、已选择 `#f29f11`、已预订 `#0762c7`、不可预订 `#c8c8c8`；course0/6 其他活动 `#c6e0b4`，course1 体育课 `#ffe8a3`，course2 项目培训 `#b4c6e5`，course3 体训队 `#f8e1c5`，course4 艺术团 `#9bc2e4`，course5 工会活动 `#f4b084`。
- 客户端 min/max 时段限制有响应字段及初始默认1/6。当前人工模式保留单场地首选和有序备选的计划语义，不表示同时预约多块场地。

## 本次契约

现有 live projection 新增 `can_select_intent`、`intent_selectable`、活动类别与意向时间边界。原 `selectable/can_select/can_match/can_bind/can_book/can_pay/can_create_job` 仍 false。

意向边界来自相邻已观察时间标签，并标为 `adjacent_observed_time_labels`；这不证明实际原子时长或库存可执行语义。无结束边界、时间不连续、未知/占用/关闭状态均不允许组成最终意向。历史预览保持只读。价格仍隐藏，不假设价格币种或单位。

前端只从官方返回的唯一“羽毛球”语义选项取短期服务端引用，移除类别选择框，不硬编码查询标识。日期变化自动读取，重复点击当前日期也会刷新；快速切换只读取最后待处理日期，尊重服务端配置的共享请求间隔。无后台轮询；查询引用过期最多自动重新取得一次。限流仅在服务端给出合法 Retry-After 时等待后重试一次，失败后停止。

所有返回场地可参与意向选择，不受表单先填的场地名称限制。选择、取消、连续检查、备选排序后，先预览新旧值和备用范围，再应用到未保存表单；最后点击保存才经 PlanService 新增修订。选择的60秒显示有效期失效后不能继续确认。

只保存日期、开始时间、时长、场地语义顺序及用户确认的备用/预算策略；不保存坐标、原始ID、库存或观察时间戳。不将“羽毛球”类别自动当作实体场馆。VenueCatalog 仍为空，计划仍 `unbound_draft / unverified_manual`，正式绑定和执行能力未解除。

真实只读读取沿用已有用户 Credential、Session/CSRF、BookingWindowPolicy 和 UpstreamRequestGate。用户本次明确要求日期点击自动读取，并保留此前真实Token只读授权。没有调用报价、创建订单、支付或 Job。
