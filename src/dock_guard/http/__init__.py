"""Stage 2: HTTP 控制面 (设计 §7.2 + §8 + §9.3)."""

from dock_guard.http.admin import DockMuteRequest, GlobalMuteRequest, register_admin
from dock_guard.http.app import build_app
from dock_guard.http.auth import TokenMissing, load_admin_token, make_admin_token_dependency
from dock_guard.http.events import EventBus
from dock_guard.http.server import start_http_server
from dock_guard.http.state import HttpState

__all__ = [
    "DockMuteRequest",
    "EventBus",
    "GlobalMuteRequest",
    "HttpState",
    "TokenMissing",
    "build_app",
    "load_admin_token",
    "make_admin_token_dependency",
    "register_admin",
    "start_http_server",
]
