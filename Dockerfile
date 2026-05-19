FROM python:3.12-slim AS builder
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements.txt

FROM python:3.12-slim
RUN useradd -m -u 10001 -s /usr/sbin/nologin app
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY --chown=app:app app.py .
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request as r,sys; sys.exit(0 if r.urlopen('http://127.0.0.1:8000/healthz',timeout=2).status==200 else 1)"
CMD ["uvicorn","app:app","--host","0.0.0.0","--port","8000"]
