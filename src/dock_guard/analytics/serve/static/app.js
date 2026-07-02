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
    + "<th>时长(s)</th><th>最低电量</th><th>阵风峰值</th><th>状态</th><th>安全</th></tr></thead><tbody>";
  for (const r of rows) {
    if (!r.ok) {
      h += `<tr><td>${esc(r.recording)}</td><td colspan="6"></td>`
        + `<td>⚠️ ${esc(r.error || "损坏")}</td></tr>`;
      continue;
    }
    const dur = r.duration_ms != null ? (r.duration_ms / 1000).toFixed(0) : "-";
    const batt = r.min_battery_percent != null ? r.min_battery_percent + "%" : "-";
    const wind = r.peak_wind_gust_30s != null ? r.peak_wind_gust_30s.toFixed(1) + " m/s" : "-";
    h += `<tr><td><a href="/r/${encodeURIComponent(r.recording)}">${esc(r.recording)}</a></td>`
      + `<td>${esc(r.dock_sn || "-")}</td><td>${esc(r.drone_sn || "-")}</td>`
      + `<td>${dur}</td><td>${batt}</td><td>${wind}</td><td>✅</td>`
      + `<td><a href="/safety/${encodeURIComponent(r.recording)}">安全视图</a></td></tr>`;
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

// ── 安全视图 (同步多面板) ──
async function renderSafety() {
  const name = decodeURIComponent(location.pathname.replace(/^\/safety\//, ""));
  document.getElementById("title").textContent = "飞行安全视图 — " + name;
  let rep;
  try {
    const resp = await fetch("/api/reports/" + encodeURIComponent(name));
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    rep = await resp.json();
  } catch (e) {
    document.getElementById("summary").textContent = "加载失败: " + e;
    return;
  }
  const fs = rep.flight_samples || [];
  const dur = rep.duration_ms != null ? (rep.duration_ms / 1000).toFixed(0) + "s" : "-";
  document.getElementById("summary").innerHTML =
    `机场 SN: <b>${esc(rep.dock_sn || "-")}</b> · 飞机 SN: <b>${esc(rep.drone_sn || "-")}</b>`
    + ` · 时长: <b>${dur}</b> · 原频采样点: <b>${fs.length}</b>`;
  if (!fs.length) {
    document.getElementById("warn").textContent =
      "该报告无原频飞行采样 (flight_samples 为空; 用 --force 重跑升 v4)。";
    return;
  }
  const charts = [
    safLine("p-height", "高度", "m", safPick(fs, "height_m")),
    safSpeed("p-speed", fs),
    safAttitude("p-attitude", fs),
    safRtk("p-rtk", fs),
    safDrc("p-drc", fs),
  ].filter(Boolean);
  charts.forEach(c => { c.group = "safety"; });
  echarts.connect("safety");
}

function safPick(fs, key) {
  return fs.filter(s => s[key] != null).map(s => [s.rel_ms, s[key]]);
}

function safBase() {
  return {
    tooltip: { trigger: "axis" },
    xAxis: { type: "value", name: "时间", axisLabel: { formatter: fmtT } },
    dataZoom: [{ type: "inside" }, { type: "slider", height: 16, bottom: 4 }],
    grid: { left: 60, right: 30, top: 44, bottom: 46 },
  };
}

function safLine(id, title, unit, pts) {
  if (!pts.length) { noData(id, title); return null; }
  const c = echarts.init(document.getElementById(id));
  c.setOption({ ...safBase(), title: { text: title },
    yAxis: { type: "value", name: unit },
    series: [{ name: title, type: "line", showSymbol: false, connectNulls: false, data: pts }] });
  return c;
}

function safSpeed(id, fs) {
  const h = safPick(fs, "horizontal_speed_ms"), v = safPick(fs, "vertical_speed_ms");
  if (!h.length && !v.length) { noData(id, "速度"); return null; }
  const c = echarts.init(document.getElementById(id));
  c.setOption({ ...safBase(), title: { text: "速度 (垂直: 正=上升 负=下降)" },
    legend: { data: ["水平速度", "垂直速度"], top: 12, right: 20 },
    yAxis: { type: "value", name: "m/s" },
    series: [
      { name: "水平速度", type: "line", showSymbol: false, connectNulls: false, data: h },
      { name: "垂直速度", type: "line", showSymbol: false, connectNulls: false, data: v,
        markLine: { silent: true, symbol: "none", data: [{ yAxis: 0 }] } },
    ] });
  return c;
}

function safAttitude(id, fs) {
  const p = safPick(fs, "attitude_pitch"), r = safPick(fs, "attitude_roll"), hd = safPick(fs, "attitude_head");
  if (!p.length && !r.length && !hd.length) { noData(id, "姿态"); return null; }
  const c = echarts.init(document.getElementById(id));
  c.setOption({ ...safBase(), title: { text: "姿态" },
    legend: { data: ["俯仰", "横滚", "航向"], top: 12, right: 20 },
    yAxis: { type: "value", name: "度" },
    series: [
      { name: "俯仰", type: "line", showSymbol: false, connectNulls: false, data: p },
      { name: "横滚", type: "line", showSymbol: false, connectNulls: false, data: r },
      { name: "航向", type: "line", showSymbol: false, connectNulls: false, data: hd },
    ] });
  return c;
}

function safRtk(id, fs) {
  const g = safPick(fs, "gps_number"), rk = safPick(fs, "rtk_number");
  const fx = fs.filter(s => s.is_fixed != null).map(s => [s.rel_ms, s.is_fixed ? 1 : 0]);
  if (!g.length && !rk.length && !fx.length) { noData(id, "RTK/GNSS"); return null; }
  const c = echarts.init(document.getElementById(id));
  c.setOption({ ...safBase(), title: { text: "RTK/GNSS" },
    legend: { data: ["卫星数", "RTK星数", "Fixed"], top: 12, right: 20 },
    yAxis: [
      { type: "value", name: "颗" },
      { type: "value", name: "Fixed", min: 0, max: 1, interval: 1,
        axisLabel: { formatter: v => v === 1 ? "是" : (v === 0 ? "否" : "") } },
    ],
    series: [
      { name: "卫星数", type: "line", step: "end", showSymbol: false, connectNulls: false, data: g },
      { name: "RTK星数", type: "line", step: "end", showSymbol: false, connectNulls: false, data: rk },
      { name: "Fixed", type: "line", step: "end", yAxisIndex: 1, showSymbol: false,
        connectNulls: false, areaStyle: {}, data: fx },
    ] });
  return c;
}

function safDrc(id, fs) {
  const valid = fs.filter(s => s.drc_state != null);
  if (!valid.length) { noData(id, "DRC 状态"); return null; }
  const labels = [...new Set(valid.map(s => String(s.drc_state)))];
  const idx = Object.fromEntries(labels.map((l, i) => [l, i]));
  const pts = valid.map(s => [s.rel_ms, idx[String(s.drc_state)]]);
  const c = echarts.init(document.getElementById(id));
  c.setOption({ ...safBase(), title: { text: "DRC 状态" },
    tooltip: { trigger: "axis", formatter: p => fmtT(p[0].value[0]) + " · " + labels[p[0].value[1]] },
    yAxis: { type: "value", min: 0, max: Math.max(1, labels.length - 1), interval: 1,
             axisLabel: { formatter: v => labels[v] !== undefined ? labels[v] : "" } },
    series: [{ name: "DRC", type: "line", step: "end", showSymbol: false, connectNulls: false, data: pts }] });
  return c;
}
