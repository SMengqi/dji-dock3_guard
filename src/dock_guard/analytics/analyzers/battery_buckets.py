"""Stage 5-F: 电池分桶 + 速率 + 30s 滑窗 (设计 §7.1-§7.2).

bucket_key_for: (wind, height, percent) -> 桶 key str
compute_discharge_rates: BatterySample list -> 速率 list (差分, %/秒)
smooth_30s: 速率 list -> 30s 滑窗均值 (3 个相邻样本)
group_rates_by_bucket: 按 sample 的桶 key 把 rate 分组
"""

from __future__ import annotations

from collections import defaultdict

from dock_guard.analytics.models import BatterySample

# 分桶切点 (设计 D9 / D10)
WIND_BREAKS = [3.0, 6.0]      # 桶: [0,3), [3,6), [6, +inf)
HEIGHT_BREAK = 50.0           # 桶: [0,50), [50, +inf)
SOC_BREAKS = [30, 60]         # 桶: [0,30), [30,60), [60,100]


def bucket_key_for(wind_ms: float, height_m: float, percent: int) -> str:
    """生成桶 key, 例: w0_3.h_lt50.soc_high.

    SOC: low=[0,30) / mid=[30,60) / high=[60,100]
    """
    if wind_ms < WIND_BREAKS[0]:
        w = "w0_3"
    elif wind_ms < WIND_BREAKS[1]:
        w = "w3_6"
    else:
        w = "w6_inf"
    h = "h_lt50" if height_m < HEIGHT_BREAK else "h_ge50"
    if percent < SOC_BREAKS[0]:
        s = "soc_low"
    elif percent < SOC_BREAKS[1]:
        s = "soc_mid"
    else:
        s = "soc_high"
    return f"{w}.{h}.{s}"


def compute_discharge_rates(samples: list[BatterySample]) -> list[float]:
    """每相邻 2 样本算 1 个速率 (%/秒). 返长度 = len(samples) - 1.

    dt_ms <= 0 -> rate=0.0 (鲁棒, 不抛 ZeroDivisionError).
    """
    rates: list[float] = []
    for i in range(1, len(samples)):
        dt_ms = samples[i].rel_ms - samples[i - 1].rel_ms
        if dt_ms <= 0:
            rates.append(0.0)
            continue
        dpct = samples[i - 1].percent - samples[i].percent
        rates.append(dpct / (dt_ms / 1000.0))
    return rates


def smooth_30s(rates: list[float]) -> list[float]:
    """30s 滑窗 = 3 个相邻样本均值. < 3 样本原样返; 边界 (首/末) 保留原值."""
    if len(rates) < 3:
        return list(rates)
    out = list(rates)
    for i in range(1, len(rates) - 1):
        out[i] = (rates[i - 1] + rates[i] + rates[i + 1]) / 3.0
    return out


def group_rates_by_bucket(
    samples: list[BatterySample], rates: list[float],
) -> dict[str, list[float]]:
    """按 sample[i] 的桶 key 把 rate[i] 分组. samples / rates 同长度.

    rate <= 0 跳过 (充电 / 零速率).
    """
    groups: dict[str, list[float]] = defaultdict(list)
    for s, r in zip(samples, rates, strict=False):
        if r <= 0:
            continue
        key = bucket_key_for(s.wind_ms, s.height_m, s.percent)
        groups[key].append(r)
    return dict(groups)
