# 设计:飞行器速度曲线图(离线分析)

- **日期:** 2026-06-29
- **范围:** 离线分析报告新增"速度曲线"段(仅实际速度;水平主图 + 垂直副图)
- **目的:** 复盘时展示飞行器实际飞行速度时序,供人工对照飞控指令,检查是否按指定速度飞行
- **状态:** 已批准,待写实现计划

## 1. 背景与动机

离线分析(`dock_guard.analytics`)已能从录制目录回放生成飞行复盘报告,
报告含电池曲线、风速曲线、风向时序等时序图(mermaid + ASCII 双版本)。

本次新增飞行器**速度**时序图。最终目的是"下发飞控指令后,检查飞行器是否
按指定速度飞行"。经评审,本次只画**实际**速度(OSD 上报的真实飞行速度),
**不**解析下发的指定速度;人工复盘时将实际速度曲线与飞控指令对照查看。
指定速度(DRC up joystick 速度 / flyto `max_speed`)的自动对比留作后续扩展,
数据模型预留扩展位。

### 数据来源(现状,无需改动上游)
- `horizontal_speed` / `vertical_speed` 已是 OSD facts(见 `aggregator/facts.py`
  的 `F.HORIZONTAL_SPEED` / `F.VERTICAL_SPEED`,由 `dock_aggregator._snapshot_facts`
  从 drone OSD 填入),单位 m/s。
- `vertical_speed` 可为负(下降)。
- `horizontal_speed` 非负(水平合速度标量)。

## 2. 设计决策(评审结论)

| 决策点 | 结论 | 理由 |
|---|---|---|
| 功能范围 | 仅实际速度曲线 | 改动小,沿用电池/风速同套模式;指定速度对比留后续 |
| 速度量 | 水平主图 + 垂直副图 | 两段都复用现有单线 helper,信息全且改动适中 |
| schema 版本 | 保持 `SCHEMA_VERSION = 3` | 纯添加可选字段,与 `wind_direction` 先例一致 |

## 3. 数据模型(`src/dock_guard/analytics/models.py`)

给 `BatterySample` 增加两个**可选**字段(纯添加,默认 `None`):

```python
@dataclass(frozen=True, slots=True)
class BatterySample:
    rel_ms: int
    percent: int
    height_m: float
    wind_ms: float
    wind_direction: int | None = None
    # NEW: 飞行器速度时序 (m/s). None = 该采样时刻未上报.
    # 纯添加字段, schema_version 保持 3 (向后兼容).
    horizontal_speed_ms: float | None = None   # OSD horizontal_speed (>=0)
    vertical_speed_ms: float | None = None       # OSD vertical_speed (负=下降)
```

合成样例 JSON(一个采样点):
```json
{"rel_ms": 20000, "percent": 87, "height_m": 45.0, "wind_ms": 3.2,
 "wind_direction": 3, "horizontal_speed_ms": 8.5, "vertical_speed_ms": -1.2}
```

### 向后兼容
- 老 v3 `report.json` 缺这两字段 → `BatterySample(**s)`(见 `analytics/__main__.py`
  `_from_dict`)用默认 `None` 填充,batch 重读不报错。
- `_from_dict` 的 `schema != 3` 网关**无需改动**。
- 不发明新 schema 版本,与 `wind_direction` 处理完全一致
  (`models.py` 注释:"纯添加字段, schema_version 保持 3")。

## 4. 采集(`src/dock_guard/analytics/collector.py`)

在现有 10s 采样块内(已要求 `batt` + `height` + `wind` 全就绪才落样本),
**额外**读取速度并存入新字段:

```python
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

- 速度**不**加入采样门控:速度缺失时仅置 `None`,不丢整条样本,
  保持速度采样点与电池/风同步(同一 10s 栅格)。

## 5. 报告渲染(`src/dock_guard/analytics/report.py`)

新增 `_render_speed_chart(rep) -> list[str]`,产出**两段**,插入位置:
`render_markdown` 中 `## 电池曲线` 之后、`## 风速曲线` 之前(同属飞行器动力学时序)。

### 5.1 水平速度曲线(主图)
- 取样:`[s for s in rep.battery_samples if s.horizontal_speed_ms is not None]`
- 无样本 → `["## 水平速度曲线", "", "(无速度数据)"]`
- `y_min = 0`,`y_max = max(5.0, ceil(峰值))`
- mermaid(`_mermaid_line`,每分钟均值,`_aggregate_per_minute`)+ ASCII
  (`_render_line_chart`,原始 10s 点)双版本,复用现有单线 helper。
- Y 轴 label 格式:`{v:4.1f}m/s`(仿风速段)。
- 摘要:`峰值 X.X m/s · 平均 Y.Y m/s`。

### 5.2 垂直速度曲线(副图)
- 取样:`[s for s in rep.battery_samples if s.vertical_speed_ms is not None]`
- 无样本 → `["## 垂直速度曲线", "", "(无速度数据)"]`
- 支持负值:`y_min = min(-2.0, floor(谷值))`,`y_max = max(2.0, ceil(峰值))`
  (`_render_line_chart` 与 `_mermaid_line` 均已支持 `y_min` 参数)。
- Y 轴 label 含正负号:`{v:+5.1f}`(上升为正、下降为负)。
- 摘要:`最大上升 X.X m/s · 最大下降 Y.Y m/s`(下降取最负值绝对值)。

### 渲染接线
`render_markdown` 在 `_render_battery_chart` 段之后追加:
```python
parts.extend(_render_speed_chart(rep))
parts.append("")
```

## 6. 测试

### 6.1 `tests/unit/test_report_speed_chart.py`(仿 `test_report_wind_speed_chart.py`)
- 有数据:渲染含 `## 水平速度曲线` 与 `## 垂直速度曲线` 两段,各含 mermaid 块、
  ASCII 块、摘要行。
- 负垂速:vertical 段 y 轴出现负值 label。
- 无速度数据(样本 `horizontal_speed_ms` 全 `None`):走 `(无速度数据)`。

### 6.2 `tests/unit/test_analytics_collector.py`(补充)
- facts 含 `horizontal_speed` / `vertical_speed` 时,生成的 `BatterySample`
  带上对应速度值;缺失时为 `None`。

### 6.3 向后兼容
- 老 v3 `report.json`(无速度字段)batch 重读不崩(`BatterySample(**s)` 默认填 `None`),
  渲染走 `(无速度数据)`。可在现有 CLI/报告测试中加一条断言或新增小用例。

## 7. 不做(YAGNI)
- 不放开 `DOCK_DRC_UP`/`DOCK_DRC_DOWN`(replay 默认丢弃)。
- 不解析指定速度(DRC joystick / flyto `max_speed`)。
- 不加细采样(10s 栅格不变)。
- 不做实际 vs 指定的偏差标注 —— 全部属后续"对比"扩展,本次明确不做。
  数据模型如需扩展,再加 `commanded_speed_ms` 同理纯添加。

## 8. 影响面
- 改动文件:`models.py`、`collector.py`、`report.py` + 新增 1 个测试文件、补 1 个测试。
- 不改 CLI 接口、不改 `_from_dict` 网关、不改 schema 版本号。
- 推 main 前跑 ruff + pytest(CI 第一步是 ruff)。
