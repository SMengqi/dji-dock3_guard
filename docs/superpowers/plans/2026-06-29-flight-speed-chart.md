# 飞行器速度曲线图 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 离线分析报告新增"速度曲线"段——展示飞行器实际水平/垂直速度时序,供人工对照飞控指令检查是否按指定速度飞行。

**Architecture:** 沿用现有电池/风速曲线同套模式。给 `BatterySample` 加两个可选速度字段(纯添加,schema 保持 v3);collector 在现有 10s 采样块里顺带读速度;report 新增 `_render_speed_chart` 渲染水平(主图)+ 垂直(副图,支持负值)两段,各出 mermaid + ASCII 双版本,复用现有单线 helper。

**Tech Stack:** Python 3.12, dataclasses, pytest, ruff. 无新依赖。

## Global Constraints

- `SCHEMA_VERSION` 保持 `3` 不变——速度字段为纯添加可选字段(与 `wind_direction` 先例一致),不改 `analytics/__main__.py:_from_dict` 的 `schema != 3` 网关。
- 单位 m/s。`horizontal_speed` 非负;`vertical_speed` 可负(负=下降)。
- 速度**不**加入采样门控:速度缺失只置 `None`,不丢整条样本。
- 本次只画实际速度;**不**放开 DRC、**不**解析指定速度、**不**改采样粒度(YAGNI)。
- 推 main 前必须先跑 `ruff check .` 再跑 `pytest`(CI 第一步是 ruff)。
- 提交直推 main;commit message 末尾加 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。

---

### Task 1: 数据模型 — `BatterySample` 速度字段

**Files:**
- Modify: `src/dock_guard/analytics/models.py:16-26` (`BatterySample`)
- Test: `tests/unit/test_speed_sample.py` (新建)

**Interfaces:**
- Consumes: 无
- Produces: `BatterySample(..., horizontal_speed_ms: float | None = None, vertical_speed_ms: float | None = None)` — 后续 Task 2(collector 填值)、Task 3(report 读值)依赖这两个字段名与默认值。

- [ ] **Step 1: 写失败测试**

新建 `tests/unit/test_speed_sample.py`:

```python
"""BatterySample 速度字段单测 (纯添加, 默认 None, 向后兼容老 dict)."""

from __future__ import annotations

from dataclasses import asdict

from dock_guard.analytics.models import BatterySample


def test_speed_fields_default_none() -> None:
    s = BatterySample(rel_ms=0, percent=80, height_m=10.0, wind_ms=2.0)
    assert s.horizontal_speed_ms is None
    assert s.vertical_speed_ms is None


def test_speed_fields_roundtrip_asdict() -> None:
    s = BatterySample(
        rel_ms=0, percent=80, height_m=10.0, wind_ms=2.0,
        horizontal_speed_ms=8.5, vertical_speed_ms=-1.2,
    )
    d = asdict(s)
    assert d["horizontal_speed_ms"] == 8.5
    assert d["vertical_speed_ms"] == -1.2


def test_old_sample_dict_without_speed_loads() -> None:
    """老 v3 report.json 的样本 dict 无速度字段 -> BatterySample(**s) 默认填 None."""
    old = {
        "rel_ms": 0, "percent": 80, "height_m": 10.0,
        "wind_ms": 2.0, "wind_direction": None,
    }
    s = BatterySample(**old)
    assert s.horizontal_speed_ms is None
    assert s.vertical_speed_ms is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/unit/test_speed_sample.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'horizontal_speed_ms'`

- [ ] **Step 3: 加字段**

在 `src/dock_guard/analytics/models.py` 的 `BatterySample` 里,`wind_direction` 行之后追加:

```python
    wind_direction: int | None = None
    # 飞行器速度时序 (m/s). None = 该采样时刻未上报.
    # 纯添加字段, schema_version 保持 3 (向后兼容, 同 wind_direction).
    horizontal_speed_ms: float | None = None   # OSD horizontal_speed (>=0)
    vertical_speed_ms: float | None = None       # OSD vertical_speed (负=下降)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/unit/test_speed_sample.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: ruff + 提交**

```bash
ruff check src/dock_guard/analytics/models.py tests/unit/test_speed_sample.py
git add src/dock_guard/analytics/models.py tests/unit/test_speed_sample.py
git commit -m "feat(analytics): BatterySample 加水平/垂直速度字段 (纯添加, schema v3)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: 采集 — collector 顺带采速度

**Files:**
- Modify: `src/dock_guard/analytics/collector.py:108-124` (10s 采样块)
- Test: `tests/unit/test_analytics_collector.py` (追加 `_speed_sequence` + `TestSpeedSampling`)

**Interfaces:**
- Consumes: `BatterySample(horizontal_speed_ms=..., vertical_speed_ms=...)` (Task 1)
- Produces: `collect(...).battery_samples[i].horizontal_speed_ms / .vertical_speed_ms` 反映 facts 里的 `horizontal_speed` / `vertical_speed`(缺失为 `None`)。

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_analytics_collector.py` 末尾追加(文件已有 `pytest`、`pathlib`、`_seed_config`、`_make_recording`、`collect` 导入):

```python
def _speed_sequence() -> list[dict]:
    """单帧 drone OSD 同时带 battery + height + wind_speed + 水平/垂直速度,
    确保落一条 battery_sample 且带速度."""
    base = 1700000000000
    return [
        {"recv_ts_ms": base, "topic": "sys/product/TEST_DOCK_01/status",
         "payload": {"sub_type": 0}},
        {"recv_ts_ms": base + 200, "topic": "thing/product/TEST_DOCK_01/osd",
         "payload": {"data": {
             "flighttask_step_code": 1, "drone_in_dock": 0,
             "sub_device": {"device_sn": "TEST_DRONE_01"},
         }, "timestamp": base + 200}},
        {"recv_ts_ms": base + 300, "topic": "thing/product/TEST_DRONE_01/osd",
         "payload": {"data": {
             "mode_code": 0, "height": 30.0,
             "wind_speed": 40,            # drone OSD 0.1 m/s -> 4.0 m/s
             "wind_direction": 3,
             "horizontal_speed": 8.5,
             "vertical_speed": -1.2,
             "battery": {"capacity_percent": 80},
         }, "timestamp": base + 300}},
    ]


class TestSpeedSampling:
    def test_battery_sample_carries_speed(self, tmp_path: pathlib.Path) -> None:
        cfg = _seed_config(tmp_path)
        rec = _make_recording(tmp_path, _speed_sequence())
        rep = collect(rec, cfg)
        assert rep.battery_samples, "expected at least one battery_sample"
        s = rep.battery_samples[0]
        assert s.horizontal_speed_ms == pytest.approx(8.5)
        assert s.vertical_speed_ms == pytest.approx(-1.2)

    def test_speed_none_when_absent(self, tmp_path: pathlib.Path) -> None:
        cfg = _seed_config(tmp_path)
        seq = _speed_sequence()
        del seq[2]["payload"]["data"]["horizontal_speed"]
        del seq[2]["payload"]["data"]["vertical_speed"]
        rec = _make_recording(tmp_path, seq)
        rep = collect(rec, cfg)
        assert rep.battery_samples, "expected at least one battery_sample"
        s = rep.battery_samples[0]
        assert s.horizontal_speed_ms is None
        assert s.vertical_speed_ms is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/unit/test_analytics_collector.py::TestSpeedSampling -v`
Expected: FAIL — `test_battery_sample_carries_speed` 报 `assert None == 8.5 ± ...`(字段已存在但 collector 还没填值)

- [ ] **Step 3: collector 采样块读速度**

`src/dock_guard/analytics/collector.py` 把现有这段:

```python
                        wd = frame.facts.get("wind_direction")
                        wd_int = wd if isinstance(wd, int) and 1 <= wd <= 8 else None
                        battery_samples.append(BatterySample(
                            rel_ms=rel_ms, percent=batt,
                            height_m=float(height), wind_ms=float(wind),
                            wind_direction=wd_int,
                        ))
```

改成:

```python
                        wd = frame.facts.get("wind_direction")
                        wd_int = wd if isinstance(wd, int) and 1 <= wd <= 8 else None
                        hs = frame.facts.get("horizontal_speed")
                        vs = frame.facts.get("vertical_speed")
                        hs_f = float(hs) if isinstance(hs, (int, float)) else None
                        vs_f = float(vs) if isinstance(vs, (int, float)) else None
                        battery_samples.append(BatterySample(
                            rel_ms=rel_ms, percent=batt,
                            height_m=float(height), wind_ms=float(wind),
                            wind_direction=wd_int,
                            horizontal_speed_ms=hs_f, vertical_speed_ms=vs_f,
                        ))
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/unit/test_analytics_collector.py -v`
Expected: PASS(原有用例 + `TestSpeedSampling` 2 条全过)

- [ ] **Step 5: ruff + 提交**

```bash
ruff check src/dock_guard/analytics/collector.py tests/unit/test_analytics_collector.py
git add src/dock_guard/analytics/collector.py tests/unit/test_analytics_collector.py
git commit -m "feat(analytics): collector 10s 采样顺带采水平/垂直速度

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: 渲染 — `## 水平速度曲线` + `## 垂直速度曲线`

**Files:**
- Modify: `src/dock_guard/analytics/report.py` (新增 `_render_speed_chart`;`render_markdown` 接线)
- Test: `tests/unit/test_report_speed_chart.py` (新建)

**Interfaces:**
- Consumes: `rep.battery_samples[i].horizontal_speed_ms / .vertical_speed_ms` (Task 1/2);现有 `_aggregate_per_minute`、`_mermaid_line(y_min=...)`、`_render_line_chart(y_min=..., y_label_fmt=...)`。
- Produces: markdown 含 `## 水平速度曲线`、`## 垂直速度曲线` 两段,位于 `## 电池曲线` 之后、`## 风速曲线` 之前。

- [ ] **Step 1: 写失败测试**

新建 `tests/unit/test_report_speed_chart.py`:

```python
"""单架次报告"## 水平/垂直速度曲线"段单测 (仿 test_report_wind_speed_chart)."""

from __future__ import annotations

import re

from dock_guard.analytics.models import (
    SCHEMA_VERSION,
    BatterySample,
    FlightMetrics,
    FlightReport,
)
from dock_guard.analytics.report import render_markdown


def _make_report(samples: list[BatterySample]) -> FlightReport:
    m = FlightMetrics(
        peak_wind_gust_30s=None, peak_wind_gust_30s_at_ms=None,
        min_battery_percent=None, min_battery_percent_at_ms=None,
        longest_offline_ms=0, flight_duration_ms=0,
        total_verdicts=0, total_dispatched=0, total_suppressed=0,
        verdicts_by_code={}, wind_direction_seconds={},
    )
    return FlightReport(
        schema_version=SCHEMA_VERSION, recording="x",
        dock_sn="D", drone_sn=None,
        started_at_ms=1700000000000, ended_at_ms=1700000420000,
        duration_ms=420000, total_envelopes=0,
        envelope_counts_by_topic_key={},
        phase_transitions=[], verdicts=[], alert_decisions=[],
        metrics=m, battery_samples=samples,
    )


class TestSpeedChart:
    def test_no_samples_placeholder(self) -> None:
        md = render_markdown(_make_report([]))
        assert "## 水平速度曲线" in md
        assert "## 垂直速度曲线" in md
        assert "无速度数据" in md

    def test_renders_dual_charts(self) -> None:
        """双版本: mermaid + ASCII, 两段都出."""
        samples = [
            BatterySample(rel_ms=0, percent=100, height_m=10, wind_ms=2.0,
                          horizontal_speed_ms=0.0, vertical_speed_ms=2.0),
            BatterySample(rel_ms=60_000, percent=85, height_m=30, wind_ms=3.0,
                          horizontal_speed_ms=8.5, vertical_speed_ms=0.5),
            BatterySample(rel_ms=120_000, percent=70, height_m=40, wind_ms=4.0,
                          horizontal_speed_ms=10.2, vertical_speed_ms=-1.5),
            BatterySample(rel_ms=180_000, percent=55, height_m=20, wind_ms=3.0,
                          horizontal_speed_ms=6.0, vertical_speed_ms=-2.5),
        ]
        md = render_markdown(_make_report(samples))
        assert "## 水平速度曲线" in md
        assert "## 垂直速度曲线" in md
        assert "```mermaid" in md
        assert "xychart-beta" in md
        assert "█" in md
        assert "m/s" in md

    def test_vertical_axis_has_negative(self) -> None:
        samples = [
            BatterySample(rel_ms=0, percent=100, height_m=40, wind_ms=2.0,
                          horizontal_speed_ms=5.0, vertical_speed_ms=1.0),
            BatterySample(rel_ms=60_000, percent=80, height_m=10, wind_ms=3.0,
                          horizontal_speed_ms=5.0, vertical_speed_ms=-3.0),
        ]
        md = render_markdown(_make_report(samples))
        assert "-3.0" in md                       # 垂直副图 y 轴底端负值 label
        assert "最大下降 3.0 m/s" in md

    def test_horizontal_summary_peak_avg(self) -> None:
        samples = [
            BatterySample(rel_ms=0, percent=100, height_m=10, wind_ms=2.0,
                          horizontal_speed_ms=4.0, vertical_speed_ms=0.0),
            BatterySample(rel_ms=60_000, percent=80, height_m=20, wind_ms=3.0,
                          horizontal_speed_ms=8.0, vertical_speed_ms=0.0),
        ]
        md = render_markdown(_make_report(samples))
        assert re.search(r"峰值 8\.0 m/s", md) is not None
        assert re.search(r"平均 6\.0 m/s", md) is not None

    def test_section_after_battery_before_wind(self) -> None:
        samples = [BatterySample(rel_ms=0, percent=80, height_m=10, wind_ms=2.0,
                                 horizontal_speed_ms=5.0, vertical_speed_ms=0.0)]
        md = render_markdown(_make_report(samples))
        i_batt = md.find("## 电池曲线")
        i_h = md.find("## 水平速度曲线")
        i_wind = md.find("## 风速曲线")
        assert 0 < i_batt < i_h < i_wind
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/unit/test_report_speed_chart.py -v`
Expected: FAIL — `assert "## 水平速度曲线" in md`(段还没渲染)

- [ ] **Step 3: 实现 `_render_speed_chart` 并接线**

在 `src/dock_guard/analytics/report.py` 的 `_render_battery_chart` 之后(`_render_wind_speed_chart` 之前)新增:

```python
def _render_speed_chart(rep: FlightReport) -> list[str]:
    """速度曲线: 水平 (主图, y>=0) + 垂直 (副图, 支持负值). 各 mermaid + ASCII."""
    import math

    lines: list[str] = []

    # ── 水平速度 (主图) ──
    h = [s for s in rep.battery_samples if s.horizontal_speed_ms is not None]
    lines.append("## 水平速度曲线")
    lines.append("")
    if not h:
        lines.append("(无速度数据)")
    else:
        duration_min = max(1, (h[-1].rel_ms - h[0].rel_ms) // 60_000 + 1)
        minute_values = _aggregate_per_minute(
            h, value_func=lambda s: s.horizontal_speed_ms, duration_min=duration_min,
        )
        peak = max(s.horizontal_speed_ms for s in h)
        avg = sum(s.horizontal_speed_ms for s in h) / len(h)
        y_max = max(5.0, math.ceil(peak))
        lines.extend(_mermaid_line(
            title="水平速度", x_labels=list(range(duration_min)),
            y_label="m/s", values=minute_values, y_max=y_max,
        ))
        lines.append("")
        lines.append("终端文本图:")
        lines.append("")
        lines.append("```")
        pairs = [(s.rel_ms, s.horizontal_speed_ms) for s in h]
        lines.extend(_render_line_chart(
            pairs, height=8, width=60, y_min=0, y_max=y_max,
            y_label_fmt=lambda v: f"{v:4.1f}m/s",
        ))
        lines.append("```")
        lines.append("")
        lines.append(f"峰值 {peak:.1f} m/s · 平均 {avg:.1f} m/s")

    lines.append("")

    # ── 垂直速度 (副图, 正=上升 负=下降) ──
    v = [s for s in rep.battery_samples if s.vertical_speed_ms is not None]
    lines.append("## 垂直速度曲线")
    lines.append("")
    if not v:
        lines.append("(无速度数据)")
        return lines

    duration_min = max(1, (v[-1].rel_ms - v[0].rel_ms) // 60_000 + 1)
    minute_values = _aggregate_per_minute(
        v, value_func=lambda s: s.vertical_speed_ms, duration_min=duration_min,
    )
    vmax = max(s.vertical_speed_ms for s in v)
    vmin = min(s.vertical_speed_ms for s in v)
    y_max = max(2.0, math.ceil(vmax))
    y_min = min(-2.0, math.floor(vmin))
    lines.extend(_mermaid_line(
        title="垂直速度 (正=上升 负=下降)", x_labels=list(range(duration_min)),
        y_label="m/s", values=minute_values, y_max=y_max, y_min=y_min,
    ))
    lines.append("")
    lines.append("终端文本图:")
    lines.append("")
    lines.append("```")
    pairs = [(s.rel_ms, s.vertical_speed_ms) for s in v]
    lines.extend(_render_line_chart(
        pairs, height=8, width=60, y_min=y_min, y_max=y_max,
        y_label_fmt=lambda val: f"{val:+5.1f}",
    ))
    lines.append("```")
    lines.append("")
    max_up = max(0.0, vmax)
    max_down = abs(min(0.0, vmin))
    lines.append(f"最大上升 {max_up:.1f} m/s · 最大下降 {max_down:.1f} m/s")
    return lines
```

在 `render_markdown` 里,把现有这两行:

```python
    parts.extend(_render_battery_chart(rep))
    parts.append("")
    parts.extend(_render_wind_speed_chart(rep))
```

改成(中间插入速度段):

```python
    parts.extend(_render_battery_chart(rep))
    parts.append("")
    parts.extend(_render_speed_chart(rep))
    parts.append("")
    parts.extend(_render_wind_speed_chart(rep))
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/unit/test_report_speed_chart.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: 全量回归 + ruff**

Run:
```bash
ruff check .
python -m pytest tests/unit -q
```
Expected: ruff 无错;pytest 全过(确认未破坏电池/风速/风向等既有段)。

- [ ] **Step 6: 提交**

```bash
git add src/dock_guard/analytics/report.py tests/unit/test_report_speed_chart.py
git commit -m "feat(analytics): 报告新增水平/垂直速度曲线段 (mermaid + ASCII)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## 收尾

- [ ] 三个 task 全绿后,按项目惯例直推 main 前再跑一遍 `ruff check .` + `python -m pytest -q`,然后 `git push`。
- [ ] (可选) 手工对一份真实录制跑 `python -m dock_guard.analytics <recording_dir> --force`,肉眼确认 `report.md` 里两段速度曲线渲染正常。
