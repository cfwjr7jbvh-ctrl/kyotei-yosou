"use strict";
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const state = { day: null, data: null, venue: "all", tab: "now", open: new Set(), latest: null };

// ---- パスワード(予想データは暗号化して置いてある) ----
let KEY = null;
const LS = "kyotei_key";
const b64d = (s) => Uint8Array.from(atob(s.trim()), (c) => c.charCodeAt(0));
const b64e = (u) => btoa(String.fromCharCode(...new Uint8Array(u)));

async function deriveKey(pw) {
  const salt = b64d(await (await fetch("data/salt.txt?t=" + Date.now())).text());
  const base = await crypto.subtle.importKey("raw", new TextEncoder().encode(pw), "PBKDF2", false, ["deriveKey"]);
  return crypto.subtle.deriveKey({ name: "PBKDF2", salt, iterations: 250000, hash: "SHA-256" },
    base, { name: "AES-GCM", length: 256 }, true, ["decrypt"]);
}
async function loadSavedKey() {
  try {
    const raw = localStorage.getItem(LS);
    if (raw) KEY = await crypto.subtle.importKey("raw", b64d(raw), "AES-GCM", true, ["decrypt"]);
  } catch (e) { KEY = null; }
}
class Locked extends Error { }

async function getJSON(path) {
  const r = await fetch(path + "?t=" + Date.now());
  if (!r.ok) throw new Error(path);
  let obj;
  try { obj = await r.json(); } catch (e) { throw new Error("not json: " + path); }
  if (!obj || obj.enc !== 1) return obj;
  if (!KEY) throw new Locked();
  try {
    const pt = await crypto.subtle.decrypt({ name: "AES-GCM", iv: b64d(obj.iv) }, KEY, b64d(obj.ct));
    return JSON.parse(new TextDecoder().decode(pt));
  } catch (e) { throw new Locked(); }
}

function showLogin(msg) {
  $("#login").hidden = false;
  $("#app").hidden = true;
  $("#login-msg").textContent = msg || "";
  $("#pw").focus();
}

// ---- 時刻(日本時間) ----
function jst() {
  const d = new Date(Date.now() + 9 * 3600e3);
  return { date: d.toISOString().slice(0, 10), min: d.getUTCHours() * 60 + d.getUTCMinutes() + d.getUTCSeconds() / 60 };
}
function minsLeft(r) {
  const t = jst();
  if (state.day !== t.date || !r.deadline) return null;
  const [h, m] = r.deadline.split(":").map(Number);
  return h * 60 + m - t.min;
}
function finished(r) {
  if (r.result) return true;
  const t = jst();
  if (state.day < t.date) return true;
  const left = minsLeft(r);
  return left != null && left < -1;
}
function leftText(left) {
  if (left == null) return "";
  if (left < 0) return "締切";
  if (left < 1) return "まもなく";
  if (left >= 120) return `${Math.floor(left / 60)}時間後`;
  return `あと${Math.floor(left)}分`;
}

// ---- 部品 ----
const pct1 = (p) => (p * 100).toFixed(1);
const tile = (lane) => `<span class="lane l${lane}" aria-label="${lane}号艇">${lane}</span>`;
function tri(combo, big = false) {
  return `<span class="tri${big ? " big" : ""}" aria-label="3連単 ${combo}">${combo.split("-").map((x) => tile(+x)).join("")}</span>`;
}
const MARKS = ["◎", "○", "▲", "△"];
function marksOf(r) {
  const order = [...r.boats].sort((a, b) => b.p_win - a.p_win).map((b) => b.lane);
  return Object.fromEntries(order.slice(0, 4).map((lane, i) => [lane, MARKS[i]]));
}

function boatsHTML(r) {
  const mk = marksOf(r);
  const maxP = Math.max(...r.boats.map((b) => b.p_win));
  return `<ol class="boats">` + r.boats.map((b) => {
    const meta = [
      b.class ? `<span class="cls">${esc(b.class)}</span>` : "",
      b.nat_win_rate != null ? `<span>勝率${Number(b.nat_win_rate).toFixed(2)}</span>` : "",
      b.motor_2rate != null ? `<span>機${Number(b.motor_2rate).toFixed(0)}%</span>` : "",
      b.exhibit_time != null ? `<span>展示${Number(b.exhibit_time).toFixed(2)}</span>` : "",
      b.ex_st != null ? `<span>ST ${b.ex_st < 0 ? "F" + Math.abs(b.ex_st).toFixed(2).slice(1) : Number(b.ex_st).toFixed(2).slice(1)}</span>` : "",
      b.course != null && b.course !== b.lane ? `<span class="move">${b.course}コース進入</span>` : "",
    ].join("");
    let delta = "";
    if (r.stage === "late" && b.p_win_early != null) {
      const d = (b.p_win - b.p_win_early) * 100;
      if (Math.abs(d) >= 1) delta = `<span class="delta ${d > 0 ? "up" : "down"}" title="展示前との差">${d > 0 ? "+" : "−"}${Math.abs(d).toFixed(1)}</span>`;
    }
    return `<li class="boat">${tile(b.lane)}<span class="shirushi" aria-label="${mk[b.lane] ? "印 " + mk[b.lane] : ""}">${mk[b.lane] || ""}</span>
      <div class="who"><b>${esc(b.name)}</b><div class="meta">${meta}</div></div>
      <div class="prob"><span class="pct">${pct1(b.p_win)}<small>%</small></span>${delta}</div>
      <div class="meter" aria-hidden="true"><i class="b${b.lane}" style="width:${Math.max(3, (b.p_win / maxP) * 100)}%"></i></div></li>`;
  }).join("") + `</ol>`;
}

// 本命の3連単(いちばん大きく)と、オッズの1番人気
function honmeiHTML(r) {
  if (!r.top || !r.top.length) return "";
  const t0 = r.top[0];
  const hit = r.result && r.result.tri_combo === t0.combo;
  const pop = r.market_top && r.market_top.length
    ? `<div class="pop">オッズの1番人気${tri(r.market_top[0].combo)}</div>` : "";
  return `<div class="honmei${hit ? " hit" : ""}">${tri(t0.combo, true)}
    <div class="lbl">本命${hit ? " 的中" : ""}<b>${pct1(t0.prob)}%</b>${t0.odds ? `${t0.odds}倍` : ""}</div>${pop}</div>`;
}

// 本命以外の候補
function combosHTML(r) {
  if (!r.top || r.top.length < 2) return "";
  const res = r.result && r.result.tri_combo;
  return `<div class="picks"><h3>ほかの候補(3連単)</h3><div class="combos">` + r.top.slice(1, 7).map((t) =>
    `<div class="combo${res === t.combo ? " hit" : ""}">${tri(t.combo)}
      <span class="p">${pct1(t.prob)}%${t.odds ? `<small>${t.odds}倍</small>` : ""}</span></div>`).join("") + `</div></div>`;
}

function evHTML(r) {
  if (!r.bets || !r.bets.length) return "";
  return `<div class="ev"><h3>期待値のある買い目</h3>` + r.bets.map((b) => `
    <div class="bet${b.hit ? " hit" : ""}">${tri(b.combo)}
      <div class="m">確率 <b>${pct1(b.prob)}%</b> オッズ <b>${b.odds}</b>倍${b.hit ? " 的中" : ""}</div>
      <div class="e${b.ev >= 1.2 ? " strong" : ""}">${Math.round(b.ev * 100)}<small>%</small><span>期待値</span></div></div>`).join("") + `</div>`;
}

function resultHTML(r) {
  if (!r.result) return "";
  return `<div class="result">結果 ${tri(r.result.tri_combo)}<span class="pay">${r.result.tri_pay.toLocaleString()}円</span></div>`;
}

function stageHTML(r) {
  return r.stage === "late"
    ? `<div class="stage late">展示を反映した直前予想(${esc(r.updated_at)})</div>`
    : `<div class="stage">朝の予想(展示前)</div>`;
}

// 見る順: 結果 → 本命 → 期待値の買い目 → 各艇 → ほかの候補
const bodyHTML = (r) => stageHTML(r) + resultHTML(r) + honmeiHTML(r) + evHTML(r) + boatsHTML(r) + combosHTML(r);

function clockHTML(r) {
  const left = minsLeft(r);
  return left == null ? "" : left < 1 ? `<span class="cd soon">まもなく</span>`
    : left >= 120 ? `<span class="cd">${Math.floor(left / 60)}<small>時間後</small></span>`
      : `<span class="cd${left < 10 ? " soon" : ""}">${Math.floor(left)}<small>分</small></span>`;
}

function heroHTML(r) {
  return `<section class="next" data-id="${r.race_id}">
    <div class="next-h"><div class="where"><span class="v">${esc(r.venue)}</span><span class="r">${r.rno}<small>R</small></span>
      <span class="type">${esc(r.race_type || "")}</span></div>
      <div class="clock"><span class="cdw" data-id="${r.race_id}">${clockHTML(r)}</span><span class="dl">締切 ${esc(r.deadline || "")}</span></div></div>
    ${bodyHTML(r)}</section>`;
}

function hitBadge(r) {
  if (!r.result) return "";
  const b = [];
  if (r.top && r.top[0] && r.top[0].combo === r.result.tri_combo) b.push("本命的中");
  if (r.bets && r.bets.some((x) => x.hit)) b.push("買い目的中");
  return b.map((x) => `<span class="badge">${x}</span>`).join("");
}

function subHTML(r) {
  const left = minsLeft(r);
  return `<small class="${left != null && left >= 0 && left < 10 ? "soon" : ""}">${r.result ? `${r.result.tri_pay.toLocaleString()}円` : leftText(left)}</small>`;
}

function rowHTML(r) {
  const right = r.result ? tri(r.result.tri_combo) : (r.top && r.top[0] ? tri(r.top[0].combo) : "");
  return `<details class="row" data-id="${r.race_id}"${state.open.has(r.race_id) ? " open" : ""}>
    <summary><span class="t">${esc(r.deadline || "")}<span class="subw" data-id="${r.race_id}">${subHTML(r)}</span></span>
      <span class="vr"><b>${esc(r.venue)}</b><span class="n">${r.rno}R</span>${r.stage === "late" ? `<span class="late" title="直前予想"></span>` : ""}</span>
      <span class="hits">${hitBadge(r)}</span>${right}</summary>
    <div class="body">${bodyHTML(r)}</div></details>`;
}

// ---- 画面 ----
function visibleRaces() {
  return state.data.races.filter((r) => state.venue === "all" || r.venue === state.venue);
}
const byTime = (a, b) => (a.deadline || "").localeCompare(b.deadline || "") || a.jcd - b.jcd;

function renderNow() {
  const box = $("#tab-now");
  const races = visibleRaces();
  if (!races.length) { box.innerHTML = `<div class="empty">この日の予想はまだありません。</div>`; return; }
  const up = races.filter((r) => !finished(r)).sort(byTime);
  const done = races.filter(finished).sort((a, b) => byTime(b, a));
  let html = "";
  if (up.length) {
    html += `<div class="now-grid"><div><h2 class="sect">次の締切</h2>${heroHTML(up[0])}</div><div>`;
    if (up.length > 1) html += `<h2 class="sect">このあと</h2><div class="list">${up.slice(1).map(rowHTML).join("")}</div>`;
    html += `</div></div>`;
  }
  if (done.length) html += `<h2 class="sect">終わったレース</h2><div class="list">${done.map(rowHTML).join("")}</div>`;
  box.innerHTML = html;
}

function renderBets() {
  const box = $("#tab-bets");
  const races = visibleRaces().filter((r) => r.bets && r.bets.length);
  const late = state.data.races.filter((r) => r.stage === "late").length;
  let html = `<p class="note">締切の約30分前から、展示とオッズを取り込んで5分ごとに更新します。確率×オッズ(期待値)が100%以上の組を出します。120%以上は赤で強調。直前予想 ${late} / ${state.data.races.length} レース</p>`;
  if (!races.length) {
    box.innerHTML = html + `<div class="empty">今のところ期待値の高い買い目はありません。締切が近づくと出てきます。</div>`;
    return;
  }
  const up = races.filter((r) => !finished(r)).sort(byTime);
  const done = races.filter(finished).sort((a, b) => byTime(b, a));
  if (up.length) html += `<div class="cards">${up.map(heroHTML).join("")}</div>`;
  if (done.length) html += `<h2 class="sect">終わったレース</h2><div class="list">${done.map(rowHTML).join("")}</div>`;
  box.innerHTML = html;
}

function stat(k, v, cls = "") { return `<div class="stat"><div class="k">${k}</div><div class="v ${cls}">${v}</div></div>`; }

async function renderTrack() {
  const box = $("#tab-track");
  let track = { days: [] }, rep = null;
  try { track = await getJSON("api/data/track.json"); } catch (e) { if (e instanceof Locked) return showLogin(""); }
  try { rep = await getJSON("api/data/report.json"); } catch (e) { if (e instanceof Locked) return showLogin(""); }
  const t = track.days.reduce((a, d) => {
    for (const k of ["races", "top1_hit", "bets", "bet_hits", "invest", "return"]) a[k] = (a[k] || 0) + d[k];
    return a;
  }, {});
  let html = `<div class="box"><h3>実際の成績</h3>`;
  if (t.races) {
    const roi = t.invest ? t.return / t.invest : 0;
    html += `<p>${track.days[0].date} 〜 ${track.days[track.days.length - 1].date}(${track.days.length}日、${t.races}レース)</p>
      <div class="stats">${stat("期待値買いの回収率", t.invest ? (roi * 100).toFixed(0) + "%" : "-", roi >= 1 ? "good" : "bad")}
      ${stat("収支(1点100円)", (t.return - t.invest >= 0 ? "+" : "") + (t.return - t.invest).toLocaleString() + "円")}
      ${stat("買い目の的中率", t.bets ? pct1(t.bet_hits / t.bets) + "%" : "-")}
      ${stat("本命3連単の的中率", pct1(t.top1_hit / t.races) + "%")}</div>`;
  } else html += `<p>予想を始めた翌朝から集計します。</p>`;
  html += `</div>`;
  if (rep) {
    const st = rep.stages.late || rep.stages.early;
    const names = { baseline_lane: "枠番だけ(基準)", gbdt_win: "勾配ブースティング(1着)", gbdt_place: "勾配ブースティング(3着内)",
      rank: "ランキング学習", pl_logit: "条件付きロジット", rating: "レーティング", ensemble: "アンサンブル(本番)" };
    const rows = Object.entries(st.metrics).map(([k, m]) => `<tr class="${k === "ensemble" ? "best" : ""}">
      <td>${names[k] || k}</td><td>${m.win_logloss.toFixed(3)}</td><td>${pct1(m.win_hit)}%</td>
      <td>${pct1(m.tri_hit_top1)}%</td><td>${pct1(m.tri_hit_top5)}%</td></tr>`).join("");
    html += `<div class="box"><h3>モデルの比較(過去データでの検証)</h3>
      <p>テスト期間 ${rep.period.test[0]} 〜 ${rep.period.test[1]}。誤差は小さいほど良い。</p>
      <div class="scroll"><table class="tbl"><thead><tr><th>モデル</th><th>誤差</th><th>1着</th><th>3連単本命</th><th>上位5点</th></tr></thead>
      <tbody>${rows}</tbody></table></div></div>`;
    if (rep.ev) {
      const e = rep.ev;
      const evRows = e.ev_blend.map((r, i) => `<tr><td>${Math.round(r.ev_min * 100)}%以上</td><td>${r.bets}</td>
        <td>${r.hit_rate != null ? pct1(r.hit_rate) + "%" : "-"}</td><td>${r.roi != null ? (r.roi * 100).toFixed(0) + "%" : "-"}</td>
        <td>${e.ev_model[i].roi != null ? (e.ev_model[i].roi * 100).toFixed(0) + "%" : "-"}</td></tr>`).join("");
      html += `<div class="box"><h3>期待値で買った場合の検証</h3>
        <p>${e.period[0]} 〜 ${e.period[1]} の ${e.races} レース。締切時オッズで1点100円、実際の払戻金で計算。</p>
        <div class="scroll"><table class="tbl"><thead><tr><th>期待値</th><th>点数</th><th>的中率</th><th>回収率</th><th>モデル単体</th></tr></thead>
        <tbody>${evRows}</tbody></table></div></div>`;
    }
    if (st.top_features) {
      html += `<div class="box"><h3>よく効いている要素</h3><p>${Object.keys(st.top_features).slice(0, 10).map(esc).join("、")}</p></div>`;
    }
  }
  box.innerHTML = html;
}

function renderVenues() {
  const vs = [...new Set(state.data.races.map((r) => r.venue))];
  if (state.venue !== "all" && !vs.includes(state.venue)) state.venue = "all";
  $("#venues").innerHTML = ["all", ...vs].map((v) =>
    `<button data-v="${esc(v)}" aria-pressed="${state.venue === v}">${v === "all" ? "すべて" : esc(v)}</button>`).join("");
}

function renderHeader() {
  const d = state.data;
  const today = state.day === jst().date;
  const late = d.races.some((r) => r.stage === "late");
  $("#updated").innerHTML = d.races.length
    ? (today && late ? `<span class="dot"></span>` : "") + `${d.updated_at ? esc(d.updated_at) + " 更新" : esc(state.day)}`
    : "予想の準備中";
}

function render() {
  state.doneCount = state.data.races.filter(finished).length;
  renderHeader();
  renderVenues();
  if (state.tab === "now") renderNow();
  if (state.tab === "bets") renderBets();
  if (state.tab === "track") renderTrack();
}

async function loadDay(day) {
  state.day = day;
  try {
    state.data = await getJSON(`api/data/days/${day}.json`);
  } catch (e) {
    if (e instanceof Locked) { showLogin(KEY ? "パスワードが変わりました。もう一度入力してください" : ""); return false; }
    state.data = { races: [] };
  }
  $("#login").hidden = true;
  $("#app").hidden = false;
  render();
  return true;
}

// 締切までの残り時間だけ書き換える(締切を過ぎたレースが出たら並べ直す)
function tick() {
  if (!state.data || state.day !== jst().date || state.tab === "track") return;
  const done = state.data.races.filter(finished).length;
  if (done !== state.doneCount) { state.doneCount = done; render(); return; }
  const byId = Object.fromEntries(state.data.races.map((r) => [r.race_id, r]));
  $$(".cdw").forEach((el) => { const r = byId[el.dataset.id]; if (r) el.innerHTML = clockHTML(r); });
  $$(".subw").forEach((el) => { const r = byId[el.dataset.id]; if (r) el.innerHTML = subHTML(r); });
}

async function init() {
  await loadSavedKey();
  $("#login-form").onsubmit = async (e) => {
    e.preventDefault();
    const btn = $("#login-form button");
    btn.disabled = true;
    $("#login-msg").textContent = "確認中…";
    KEY = await deriveKey($("#pw").value);
    let ok = true;
    try { await getJSON("api/data/check.json"); } catch (err) { ok = !(err instanceof Locked); }
    if (ok && state.day) ok = await loadDay(state.day);
    if (ok) { $("#login").hidden = true; $("#app").hidden = false; $("#login-msg").textContent = ""; }
    btn.disabled = false;
    if (ok) {
      if ($("#remember").checked) localStorage.setItem(LS, b64e(await crypto.subtle.exportKey("raw", KEY)));
      $("#pw").value = "";
    } else { KEY = null; $("#login-msg").textContent = "パスワードが違います"; }
  };
  $("#logout").onclick = () => { localStorage.removeItem(LS); KEY = null; showLogin(""); };
  let idx = { days: [] };
  try { idx = await getJSON("api/data/index.json"); } catch (e) { }
  // 今日の予想が一覧より先にできている(直前予想のループが先に作った)場合も今日を出す
  const today = jst().date;
  if (!idx.days.includes(today)) {
    try { await getJSON(`api/data/days/${today}.json`); idx.days.push(today); idx.latest = today; } catch (e) { }
  }
  state.latest = idx.latest;
  const sel = $("#day");
  sel.innerHTML = idx.days.slice().reverse().map((d) => `<option value="${d}">${+d.slice(5, 7)}/${+d.slice(8)}</option>`).join("");
  sel.onchange = () => { state.open.clear(); loadDay(sel.value); };
  $$(".tabs button").forEach((b) => b.onclick = () => {
    state.tab = b.dataset.tab;
    $$(".tabs button").forEach((x) => x.setAttribute("aria-selected", x === b));
    $$(".panel").forEach((p) => p.hidden = p.id !== "tab-" + state.tab);
    $("#venues").hidden = state.tab === "track";
    render();
    window.scrollTo({ top: 0 });
  });
  $("#venues").onclick = (e) => {
    const v = e.target.closest("button");
    if (v) { state.venue = v.dataset.v; render(); }
  };
  // 開いた行は、更新しても開いたままにする
  document.addEventListener("toggle", (e) => {
    const d = e.target;
    if (d.matches && d.matches("details.row")) d.open ? state.open.add(d.dataset.id) : state.open.delete(d.dataset.id);
  }, true);
  state.day = idx.latest;
  try { await getJSON("api/data/check.json"); } catch (e) { if (e instanceof Locked) return showLogin(""); }
  if (idx.latest) await loadDay(idx.latest);
  else { $("#updated").textContent = "予想の準備中"; $("#tab-now").innerHTML = `<div class="empty">最初の予想は、過去データの学習が終わりしだいここに出ます。</div>`; }
  setInterval(tick, 30 * 1000);
  setInterval(() => { if (state.day === state.latest) loadDay(state.day); }, 2 * 60 * 1000);
}
init();
