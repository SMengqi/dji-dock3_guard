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
  const hsi = rep.hsi_samples || [];
  const stick = rep.stick_samples || [];
  const link = rep.link_samples || [];
  const dur = rep.duration_ms != null ? (rep.duration_ms / 1000).toFixed(0) + "s" : "-";
  document.getElementById("summary").innerHTML =
    `机场 SN: <b>${esc(rep.dock_sn || "-")}</b> · 飞机 SN: <b>${esc(rep.drone_sn || "-")}</b>`
    + ` · 时长: <b>${dur}</b> · 原频采样点: <b>${fs.length}</b>`;
  if (!fs.length) {
    document.getElementById("warn").textContent =
      "该报告无原频飞行采样 (flight_samples 为空; 升 v7)。";
    return;
  }
  const charts = [
    safLine("p-height", "高度", "m", safPick(fs, "height_m")),
    safDownDist("p-downdist", hsi),
    safSpeed("p-speed", fs),
    safAttitude("p-attitude", fs),
    safStick("p-stick", stick),
    safRtk("p-rtk", fs),
    safDrc("p-drc", fs),
    safDownState("p-downstate", hsi),
    safAround("p-around", hsi),
    safDrift("p-drift", fs),
    safLink("p-link", link),
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

function safStick(id, stick) {
  // 归一化: (v-1024)/660 -> [-1,+1], 夹住溢出; 1024=回中.
  const norm = key => stick
    .filter(s => s[key] != null)
    .map(s => [s.rel_ms, Math.max(-1, Math.min(1, (s[key] - 1024) / 660))]);
  const rl = norm("roll"), pt = norm("pitch"), yw = norm("yaw"), th = norm("throttle");
  if (!rl.length && !pt.length && !yw.length && !th.length) { noData(id, "控制输入"); return null; }
  const c = echarts.init(document.getElementById(id));
  c.setOption({ ...safBase(), title: { text: "控制输入 (归一化 -1~+1, 0=回中)" },
    legend: { data: ["横移", "前后", "转向", "升降"], top: 12, right: 20 },
    yAxis: { type: "value", name: "杆量", min: -1, max: 1 },
    series: [
      { name: "横移", type: "line", step: "end", showSymbol: false, connectNulls: true, data: rl,
        markLine: { silent: true, symbol: "none", data: [{ yAxis: 0 }] } },
      { name: "前后", type: "line", step: "end", showSymbol: false, connectNulls: true, data: pt },
      { name: "转向", type: "line", step: "end", showSymbol: false, connectNulls: true, data: yw },
      { name: "升降", type: "line", step: "end", showSymbol: false, connectNulls: true, data: th },
    ] });
  return c;
}

function safRtk(id, fs) {
  const g = safPick(fs, "gps_number"), rk = safPick(fs, "rtk_number");
  const fx = fs.filter(s => s.is_fixed != null).map(s => [s.rel_ms, s.is_fixed ? 1 : 0]);
  if (!g.length && !rk.length && !fx.length) { noData(id, "RTK/GNSS"); return null; }
  const c = echarts.init(document.getElementById(id));
  c.setOption({ ...safBase(), title: { text: "RTK/GNSS" },
    legend: { data: ["卫星数", "RTK星数", "固定解"], top: 12, right: 20 },
    yAxis: [
      { type: "value", name: "颗" },
      { type: "value", name: "固定解", min: 0, max: 1, interval: 1,
        axisLabel: { formatter: v => v === 1 ? "是" : (v === 0 ? "否" : "") } },
    ],
    series: [
      { name: "卫星数", type: "line", step: "end", showSymbol: false, connectNulls: false, data: g },
      { name: "RTK星数", type: "line", step: "end", showSymbol: false, connectNulls: false, data: rk },
      { name: "固定解", type: "line", step: "end", yAxisIndex: 1, showSymbol: false,
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
    tooltip: { trigger: "axis", formatter: p => fmtT(p[0].value[0]) + " · " + esc(labels[p[0].value[1]]) },
    yAxis: { type: "value", min: 0, max: Math.max(1, labels.length - 1), interval: 1,
             axisLabel: { formatter: v => labels[v] !== undefined ? labels[v] : "" } },
    series: [{ name: "DRC", type: "line", step: "end", showSymbol: false, connectNulls: false, data: pts }] });
  return c;
}

const _HSI_NA = 60000;  // down_distance >= 此值判无效

function safDownDist(id, hsi) {
  const raw = [], diff = [];
  hsi.forEach(s => {
    if (s.down_distance_mm == null || s.down_distance_mm >= _HSI_NA) return;
    const dm = s.down_distance_mm / 1000;
    raw.push([s.rel_ms, dm]);
    if (s.elevation_m != null) diff.push([s.rel_ms, dm - s.elevation_m]);
  });
  if (!raw.length && !diff.length) { noData(id, "下视距离"); return null; }
  const c = echarts.init(document.getElementById(id));
  c.setOption({ ...safBase(), title: { text: "下视距离 vs 相对高度" },
    legend: { data: ["下视距离", "差值(下视−相对高度)"], top: 12, right: 20 },
    yAxis: { type: "value", name: "m" },
    series: [
      { name: "下视距离", type: "line", showSymbol: false, connectNulls: false, data: raw },
      { name: "差值(下视−相对高度)", type: "line", showSymbol: false, connectNulls: false, data: diff },
    ] });
  return c;
}

function safDownState(id, hsi) {
  const work = hsi.filter(s => s.down_work != null).map(s => [s.rel_ms, s.down_work ? 1 : 0]);
  const na = hsi.map(s => [s.rel_ms, (s.down_distance_mm == null || s.down_distance_mm >= _HSI_NA) ? 1 : 0]);
  if (!work.length && !na.length) { noData(id, "下视状态"); return null; }
  const c = echarts.init(document.getElementById(id));
  c.setOption({ ...safBase(), title: { text: "下视工作 / 失效状态" },
    legend: { data: ["下视工作", "下视失效(无效距离)"], top: 12, right: 20 },
    yAxis: { type: "value", min: 0, max: 1, interval: 1,
             axisLabel: { formatter: v => v === 1 ? "是" : "否" } },
    series: [
      { name: "下视工作", type: "line", step: "end", showSymbol: false, connectNulls: false, data: work },
      { name: "下视失效(无效距离)", type: "line", step: "end", showSymbol: false,
        connectNulls: false, areaStyle: {}, data: na },
    ] });
  return c;
}

function safAround(id, hsi) {
  const up = hsi.filter(s => s.up_distance_mm != null && s.up_distance_mm < _HSI_NA)
    .map(s => [s.rel_ms, s.up_distance_mm / 1000]);
  const around = hsi.filter(s => Array.isArray(s.around_distances_mm) && s.around_distances_mm.length)
    .map(s => [s.rel_ms, Math.min(...s.around_distances_mm) / 1000]);
  if (!up.length && !around.length) { noData(id, "上/周向距离"); return null; }
  const c = echarts.init(document.getElementById(id));
  c.setOption({ ...safBase(), title: { text: "上视 / 周向最近距离" },
    legend: { data: ["上视距离", "周向最近"], top: 12, right: 20 },
    yAxis: { type: "value", name: "m", min: 0 },
    series: [
      { name: "上视距离", type: "line", showSymbol: false, connectNulls: false, data: up },
      { name: "周向最近", type: "line", showSymbol: false, connectNulls: false, data: around },
    ] });
  return c;
}

function safDrift(id, fs) {
  // 相对起点东/北位移(米). 原点 = 第一个 lat/lon 双非空点.
  const R = 111320;
  let lat0 = null, lon0 = null;
  for (const s of fs) {
    if (s.latitude != null && s.longitude != null) { lat0 = s.latitude; lon0 = s.longitude; break; }
  }
  if (lat0 == null) { noData(id, "水平漂移"); return null; }
  const k = Math.cos(lat0 * Math.PI / 180);
  const east = [], north = [];
  for (const s of fs) {
    if (s.latitude == null || s.longitude == null) continue;
    east.push([s.rel_ms, (s.longitude - lon0) * R * k]);
    north.push([s.rel_ms, (s.latitude - lat0) * R]);
  }
  const c = echarts.init(document.getElementById(id));
  c.setOption({ ...safBase(), title: { text: "水平漂移 (相对起点 东/北 位移)" },
    legend: { data: ["东向", "北向"], top: 12, right: 20 },
    yAxis: { type: "value", name: "米" },
    series: [
      { name: "东向", type: "line", showSymbol: false, connectNulls: false, data: east },
      { name: "北向", type: "line", showSymbol: false, connectNulls: false, data: north },
    ] });
  return c;
}

function safLink(id, link) {
  const sdr = link.filter(s => s.sdr_quality != null).map(s => [s.rel_ms, s.sdr_quality]);
  const fg = link.filter(s => s.fourg_quality != null).map(s => [s.rel_ms, s.fourg_quality]);
  if (!sdr.length && !fg.length) { noData(id, "链路质量"); return null; }
  const c = echarts.init(document.getElementById(id));
  c.setOption({ ...safBase(), title: { text: "链路质量 (SDR/4G, 0-5)" },
    legend: { data: ["SDR质量", "4G质量"], top: 12, right: 20 },
    yAxis: { type: "value", name: "质量", min: 0, max: 5 },
    series: [
      { name: "SDR质量", type: "line", step: "end", showSymbol: false, connectNulls: false, data: sdr },
      { name: "4G质量", type: "line", step: "end", showSymbol: false, connectNulls: false, data: fg },
    ] });
  return c;
}

// ── 窗口缩放自适应: 重绘所有 ECharts 面板 (详情 .chart / 安全 .panel), 轻量防抖 ──
let _resizeTimer = null;
window.addEventListener("resize", function () {
  clearTimeout(_resizeTimer);
  _resizeTimer = setTimeout(function () {
    document.querySelectorAll(".chart, .panel").forEach(function (el) {
      const inst = echarts.getInstanceByDom(el);
      if (inst) inst.resize();
    });
  }, 150);
});
