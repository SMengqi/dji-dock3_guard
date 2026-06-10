"""Stage 2 uvicorn 异步启动 hook.

设计: HTTP 服务与 MQTT ingest 在**同一进程同一 event loop** (用户选定).
调用方在 _run_live 中:
  server, task = await start_http_server(app, host=..., port=...)
  ...                      # 跑 MQTT 主循环
  server.should_exit = True
  await asyncio.wait_for(task, timeout=5.0)
"""

from __future__ import annotations

import asyncio

import uvicorn
from fastapi import FastAPI


async def start_http_server(
    app: FastAPI,
    *,
    host: str,
    port: int,
    log_level: str = "warning",
) -> tuple[uvicorn.Server, asyncio.Task[None]]:
    """启动 uvicorn 异步, 返回 (server, task).

    日志走 stderr; access log 关闭 (噪音, /healthz 每秒被 k8s 拨, 没必要打印).
    """
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level=log_level.lower(),
        access_log=False,
        lifespan="on",
    )
    server = uvicorn.Server(config)
    task: asyncio.Task[None] = asyncio.create_task(server.serve())
    # 等 server 真正监听后再返回, 否则 caller 立刻发请求会 connection refused.
    # uvicorn.Server.started 是 bool, server.serve() 内部把它置 True.
    for _ in range(50):
        if server.started:
            break
        await asyncio.sleep(0.02)
    return server, task
