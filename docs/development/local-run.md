# V1 Identity and Credential 本地启动

本文说明如何在本机启动 Flask/Vue 身份基础和 Credential Token 生命周期功能。它不启动预约执行器，也不配置 Booking、Worker、支付、LLM 或 Tailscale。

## 环境和运行配置

后端使用现有 Conda `test` 环境，前端使用仓库的 npm lockfile：

```bash
conda activate test
export APP_ENV=development
export DATABASE_PATH=instance/yumao.sqlite3
export APP_ALLOWED_ORIGINS=http://localhost:5173
export UPSTREAM_ORIGIN=https://bdtyg.cugb.edu.cn
export UPSTREAM_CONNECT_TIMEOUT_SECONDS=3
export UPSTREAM_READ_TIMEOUT_SECONDS=5
export UPSTREAM_TOTAL_DEADLINE_SECONDS=10
export UPSTREAM_MAX_RESPONSE_BYTES=65536
export UPSTREAM_RETRY_AFTER_FALLBACK_SECONDS=30
export MAX_UPSTREAM_BACKOFF_SECONDS=900
export UPSTREAM_LEASE_SAFETY_MARGIN_SECONDS=6
```

为 CSRF、Token 加密和指纹 HMAC 分别生成独立的 32 字节 CSPRNG 密钥。下面的命令把无填充 base64url 值直接放入当前 shell 环境，不会把生成值写进 Git：

```bash
export CSRF_HMAC_SECRET="$(conda run -n test python -c 'import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii"))')"
export APP_CREDENTIAL_ENCRYPTION_KEYS="$(conda run -n test python -c 'import base64,json,secrets; value=base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii"); print(json.dumps({"enc-v1":value},separators=(",",":")))')"
export APP_CREDENTIAL_ENCRYPTION_ACTIVE_KEY_ID=enc-v1
export APP_UPSTREAM_FINGERPRINT_KEYS="$(conda run -n test python -c 'import base64,json,secrets; value=base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii"); print(json.dumps({"fp-v1":value},separators=(",",":")))')"
export APP_UPSTREAM_FINGERPRINT_ACTIVE_KEY_ID=fp-v1
```

首次生成后，应通过本机受保护的环境配置或密钥管理器保存这些值，后续重启时继续注入相同密钥。不要在每次启动时重新生成，不要把实际密钥写入 Git、日志、截图或共享文档。加密 keyring 与 fingerprint HMAC keyring 必须保持独立，不得复用 key material。

`UPSTREAM_GET_USER_INFO_MIN_INTERVAL_MS` 的 `getUserInfo` 请求间隔目前没有 endpoint-specific 抓包证据，因此保持未设置。此时添加、验证或轮换 Credential 会返回 `503 validation_not_configured`，不会保存提交的候选 Token。不要用其他上游接口观察到的约 668 ms 间隔替代它。设置该值前，需要先取得针对 `getUserInfo` 的证据并重新评审。

JWT `exp` 只用于本地到期提醒；Token 当前是否有效仍由用户发起的只读 `getUserInfo` 验证确认。该操作会经过所有用户和 Credential 共用的 SQLite `UpstreamRequestGate`。

## 初始化数据库和管理员

应用启动不会自动迁移。每次升级代码后，先显式应用版本化迁移：

```bash
conda run -n test python -m backend.migrate
conda run -n test python -m backend.cli create-admin --username <name>
```

`create-admin` 只在数据库尚无管理员时创建首个管理员，密码由命令交互提示输入。应用 startup 会只读检查 schema 和当前数据库仍依赖的加密/HMAC key versions；如果某个 key 仍被活动数据引用却未配置，应用会 fail fast。

## 轮换 Token 加密密钥

Token 加密 key rotation 必须使用显式维护命令。先把新 key version 加入 `APP_CREDENTIAL_ENCRYPTION_KEYS`，将 `APP_CREDENTIAL_ENCRYPTION_ACTIVE_KEY_ID` 指向新版本，并保留旧版本；然后使用当前活动管理员的内部 user ID 执行：

```bash
conda run -n test python -m backend.cli rewrap-credential-tokens --actor-user-id <active-admin-user-id>
```

该命令在一个 SQLite 事务中认证每个活动 Token envelope、用活动加密 key 重新封装，并追加安全生命周期审计。失败时全部回滚。成功后，应用启动的只读依赖检查可确认旧加密 key 是否仍被活动 ciphertext 引用；只有确认没有剩余依赖后，才能从配置中移除旧加密 key。

指纹 HMAC keyring 与 Token 加密 keyring 分开维护。当前 Token fingerprint 和非删除 Credential 的账户 fingerprint 仍引用旧 HMAC key version 时，启动依赖检查会要求继续保留该 key。重包命令只轮换 Token ciphertext，不会改写 fingerprint。

## 启动 Flask 和 Vue

在项目根目录启动 Flask，并只监听本机回环地址：

```bash
conda run -n test python -m flask --app backend.app:create_app run --host 127.0.0.1 --port 5000
```

另开一个终端启动 Vue 开发服务器：

```bash
cd frontend
npm ci
npm run dev
```

打开 Vite 显示的本地地址（默认 `http://localhost:5173`）。Vite 将 `/api` 请求代理到 `http://127.0.0.1:5000`。登录后可在“预约凭据”页添加、验证、轮换、停用、重新启用或删除 Credential。用户发起这些操作时才会尝试调用只读上游验证；测试和启动过程不会调用真实上游。

Werkzeug 访问日志会被收敛为不含客户端地址和请求路径的通用事件，避免请求目标或查询参数进入日志。

## 验证

在项目根目录运行后端测试：

```bash
conda run -n test python -m unittest discover -s backend/tests -v
```

在 `frontend/` 目录运行前端测试和 production build：

```bash
npm test -- --run
npm run build
```
