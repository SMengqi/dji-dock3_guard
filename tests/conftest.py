"""pytest 共享 fixture.

Phase 0 仅提供 recording fixture (设计 §3.5):
从兄弟服务 sim_dji_cloud_service/sim_dji_cloud/recordings/ 解析录制目录,
不复制、不 submodule、不符号链接.
"""

from __future__ import annotations

import pathlib

import pytest

# monorepo layout: ../sim_dji_cloud_service/sim_dji_cloud/recordings/
# 此文件位于 tests/, parents[1] = 项目根 dji-dock3-guard/, parents[2] = cloud_api/
RECORDINGS_ROOT = (
    pathlib.Path(__file__).resolve().parents[2]
    / "sim_dji_cloud_service"
    / "sim_dji_cloud"
    / "recordings"
)

# Phase 0 锁定的样本 (设计 §3.5 / §12).
DEFAULT_RECORDING = "8UUXN7N00A0GAA_20260605-165145"


@pytest.fixture(scope="session")
def recordings_root() -> pathlib.Path:
    """所有录制的根目录."""
    return RECORDINGS_ROOT


@pytest.fixture(scope="session")
def recording(request: pytest.FixtureRequest) -> pathlib.Path:
    """单份录制目录路径.

    用法:
        def test_x(recording): ...                           # 默认样本
        @pytest.mark.parametrize("recording", ["<sn>_<ts>"], indirect=True)
        def test_y(recording): ...
    """
    name = getattr(request, "param", DEFAULT_RECORDING)
    path = RECORDINGS_ROOT / name
    if not path.exists():
        pytest.skip(f"recording {name} not found at {path} — sim_dji_cloud_service may not be checked out")
    return path
