"""Stage 2 ADMIN_TOKEN 鉴权 (设计 §10.1 / §10.5).

行为:
- 启动期 fail-fast: 未注入 ADMIN_TOKEN -> 拒启 (Stage 2 用户选定).
- /admin/* 强制 token (Bearer 或 X-Admin-Token header).
- /healthz / /readyz 永远豁免 (K8s liveness/readiness 不应需 token).
- /events 暂走 token (B3 启用时确认).
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Header, HTTPException, status

from dock_guard.http.state import HttpState


class TokenMissing(ValueError):
    """ADMIN_TOKEN 未在环境变量中提供."""


def load_admin_token(env_value: str | None) -> str:
    """启动期校验: env 取空或缺失即抛 TokenMissing.

    用户在 Stage 2 选型时选定了 '拒启' 而非 '免鉴权 + 警告', 因此
    本函数无 fallback.
    """
    if not env_value or not env_value.strip():
        raise TokenMissing(
            "ADMIN_TOKEN 未注入 (.env 或 export). Stage 2 控制面要求 token. "
            "生成: python -c 'import secrets; print(secrets.token_hex(32))' "
            "然后写入 .env 的 ADMIN_TOKEN= 行 (或 export ADMIN_TOKEN=...)."
        )
    return env_value.strip()


def make_admin_token_dependency(state: HttpState) -> Callable[..., None]:
    """FastAPI dependency 工厂: 闭包持 state.admin_token, 返回 verify 函数.

    用法:
      router = APIRouter(dependencies=[Depends(make_admin_token_dependency(state))])
    """
    expected = state.admin_token

    def verify(
        authorization: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
    ) -> None:
        token: str | None = None
        if authorization and authorization.lower().startswith("bearer "):
            token = authorization[7:].strip()
        elif x_admin_token:
            token = x_admin_token.strip()
        if not token or token != expected:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="missing or invalid admin token",
            )

    return verify
