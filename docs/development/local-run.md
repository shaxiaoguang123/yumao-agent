# V1 Identity Foundation 本地启动

本文只启动 Flask/Vue 身份基础。它不连接上游预约服务，也不配置 Tailscale。

## 环境准备

后端使用现有 Conda `test` 环境；前端依赖由 npm lockfile 管理。

```bash
conda activate test
export APP_ENV=development
export DATABASE_PATH=instance/yumao.sqlite3
export APP_ALLOWED_ORIGINS=http://localhost:5173
```

为 CSRF HMAC 生成至少 32 个 CSPRNG 随机字节，并以无填充 base64url 形式只放入当前 shell 环境。命令不会把生成的值打印到终端：

```bash
export CSRF_HMAC_SECRET="$(conda run -n test python -c 'import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii"))')"
```

不要把实际密钥写入 Git、启动日志、截图或共享文档。需要在多次重启间保持同一密钥时，通过本机受保护的环境配置或密钥管理器注入；生产环境从密钥管理器提供 CSPRNG 生成的密钥。

## 初始化 SQLite 和管理员

迁移必须显式执行；Flask 应用启动不会自动迁移数据库。

```bash
conda run -n test python -m backend.migrate
conda run -n test python -m backend.cli create-admin --username <name>
```

管理员密码由命令交互提示输入，不要放在命令行参数中。`create-admin` 只在数据库还没有管理员记录时创建首个管理员。

## 启动 Flask 和 Vue

在项目根目录启动 Flask，并保持服务只监听本机回环地址：

```bash
conda run -n test python -m flask --app backend.app:create_app run --host 127.0.0.1 --port 5000
```

另开一个终端启动 Vue 开发服务器：

```bash
cd frontend
npm ci
npm run dev
```

打开 Vite 显示的本地地址（默认 `http://localhost:5173`）。Vite 将 `/api` 请求代理到 `http://127.0.0.1:5000`。前后端分开运行，Flask 不暴露到局域网或公网。

## 验证

在项目根目录运行后端测试：

```bash
conda run -n test python -m unittest discover -s backend/tests -v
```

在 `frontend/` 目录运行前端测试和生产构建：

```bash
npm test -- --run
npm run build
```
