# Planning Agent MVP

## 用户路径

进入“设置 · AI模型”(`/settings/ai-models`)，添加多组完整模型配置，选择当前模型和默认模型。支持编辑、删除、替换/清除密钥以及用户主动连接测试。Planning Agent 使用当前选择，未选择时使用用户默认，再使用完整服务默认；已选配置缺密钥时直接报错，不继承其他配置的密钥。

在 `/plans` 输入自然语言，选择新建或已有计划，生成提案、查看补充问题或变化前后差异，再明确确认保存。取消或模型失败保留输入。旧版本保存返回 409，保留提案并允许明确读取最新版本、重新生成。手动编辑一直可用。

## 模型配置与密钥

- `GET/POST /api/ai/models`
- `PATCH/DELETE /api/ai/models/<id>` 使用 `base_version`
- `PATCH /api/ai/models/preferences` 使用 `selected_model_id` 和 `default_model_id`
- `POST /api/ai/models/<id>/test` 仅主动点击触发轻量 Chat Completions 请求

用户模型字段为 `name,base_url,model,auth_mode` 和可选 `api_key`，认证模式为 `bearer/none`。密钥只提交到后端，DTO 只返回 `has_api_key`。API Key 可清除；bearer 配置因此变为不可用，不会继承服务级密钥。更换 Base URL 时必须明确替换或删除原密钥。

服务默认是完整的 `LLM_BASE_URL,LLM_MODEL,LLM_AUTH_MODE,LLM_PROTOCOL`，bearer 还需 `LLM_API_KEY`。协议为 `openai-chat-completions`，Base URL 为 API 根地址（例如 `/v1`），不填写完整 `/chat/completions` 路径。部署默认未配置不影响手动计划。生产用户自己在页面添加模型，不需要把模型密钥写入部署环境。

Schema 6 新增 `ai_models` 和 `ai_model_preferences`；0001～0005 不变。AES-GCM 使用从现有应用主密钥经 HKDF 派生的 AI 专用子密钥，salt 绑定用户和模型，AAD 绑定用户/模型/密钥版本。子密钥不直接复用 Credential Token 的加密密钥。原应用主密钥轮换时须保留被 AI 配置引用的旧密钥版本。主密钥仍只来自部署配置，不写 SQLite。

Provider 只接受公网上的 HTTPS/443 地址，禁止 URL 凭据、查询、fragment、危险路径、私网/loopback/link-local/保留/多播/IPv4-mapped 地址及混合 DNS 结果。保存时和请求时验证，每次 TLS 连接固定到通过验证的地址，SNI/证书验证原始主机名。无代理、重定向或自动重试 POST；有 DNS、连接、读取、总时限、输出 token 和响应字节限制。错误仅返回安全分类，不返回供应商原文或密钥。

## 提案与保存边界

`POST /api/planning/proposals` 接受完整对象 `{message,plan_id,base_version}`，新建后两项为 null；编辑只读取 Session 用户拥有且版本匹配的计划。请求最多 16 KiB，文本最多 4000 字。输出为 ready / needs_input / unsupported，ready 附带完整人工意向、服务器 context/window 和差异。

模型只收到当前请求、服务器业务日期/相对日期表、语义 context 和当前用户拥有的意向字段，不收到用户ID、计划ID、认证材料、Credential、抓包、原始数据库或 HTTP 工具。禁止预约、支付或 Job 工具。

模型输出需严格 JSON envelope，并通过 `parse_manual_intent`。重要字段要求用户原文依据，场馆/新场地文本不得凭空添加；“下周”按下一自然周解析，已命名相对日期及明确 HH:MM 由服务器进一步核对。信息不足返回补充问题。模型结果不写数据库。

只有前端明确确认才调用现有 `/api/plans` POST/PATCH；PlanService 再次校验日期/类型/上下文/权限/base_version，并创建不可变 PlanRevision。生成后并发修改仍通过 409 保护。提案不持久化，不自动重新基于新版本保存。

所有保存内容仍是 `unbound_draft/unverified_manual`，无上游查询、预约、支付或 Job 资格。Task 0 保持 PARTIAL，Task 1B 保持 BLOCKED。

## 验证边界

自动测试与隔离浏览器实例使用合成配置、Fake Provider、全新临时 SQLite，并阻止真实 HTTP/外部 socket。Fake 通过证明 Flask/SQLite/前端链路，不证明真实供应商可用性。真实模型只能由用户之后主动在页面配置并点击测试。

官方 Chat Completions 请求格式参考：https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create 。兼容适配只使用普通 messages、model、max_tokens 和非流式文本输出，结构约束由服务端验证，不依赖供应商支持 JSON mode 或工具调用。
