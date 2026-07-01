"use strict";

// rel_ms → "+Xs" / "+Xm[Ys]"
function fmtT(relMs) {
  const s = Math.round(relMs / 1000);
  if (s < 60) return "+" + s + "s";
  const m = Math.floor(s / 60), r = s % 60;
  return "+" + m + "m" + (r ? r + "s" : "");
}

function esc(v) {
  return String(v).replace(/[&<>"]/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

// 风向枚举 1..8 → 汉字 (index 0 占位); 对应 report.py _WIND_DIR_LABELS
const WIND_DIR_CN = ["", "正北", "东北", "东", "东南", "南", "西南", "西", "西北"];

// ── 索引页 ──
async function renderIndex() {
  const el = document.getElementById("list");
  let rows;
  try {
    const resp = await fetch("/api/reports");
    rows = await resp.json();
  } catch (e) {
    el.textContent = "加载失败: " + e;
    return;
  }
  if (!rows.length) { el.textContent = "(无报告)"; return; }
  let h = "<table><thead><tr><th>录制</th><th>机场</th><th>飞机</th>"
    + "<th>时长(s)</th><th>最低电量</th><th>阵风峰值</th><th>状态</th></tr></thead><tbody>";
  for (const r of rows) {
    if (!r.ok) {
      h += `<tr><td>${esc(r.recording)}</td><td colspan="5"></td>`
        + `<td>⚠️ ${esc(r.error || "损坏")}</td></tr>`;
      continue;
    }
    const dur = r.duration_ms != null ? (r.duration_ms / 1000).toFixed(0) : "-";
    const batt = r.min_battery_percent != null ? r.min_battery_percent + "%" : "-";
    const wind = r.peak_wind_gust_30s != null ? r.peak_wind_gust_30s.toFixed(1) + " m/s" : "-";
    h += `<tr><td><a href="/r/${encodeURIComponent(r.recording)}">${esc(r.recording)}</a></td>`
      + `<td>${esc(r.dock_sn || "-")}</td><td>${esc(r.drone_sn || "-")}</td>`
      + `<td>${dur}</td><td>${batt}</td><td>${wind}</td><td>✅</td></tr>`;
  }
  h += "</tbody></table>";
  el.innerHTML = h;
}

// ── 详情页 ──
async function renderDetail() {
  const name = decodeURIComponent(location.pathname.replace(/^\/r\//, ""));
  document.getElementById("title").textContent = "飞行复盘 — " + name;
  let rep;
  try {
    const resp = await fetch("/api/reports/" + encodeURIComponent(name));
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    rep = await resp.json();
  } catch (e) {
    document.getElementById("summary").textContent = "加载失败: " + e;
    return;
  }
  renderSummary(rep);
  const s = rep.battery_samples || [];
  drawBattery(s);
  drawSpeed(s);
  drawWindSpeed(s);
  drawWindDir(s);
}

function renderSummary(rep) {
  const m = rep.metrics || {};
  const dur = rep.duration_ms != null ? (rep.duration_ms / 1000).toFixed(0) + "s" : "-";
  const batt = m.min_battery_percent != null ? m.min_battery_percent + "%" : "-";
  const wind = m.peak_wind_gust_30s != null ? m.peak_wind_gust_30s.toFixed(1) + " m/s" : "-";
  document.getElementById("summary").innerHTML =
    `机场 SN: <b>${esc(rep.dock_sn || "-")}</b> · 飞机 SN: <b>${esc(rep.drone_sn || "-")}</b>`
    + ` · 时长: <b>${dur}</b> · 最低电量: <b>${batt}</b> · 阵风峰值: <b>${wind}</b>`;
}

function noData(id, title) {
  document.getElementById(id).innerHTML =
    `<div class="nodata">${title}: (无数据)</div>`;
}

function baseAxis() {
  return {
    tooltip: { trigger: "axis" },
    xAxis: { type: "value", name: "时间", axisLabel: { formatter: fmtT } },
    dataZoom: [{ type: "inside" }, { type: "slider" }],
  };
}

function drawBattery(samples) {
  const pts = samples.filter(s => s.percent != null).map(s => [s.rel_ms, s.percent]);
  if (!pts.length) return noData("chart-battery", "电池曲线");
  echarts.init(document.getElementById("chart-battery")).setOption({
    ...baseAxis(),
    title: { text: "电池曲线" },
    tooltip: { trigger: "axis", formatter: p => fmtT(p[0].value[0]) + " · " + p[0].value[1] + "%" },
    yAxis: { type: "value", name: "电量 (%)", min: 0, max: 100 },
    series: [{ name: "电量", type: "line", showSymbol: false, data: pts }],
  });
}

function drawSpeed(samples) {
  const hh = samples.filter(s => s.horizontal_speed_ms != null).map(s => [s.rel_ms, s.horizontal_speed_ms]);
  const vv = samples.filter(s => s.vertical_speed_ms != null).map(s => [s.rel_ms, s.vertical_speed_ms]);
  if (!hh.length && !vv.length) return noData("chart-speed", "速度曲线");
  echarts.init(document.getElementById("chart-speed")).setOption({
    ...baseAxis(),
    title: { text: "速度曲线 (垂直: 正=上升 负=下降)" },
    tooltip: {
      trigger: "axis",
      formatter: ps => fmtT(ps[0].value[0]) + "<br>"
        + ps.map(p => p.seriesName + ": " + p.value[1].toFixed(1) + " m/s").join("<br>"),
    },
    legend: { data: ["水平速度", "垂直速度"], top: 24 },
    yAxis: { type: "value", name: "m/s" },
    series: [
      { name: "水平速度", type: "line", showSymbol: false, data: hh },
      {
        name: "垂直速度", type: "line", showSymbol: false, data: vv,
        markLine: { silent: true, symbol: "none", data: [{ yAxis: 0 }] },
      },
    ],
  });
}

function drawWindSpeed(samples) {
  const pts = samples.filter(s => s.wind_ms != null).map(s => [s.rel_ms, s.wind_ms]);
  if (!pts.length) return noData("chart-windspeed", "风速曲线");
  echarts.init(document.getElementById("chart-windspeed")).setOption({
    ...baseAxis(),
    title: { text: "风速曲线" },
    tooltip: { trigger: "axis", formatter: p => fmtT(p[0].value[0]) + " · " + p[0].value[1].toFixed(1) + " m/s" },
    yAxis: { type: "value", name: "m/s", min: 0 },
    series: [{ name: "风速", type: "line", showSymbol: false, data: pts }],
  });
}

function drawWindDir(samples) {
  const pts = samples.filter(s => s.wind_direction != null).map(s => [s.rel_ms, s.wind_direction]);
  if (!pts.length) return noData("chart-winddir", "风向时序");
  echarts.init(document.getElementById("chart-winddir")).setOption({
    ...baseAxis(),
    title: { text: "风向时序" },
    tooltip: { trigger: "axis", formatter: p => fmtT(p[0].value[0]) + " · " + (WIND_DIR_CN[p[0].value[1]] || "?") },
    yAxis: {
      type: "value", min: 1, max: 8, interval: 1,
      axisLabel: { formatter: v => WIND_DIR_CN[v] || "" },
    },
    series: [{ name: "风向", type: "line", step: "end", showSymbol: false, data: pts }],
  });
}
