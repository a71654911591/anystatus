from collections import defaultdict, deque
from time import monotonic
import re

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
import httpx

UPSTREAM = "https://anyrouter.top"
TIMEOUT = 10.0
UNLIMITED = 1e8
TOKEN_RE = re.compile(r"^sk-[A-Za-z0-9_-]{16,128}$")
RATE_MAX = 30
RATE_WINDOW = 60.0
MAX_BODY = 2048

app = FastAPI(title="令牌额度查询", docs_url=None, redoc_url=None, openapi_url=None)


class RateLimiter:
    def __init__(self, max_calls: int, window: float):
        self.max_calls = max_calls
        self.window = window
        self.calls: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = monotonic()
        q = self.calls[key]
        while q and q[0] < now - self.window:
            q.popleft()
        if len(q) >= self.max_calls:
            return False
        q.append(now)
        return True


limiter = RateLimiter(RATE_MAX, RATE_WINDOW)


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "?"


@app.middleware("http")
async def harden(request: Request, call_next):
    if request.method == "POST":
        cl = request.headers.get("content-length")
        if cl and int(cl) > MAX_BODY:
            return JSONResponse({"detail": "请求体过大"}, status_code=413)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; connect-src 'self'"
    )
    if "server" in response.headers:
        del response.headers["server"]
    return response


class QueryBody(BaseModel):
    key: str = Field(..., min_length=10, max_length=200)


async def _fetch(client: httpx.AsyncClient, path: str, **params):
    r = await client.get(f"{UPSTREAM}{path}", params=params or None)
    if r.status_code == 401:
        raise HTTPException(401, "令牌无效或已过期")
    r.raise_for_status()
    return r.json()


@app.post("/api/query")
async def query(request: Request, body: QueryBody):
    if not limiter.allow(client_ip(request)):
        raise HTTPException(429, "请求过于频繁，请稍后再试")

    key = body.key.strip()
    if not TOKEN_RE.match(key):
        raise HTTPException(400, "令牌格式不正确")

    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT,
            headers=headers,
            follow_redirects=False,
        ) as client:
            sub = await _fetch(client, "/v1/dashboard/billing/subscription")
            usage = await _fetch(
                client,
                "/v1/dashboard/billing/usage",
                start_date="2024-01-01",
                end_date="2099-12-31",
            )
    except httpx.RequestError:
        raise HTTPException(502, "上游服务不可达")

    total = float(sub.get("hard_limit_usd", 0))
    used = float(usage.get("total_usage", 0)) / 100
    unlimited = total >= UNLIMITED

    return {
        "is_unlimited": unlimited,
        "total_usd": None if unlimited else round(total, 4),
        "used_usd": round(used, 4),
        "remaining_usd": None if unlimited else round(total - used, 4),
        "usage_percent": None if unlimited or total <= 0 else round(used / total * 100, 2),
    }


@app.get("/healthz")
async def healthz():
    return {"ok": True}


INDEX_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>令牌额度查询</title>
<style>
  *{box-sizing:border-box}
  body{font-family:-apple-system,"Segoe UI",sans-serif;max-width:460px;margin:60px auto;padding:0 20px;color:#1a1a1a;background:#fafafa}
  h1{font-size:18px;font-weight:600;margin:0 0 20px}
  input{width:100%;padding:11px 14px;font-size:14px;border:1px solid #d8d8d8;border-radius:8px;outline:none;background:#fff;font-family:inherit}
  input:focus{border-color:#1a73e8}
  button{width:100%;margin-top:10px;padding:11px;font-size:14px;font-weight:500;background:#1a1a1a;color:#fff;border:0;border-radius:8px;cursor:pointer}
  button:disabled{opacity:.5;cursor:wait}
  .card{margin-top:20px;padding:18px 20px;background:#fff;border:1px solid #ececec;border-radius:10px;display:none}
  .row{display:flex;justify-content:space-between;align-items:center;padding:7px 0;font-size:14px;color:#555}
  .row b{color:#1a1a1a;font-weight:600;font-variant-numeric:tabular-nums}
  .bar{height:6px;background:#eee;border-radius:3px;overflow:hidden;margin-top:10px}
  .bar-fill{height:100%;background:linear-gradient(90deg,#1a73e8,#4285f4);transition:width .5s}
  .err{margin-top:14px;padding:10px 14px;background:#fdecea;color:#b3261e;border-radius:8px;font-size:13px;display:none}
  .muted{color:#999;font-size:12px;margin-top:14px;text-align:center}
</style>
</head>
<body>
<h1>令牌额度查询</h1>
<input id="key" placeholder="输入完整令牌，如 sk-xxxxx" autocomplete="off">
<button id="btn">查询</button>
<div class="err" id="err"></div>
<div class="card" id="card">
  <div class="row"><span>总额度</span><b id="total">—</b></div>
  <div class="row"><span>已使用</span><b id="used">—</b></div>
  <div class="row"><span>剩余</span><b id="rem">—</b></div>
  <div class="row"><span>使用率</span><b id="pct">—</b></div>
  <div class="bar"><div class="bar-fill" id="fill" style="width:0"></div></div>
</div>
<p class="muted">仅查询，不存储任何令牌</p>
<script>
const $ = id => document.getElementById(id);
const fmt = v => v == null ? '—' : '$' + v.toFixed(4).replace(/\\.?0+$/, '');
async function run(){
  const key = $('key').value.trim();
  const btn = $('btn'), err = $('err'), card = $('card');
  err.style.display = card.style.display = 'none';
  if(!key) return;
  btn.disabled = true; btn.textContent = '查询中...';
  try{
    const r = await fetch('/api/query',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({key})});
    const d = await r.json();
    if(!r.ok) throw new Error(d.detail || '查询失败');
    if(d.is_unlimited){
      $('total').textContent = '∞ 无限';
      $('rem').textContent = '∞ 无限';
      $('pct').textContent = '—';
      $('fill').style.width = '0%';
    }else{
      $('total').textContent = fmt(d.total_usd);
      $('rem').textContent = fmt(d.remaining_usd);
      $('pct').textContent = d.usage_percent + '%';
      $('fill').style.width = Math.min(d.usage_percent, 100) + '%';
    }
    $('used').textContent = fmt(d.used_usd);
    card.style.display = 'block';
  }catch(e){
    err.textContent = e.message;
    err.style.display = 'block';
  }finally{
    btn.disabled = false; btn.textContent = '查询';
  }
}
$('btn').addEventListener('click', run);
$('key').addEventListener('keydown', e => { if(e.key==='Enter') run(); });
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def index():
    return INDEX_HTML
