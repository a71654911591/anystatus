# AnyStatus

轻量 Web 服务，用于查询 [AnyRouter](https://anyrouter.top) API 令牌的额度与使用情况。提供简洁的中文页面与 JSON 接口，令牌仅用于实时向上游查询，**不会在服务端存储**。

## 功能

- 输入 `sk-` 开头的令牌，查看总额度、已用、剩余及使用率
- 自动识别无限额度账号
- 内置限流（每 IP 60 秒内最多 30 次）与基础安全响应头
- 支持 Docker 一键部署

## 快速开始

### Docker Compose（推荐）

```bash
docker compose up -d --build
```

浏览器访问：<http://localhost:8000>

### 本地运行

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000
```

## API

### `POST /api/query`

查询指定令牌的额度信息。

**请求体**

```json
{
  "key": "sk-your-token-here"
}
```

**成功响应示例**

```json
{
  "is_unlimited": false,
  "total_usd": 10.0,
  "used_usd": 2.3456,
  "remaining_usd": 7.6544,
  "usage_percent": 23.46
}
```

无限额度时，`total_usd`、`remaining_usd`、`usage_percent` 为 `null`，`is_unlimited` 为 `true`。

| 状态码 | 说明 |
|--------|------|
| 400 | 令牌格式不正确 |
| 401 | 令牌无效或已过期 |
| 413 | 请求体过大 |
| 429 | 请求过于频繁 |
| 502 | 上游服务不可达 |

### `GET /healthz`

健康检查，返回 `{"ok": true}`。

## 项目结构

```
.
├── app.py              # FastAPI 应用、Web 页面与查询逻辑
├── requirements.txt
├── Dockerfile
└── docker-compose.yml
```

## 说明

- 额度数据来自 AnyRouter 官方计费接口，本服务仅作代理与展示。
- 请勿在公网暴露未鉴权的实例；若需对外提供服务，建议置于反向代理之后并配置 HTTPS。
- Docker 镜像以非 root 用户运行，容器为只读根文件系统，内存限制 128MB。

## 技术栈

- [FastAPI](https://fastapi.tiangolo.com/)
- [httpx](https://www.python-httpx.org/)
- [uvicorn](https://www.uvicorn.org/)

## 许可证

未指定许可证时，请按你的使用场景自行补充。
