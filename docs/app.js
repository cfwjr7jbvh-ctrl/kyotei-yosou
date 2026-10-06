"use strict";
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const state = { day: null, data: null, venue: "all", tab: "now", open: new Set(), latest: null, anSeen: new Set(), anSel: {} };

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

// ---- 選手の特性(目立つものを最大3つ) ----
// ST の表示(.12、フライングは F.01)
const fmtST = (v) => (v < 0 ? "F" : "") + Math.abs(v).toFixed(2).slice(1);
function courseOf(r, b) { return r.stage === "late" && b.course ? b.course : b.lane; }
function traitChips(r, b) {
  const t = b.traits || {};
  const c = courseOf(r, b);
  const chips = [];
  const add = (text, tone = "") => chips.push(`<span class="chip ${tone}">${text}</span>`);
  if (c === 1 && t.nige != null && (t.nige >= 0.63 || t.nige < 0.39)) add(`逃げ率${Math.round(t.nige * 100)}%`, t.nige >= 0.63 ? "plus" : "minus");
  if (c > 1) {
    const types = [["まくり", t.makuri, 0.048], ["差し", t.sashi, 0.042], ["まくり差し", t.mz, 0.040]]
      .filter(([, v, th]) => v != null && v >= th).sort((a, b) => b[1] / b[2] - a[1] / a[2]);
    if (types.length) add(`${types[0][0]}型`, "plus");
  }
  const st = t.st_pred != null && r.stage === "late" ? t.st_pred : t.st;
  if (st != null && st <= 0.144) add(`ST速い ${fmtST(st)}`, "plus");
  else if (st != null && st >= 0.19) add(`ST遅め ${fmtST(st)}`, "minus");
  else if (t.st_sd != null && t.st_sd <= 0.056) add("ST安定", "plus");
  if (t.series != null && t.series >= 0.31) add("今節の足◎", "plus");
  else if (t.motor != null && t.motor >= 0.165) add("モーター◎", "plus");
  else if (t.series != null && t.series <= -0.27) add("今節の足△", "minus");
  else if (t.motor != null && t.motor <= -0.15) add("モーター△", "minus");
  if (c > 1 && r.stage !== "late" && t.front != null && t.front >= 0.054) add("前づけあり");
  if (t.f != null && t.f >= 1) add("F持ち", "minus");
  if (t.growth != null && t.growth >= 0.3) add("上り調子", "plus");
  return chips.length ? `<div class="chips">${chips.slice(0, 3).join("")}</div>` : "";
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
      <div class="who"><button type="button" class="rname" data-rid="${b.racer_id || ""}" data-race="${r.race_id}" data-lane="${b.lane}">${esc(b.name)}<span class="rn-i" aria-hidden="true">カード</span></button><div class="meta">${meta}</div>${traitChips(r, b)}</div>
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

const betRows = (list, label = "期待値") => list.map((b) => `
    <div class="bet${b.hit ? " hit" : ""}">${tri(b.combo)}
      <div class="m">確率 <b>${pct1(b.prob)}%</b> オッズ <b>${b.odds}</b>倍${b.hit ? " 的中" : ""}</div>
      <div class="e${b.ev >= 1.2 ? " strong" : ""}">${Math.round(b.ev * 100)}<small>%</small><span>${label}</span></div></div>`).join("");
function evHTML(r) {
  if (!r.bets || !r.bets.length) return "";
  return `<div class="ev"><h3>期待値のある買い目</h3>${betRows(r.bets)}</div>`;
}
// AIの狙い目(参考): モデルの確率×オッズが100%以上の組(期待値の高い順に3点まで)
function pickHTML(r) {
  if (!r.pick || !r.pick.length) return "";
  return `<div class="ev pick"><h3>AIの狙い目<em>参考</em></h3>
    <p class="cap">モデルの確率×オッズが100%以上の組(期待値の高い順に3点まで)。オッズと合わせた本当の期待値ではなく、過去の検証では回収率80%前後と100%に届いていません。実際の成績は成績タブで集計しています。</p>
    ${betRows(r.pick, "AIの見積もり")}</div>`;
}

// ---- 荒れ度 ----
// 1号艇が負ける確率で5段階(区切りは過去約1.7万レースの20/40/60/80%点)。万舟の確率より当たる(AUC 0.72 対 0.60)。
// 過去の実際: 1号艇が負けた割合 20% / 32% / 43% / 55% / 74%、3連単の払戻の中央値 1,490 / 2,030 / 2,620 / 3,160 / 3,505円
const ARASHI_CUTS = [0.28, 0.37, 0.48, 0.63];
const ARASHI_WORD = ["", "堅い", "やや堅い", "ふつう", "荒れ気味", "大荒れ注意"];
function arashiLevel(r) {
  const a = r.arashi;
  return a && a.in_lose != null ? 1 + ARASHI_CUTS.filter((c) => a.in_lose >= c).length : 0;
}
function arashiHTML(r) {
  const a = r.arashi;
  const lv = arashiLevel(r);
  if (!lv) return "";
  const dots = [1, 2, 3, 4, 5].map((i) => `<i${i <= lv ? ' class="on"' : ""}></i>`).join("");
  return `<div class="arashi lv${lv}"><span class="k">荒れ度</span><span class="dots" role="img" aria-label="5段階中${lv}">${dots}</span>
    <b class="w">${ARASHI_WORD[lv]}</b><span class="nums"><span>1号艇が負ける<b>${Math.round(a.in_lose * 100)}%</b></span>
    <span>万舟<b>${Math.round(a.manshu * 100)}%</b></span></span></div>`;
}

// ---- 展開予測 ----
const KIM = ["逃げ", "差し", "まくり", "まくり差し", "その他"];
function aiLine(r) {
  const tk = r.tenkai;
  if (!tk || !tk.kimarite) return "";
  const k = tk.kimarite;
  const inBoat = r.boats.find((b) => courseOf(r, b) === 1) || r.boats[0];
  const parts = [];
  if (k["逃げ"] >= 0.6) parts.push(`${inBoat.lane}号艇の逃げが本線`);
  else if (k["逃げ"] >= 0.45) parts.push(`${inBoat.lane}号艇の逃げが優勢${arashiLevel(r) >= 4 ? "、ただし波乱含み" : ""}`);
  else parts.push(`インが不安で混戦模様`);
  const atk = (tk.paths || []).find((p) => p.type !== "逃げ" && p.p >= 0.07);
  const sa = slitAlert(r);
  if (atk && sa && sa.short && atk.lane === sa.lane) parts.push(`${atk.lane}号艇の${atk.type}に注意(${sa.short})`);
  else {
    if (atk) parts.push(`${atk.lane}号艇の${atk.type}に注意`);
    if (sa) parts.push(sa.text);
  }
  if (r.stage === "late") {
    const up = r.boats.filter((b) => b.p_win_early != null).map((b) => [b, b.p_win - b.p_win_early]).sort((a, b) => b[1] - a[1])[0];
    if (up && up[1] >= 0.05) parts.push(`展示で${up[0].lane}号艇の評価が上昇`);
  } else {
    const fr = r.boats.find((b) => b.lane > 1 && b.traits && b.traits.front >= 0.076);
    if (fr) parts.push(`${fr.lane}号艇の前づけで進入が動くかも`);
  }
  return `<p class="ai">${parts.slice(0, 3).join("。")}。</p>`;
}

// スリットの目印(2026-10-04 の検証、直前予想・約15万レース):
//   攻め = 3コース以遠で、内の艇より予想STが0.03以上速い → 1着率が1.6〜2.5倍(まくり・まくり差しが中心)。0.05以上は「強攻め」
//   凹み = 両隣より0.04以上遅い → その艇の3着内率が13〜16ポイント下がり、外の艇の1着率が1.3〜1.7倍
//   どちらも AI の確率とオッズにはすでに織り込まれている(買い方の上積みにはならない)。見どころの表示用
const ATK_TH = 0.03, ATK_STRONG = 0.05, DENT_TH = 0.04;
function slitRows(r) {
  const rows = r.boats.map((b) => {
    const t = b.traits || {};
    const st = r.stage === "late" && t.st_pred != null ? t.st_pred : t.st;
    return { b, c: courseOf(r, b), st };
  }).filter((x) => x.st != null).sort((a, b) => a.c - b.c);
  rows.forEach((x, i) => {
    const inn = rows[i - 1] && rows[i - 1].st, out = rows[i + 1] && rows[i + 1].st;
    x.adv = inn != null ? inn - x.st : null;
    x.atk = x.adv != null && x.adv >= ATK_TH && x.c >= 3;
    x.dent = i > 0 && !x.atk && (inn == null || x.st - inn >= DENT_TH) && (out == null || x.st - out >= DENT_TH);
    x.outer = rows[i + 1] ? rows[i + 1].b : null;
  });
  return rows;
}
// AIのひと言に入れるスリットの注意(強攻めを優先、なければ凹み)
function slitAlert(r) {
  const rows = slitRows(r);
  if (rows.length < 4) return null;
  const a = rows.filter((x) => x.atk && x.adv >= ATK_STRONG).sort((p, q) => q.adv - p.adv)[0];
  if (a) return { lane: a.b.lane, text: `スリットで${a.b.lane}号艇が内より${fmtST(a.adv)}速い予想、まくり注意`, short: `スリットで内より${fmtST(a.adv)}速い予想` };
  const d = rows.find((x) => x.dent && x.outer);
  if (d) return { lane: d.outer.lane, text: `${d.b.lane}号艇のスリットが凹みそう、外の${d.outer.lane}号艇に展開` };
  return null;
}
function slitHTML(r) {
  const rows = slitRows(r);
  if (rows.length < 4) return "";
  const note = (x) => x.atk ? `<em class="atk${x.adv >= ATK_STRONG ? " strong" : ""}">${x.adv >= ATK_STRONG ? "強攻め" : "攻め"}</em>`
    : x.dent ? `<em class="dent">凹み</em>` : "";
  return `<div class="slit" aria-label="スリット予想(予想ST)">` + rows.map((x) => {
    const pos = Math.min(1, Math.max(0, (0.30 - x.st) / 0.27)) * 100;
    return `<div class="sl"><span class="sc">${x.c}</span><span class="track"><span class="mk" style="left:calc(${pos}% - 13px)">${tile(x.b.lane)}</span></span>
      <span class="sv">${fmtST(x.st)}${note(x)}</span></div>`;
  }).join("") + `</div>` + (rows.some((x) => x.atk || x.dent)
    ? `<p class="slitnote">攻め: 内の艇より0.03以上速い予想。過去約15万レースで1着率が1.6〜2.5倍(まくりが中心)。凹み: 両隣より0.04以上遅い予想。その艇の3着内率は13〜16ポイント下がり、外の艇の1着が増える。どちらもAIの確率には織り込み済み。</p>` : "");
}

function tenkaiHTML(r) {
  const tk = r.tenkai;
  if (!tk || !tk.kimarite) return "";
  const k = tk.kimarite;
  const seg = KIM.map((n, i) => k[n] > 0.005 ? `<i class="k${i}" style="flex:${k[n]}"></i>` : "").join("");
  const legend = KIM.filter((n) => k[n] >= 0.01).map((n) => `<span><i class="k${KIM.indexOf(n)}"></i>${n} <b>${Math.round(k[n] * 100)}%</b></span>`).join("");
  return `<div class="tenkai"><h3>展開予測</h3>
    <div class="kbar" aria-hidden="true">${seg}</div><div class="klegend">${legend}</div>
    ${animHTML(r)}
    ${scenarioHTML(r)}
    <h4>スリット予想<small>${r.stage === "late" ? "展示STから" : "平均STから"}・右ほど早い</small></h4>${slitHTML(r)}</div>`;
}

// 展開シナリオ: 勝ち筋ごとに「その艇が勝つなら2着・3着は誰か」
function scenarioHTML(r) {
  const sc = (r.tenkai && r.tenkai.scenarios) || [];
  if (!sc.length) return "";
  const row = (x) => {
    const how = x.type ? `${x.type}で勝つなら` : "勝つなら";
    const sec = x.second.map((b) => `${tile(b.lane)}<b>${Math.round(b.p * 100)}%</b>`).join("");
    const odds = x.best.odds ? `・${Number(x.best.odds).toFixed(1)}倍` : "";
    return `<div class="scn"><div class="scn-h">${tile(x.lane)}<span>${how}</span><span class="scn-p">1着 <b>${Math.round(x.p_win * 100)}%</b></span></div>
      <div class="scn-b"><span class="k">2着</span>${sec}</div>
      <div class="scn-b"><span class="k">本線</span>${tri(x.best.combo)}<span class="scn-m">この展開の中で ${Math.round(x.best.p_cond * 100)}%${odds}</span></div></div>`;
  };
  return `<h4>展開シナリオ<small>勝ち筋ごとの2着と本線</small></h4><div class="scns">${sc.map(row).join("")}</div>`;
}

// ---- 選手カード ----
// 公式の成績データ(2023-10〜)を自分たちで集計した特性(scripts/racer_cards.py → cards ブランチ)。
// レーダーチャートとタグの「上位X%」は同じ級別(A1 / A2 / B級)の中での位置。タグは根拠の数字と基準を必ず出す
const CARDS = { meta: null, buckets: {} };
async function loadCard(id) {
  if (!CARDS.meta) CARDS.meta = await getJSON("api/data/cards/meta.json");
  const b = id % (CARDS.meta.buckets || 50);
  if (!CARDS.buckets[b]) CARDS.buckets[b] = await getJSON(`api/data/cards/b${String(b).padStart(2, "0")}.json`);
  return CARDS.buckets[b].cards[String(id)] || null;
}
function radarSVG(vals, labels, W = 340, H = 236) {
  const c = W / 2, cy = H / 2, R = 74, n = labels.length;  // 横長の枠で、左右のラベルが切れないようにする
  const pt = (i, v) => { const a = -Math.PI / 2 + (2 * Math.PI * i) / n; return [c + R * v * Math.cos(a), cy + R * v * Math.sin(a)]; };
  const ring = (v) => labels.map((_, i) => pt(i, v).map((x) => x.toFixed(1)).join(",")).join(" ");
  const poly = labels.map((l, i) => pt(i, Math.max(0.03, (vals[l] ?? 0) / 100)).map((x) => x.toFixed(1)).join(",")).join(" ");
  const lab = labels.map((l, i) => {
    const [x, y] = pt(i, 1.16);
    const anchor = Math.abs(x - c) < 4 ? "middle" : x > c ? "start" : "end";
    return `<text x="${x.toFixed(1)}" y="${(y + 4).toFixed(1)}" text-anchor="${anchor}">${esc(l)}<tspan class="rv" dx="3">${vals[l] == null ? "-" : Math.round(vals[l])}</tspan></text>`;
  }).join("");
  return `<svg class="radar" viewBox="0 0 ${W} ${H}" role="img" aria-label="${labels.map((l) => `${l} ${vals[l] == null ? "-" : Math.round(vals[l])}`).join("、")}">
    ${[0.25, 0.5, 0.75, 1].map((v) => `<polygon class="rg" points="${ring(v)}"/>`).join("")}
    ${labels.map((_, i) => { const [x, y] = pt(i, 1); return `<line class="rg" x1="${c}" y1="${cy}" x2="${x.toFixed(1)}" y2="${y.toFixed(1)}"/>`; }).join("")}
    <polygon class="rd" points="${poly}"/>${lab}</svg>`;
}
const pctTop = (p) => p == null ? "" : `上位${Math.max(1, Math.round(100 - p))}%`;
const pp = (x) => x == null ? "-" : `${x >= 0 ? "+" : "−"}${Math.abs(Math.round(x * 100))}`;
function cardHTML(c, race, lane) {
  const m = CARDS.meta || {};
  const g = (m.groups || {})[c.grp] || c.grp;
  const rule = (t) => (m.rules || {})[t] || (t.endsWith("巧者") ? (m.rules || {})["(場名)巧者"] : t === "急成長中" ? (m.rules || {})["上り調子"] : "");
  const tags = c.tags.map((t) => `<li><span class="tg">${typeof emblem === "function" ? emblem(t.t, 22) : ""}${esc(t.t)}</span><span class="why">${esc(t.why)}</span>
    <details class="rule"><summary>基準</summary>${esc(rule(t.t))}</details></li>`).join("");
  const k = c.kim;
  const kimRow = (name, x, unit) => `<tr><th>${name}</th><td>${x.w}<small>勝</small> / ${x.n}<small>走</small></td><td>${unit}</td><td>${pctTop(x.grp)}</td></tr>`;
  const crs = c.courses.map((x) => `<tr><th>${x.c}</th><td>${x.n}</td><td>${x.win == null ? "-" : Math.round(x.win * 100) + "%"}</td>
    <td>${x.top3 == null ? "-" : Math.round(x.top3 * 100) + "%"}</td><td>${x.st == null ? "-" : fmtST(x.st)}</td></tr>`).join("");
  const ven = c.venues.length ? c.venues.map((v) => `<span class="vchip">${esc(v.name)}<b>${pp(v.res)}</b><small>${v.n}走</small></span>`).join("") : "<span class=\"muted\">データ不足</span>";
  const b = race && race.boats.find((x) => x.lane === lane);
  const t = (b && b.traits) || {};
  const word = (v, hi, lo) => v == null ? "-" : v >= hi ? "◎ 良い" : v <= lo ? "△ 弱め" : "○ ふつう";
  const sr = c.series;
  const gr = c.growth;
  return `<div class="cd-h">${lane ? tile(lane) : ""}<div><div class="cd-name">${esc(c.name)}</div>
      <div class="cd-sub">${esc(c.class || "")} ・ ${esc(c.branch || "")} ・ ${c.age ?? "-"}歳 ・ 登番${c.id}</div></div>
      <button type="button" class="cd-x" aria-label="閉じる">×</button></div>
    <div class="cd-top">${radarSVG(c.radar, m.radar || Object.keys(c.radar))}
      <div class="cd-kv"><div><span>1着率</span><b>${Math.round(c.win * 100)}%</b></div><div><span>3着内率</span><b>${Math.round(c.top3 * 100)}%</b></div>
        <div><span>勝率(点)</span><b>${c.pts?.toFixed(2) ?? "-"}</b></div><div><span>走数</span><b>${c.n}</b></div>
        <p class="cd-note">チャートは${esc(g)}の中での位置(100がトップ)。安定感はコースの有利不利を差し引いた3着内率</p></div></div>
    ${c.fafter ? `<p class="cd-f"><b>F後${c.fafter.since}走目</b>(最後のフライング ${esc(c.fafter.date)})。全選手の傾向では、この時期はスタートが平均${fmtST(c.fafter.st).replace(/^\./, "+.")}秒ほど遅くなり、3着内率は${Math.round(c.fafter.top3 * 100)}ポイント。40走ほどで戻る(どれだけ控えるかは毎回ちがう)</p>` : ""}
    ${tags ? `<h4>ひと言タグ</h4><ul class="cd-tags">${tags}</ul>` : `<p class="muted">目立つタグはありません(どの項目も同じ級別の中で平均的)</p>`}
    <h4>スタート</h4><table class="cd-t"><tr><th>平均ST</th><td>${c.st.avg == null ? "-" : fmtST(c.st.avg)}</td><td>${pctTop(c.st.grp)}</td></tr>
      <tr><th>展示とのずれ</th><td>平均 ${c.ex.mae == null ? "-" : c.ex.mae.toFixed(3)}秒</td><td>${c.ex.grp == null ? "" : pctTop(c.ex.grp) + "の小ささ"}</td></tr>
      <tr><th>展示→本番</th><td>${c.ex.delta == null ? "-" : (c.ex.delta >= 0 ? "+" : "−") + Math.abs(c.ex.delta).toFixed(2) + "秒"}</td><td><small>全選手の中央値 ${c.ex.pop_delta == null ? "-" : "+" + c.ex.pop_delta.toFixed(2)}秒</small></td></tr>
      <tr><th>フライング</th><td>${c.st.f}回</td><td><small>集計期間中</small></td></tr></table>
    <h4>決まり手</h4><table class="cd-t">${kimRow("逃げ(1コース)", k.nige, `逃げ率 ${Math.round(k.nige.w / Math.max(1, k.nige.n) * 100)}%`)}
      ${kimRow("差し", k.sashi, "2コース以遠")}${kimRow("まくり", k.makuri, "2コース以遠")}${kimRow("まくり差し", k.mz, "3コース以遠")}</table>
    <h4>コース別</h4><table class="cd-t cd-c"><tr><th>コース</th><th>走数</th><th>1着</th><th>3着内</th><th>平均ST</th></tr>${crs}</table>
    <h4>場ごとの成績<small>3着内率の普段との差。参考程度(時期で入れ替わりやすい)</small></h4><div class="vchips">${ven}</div>
    <h4>こんなとき</h4><table class="cd-t">
      <tr><th>前づけ</th><td>${c.front.rate == null ? "-" : Math.round(c.front.rate * 100) + "%"}</td><td><small>2枠以上で枠より内へ(${c.front.n}走)</small></td></tr>
      <tr><th>荒れ水面</th><td>${pp(c.rough.res)}</td><td><small>波5cm・風5m以上(${c.rough.n}走)</small></td></tr>
      <tr><th>勝負駆け</th><td>${pp(c.kake.res)}</td><td><small>予選最終日(${c.kake.n}走)</small></td></tr>
      <tr><th>大一番</th><td>${pp(c.big.res)}</td><td><small>準優・優勝戦(${c.big.n}走、出場選手の平均 ${pp(c.big.pop)})</small></td></tr>
      <tr><th>展示が下位</th><td>${pp(c.exlate.res)}</td><td><small>展示タイム4位以下(${c.exlate.n}走、全選手の平均 ${pp(c.exlate.pop)})</small></td></tr></table>
    <p class="cd-note">「こんなとき」の数字は、3着内率が本人の普段と比べて何ポイント上下するか(回数が少ないほど普段の値に寄せて計算)。前づけ・展示が下位は時期を変えても出やすい数字、荒れ水面・勝負駆け・大一番・場は時期で入れ替わりやすいので参考程度に</p>
    <h4>最近の調子と今節</h4><table class="cd-t">
      <tr><th>勝率</th><td>${gr.prev ?? "-"} → <b>${gr.pts90 ?? "-"}</b></td><td><small>前の1年 → 直近90日(${gr.n90}走)</small></td></tr>
      ${gr.index != null ? `<tr><th>成長指数</th><td><b>${gr.index >= 0 ? "+" : "−"}${Math.abs(gr.index).toFixed(2)}</b></td><td><small>この先3か月の勝率の伸びの見込み(伸びの4割ほどが残る傾向から)</small></td></tr>` : ""}
      ${b ? `<tr><th>今節の足</th><td>${word(t.series, 0.31, -0.27)}</td><td><small>このレースの時点、同じモーターでの今節の着順から</small></td></tr>
      <tr><th>モーター</th><td>${word(t.motor, 0.165, -0.15)}</td><td><small>${b.motor_2rate != null ? `2連率${Math.round(b.motor_2rate)}%・` : ""}乗り手の腕を差し引いた力</small></td></tr>` : ""}
      ${sr ? `<tr><th>直近の節</th><td>${esc(sr.venue)}</td><td><small>${esc(sr.from.slice(5).replace("-", "/"))}〜${esc(sr.to.slice(5).replace("-", "/"))} 着順 ${sr.finishes.map(esc).join(" ")}</small></td></tr>` : ""}</table>
    <p class="cd-foot">集計期間 ${esc(c.period[0])}〜${esc(c.asof)}。公式の成績データを自分たちで集計した数字です。</p>`;
}
async function openCard(btn) {
  const id = Number(btn.dataset.rid);
  if (!id) return;
  let dlg = $("#card-dlg");
  if (!dlg) {
    dlg = document.createElement("dialog");
    dlg.id = "card-dlg";
    dlg.className = "card-dlg";
    document.body.appendChild(dlg);
    dlg.addEventListener("click", (e) => { if (e.target === dlg || e.target.closest(".cd-x")) dlg.close(); });
  }
  dlg.innerHTML = `<div class="cd-body"><p class="muted">読み込み中…</p></div>`;
  if (!dlg.open) dlg.showModal();
  const race = state.data && state.data.races.find((x) => x.race_id === btn.dataset.race);
  try {
    const c = await loadCard(id);
    dlg.innerHTML = `<div class="cd-body">${c ? cardHTML(c, race, Number(btn.dataset.lane)) : `<button type="button" class="cd-x" aria-label="閉じる">×</button><p>この選手のカードはまだありません(集計期間の出走が少ない)。</p>`}</div>`;
  } catch (e) {
    dlg.innerHTML = `<div class="cd-body"><button type="button" class="cd-x" aria-label="閉じる">×</button><p>選手カードを読み込めませんでした(毎朝の更新のあとに作られます)。</p></div>`;
  }
}
document.addEventListener("click", (e) => {
  const b = e.target.closest && e.target.closest(".rname");
  if (b) { e.preventDefault(); openCard(b); }
});

// ---- 1マークの展開アニメ ----
// 勝ち筋(展開シナリオ)ごとに「スタート → スリット → 1マークの回り方 → 着順」を動かして見せる。
// 座標はメートル(本物の寸法): 艇は長さ3m、コースの間隔5m、スタートラインから1マークまで100m。
// スロー勢(1〜3コース)は近くから加速、ダッシュ勢(4〜6コース)は遠くから全速で来る。スリットは予想ST(直前は展示ST込み)の順に
// 1艇ずつ、スローモーションで切る(0.01秒の差=本物では18cm。拡大して見せる)。カメラは先頭集団を追う。
// 1マークの回り方は決まり手ごとの典型の形で、実際の航跡のデータではない。着順はそのシナリオの本線。
const AN = { markX: 100, markY: -6, laneY: (c) => (c - 1) * 5, hold: 1.6,
  cam: { start: 56, turn: 78, fin: 120 } };
const anReduce = () => window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
const BOAT = "M 1.6 0 L 0.5 -0.68 L -1.15 -0.62 L -1.45 0 L -1.15 0.62 L 0.5 0.68 Z";  // 舳先が +x
function animHTML(r) {
  const sc = (r.tenkai && r.tenkai.scenarios) || [];
  if (!sc.length || !r.boats || r.boats.length < 6) return "";
  const chips = sc.map((x, i) => `<button type="button" class="an-chip" data-i="${i}" aria-pressed="${i === 0}">${tile(x.lane)}<span>${esc(x.type || "1着")}</span><b>${Math.round(x.p_win * 100)}%</b></button>`).join("");
  return `<div class="anim" data-id="${r.race_id}">
    <h4>1マークの展開<small>勝ち筋を選ぶと動きます</small></h4>
    <div class="an-chips">${chips}</div>
    <div class="an-stage"><svg viewBox="-30 -20 56 36" role="img" aria-label="スタートから1マークまでの展開のアニメーション">
      <rect class="an-water" x="-400" y="-300" width="900" height="700"/>
      <line class="an-slit" x1="0" y1="-4" x2="0" y2="29"/>
      <text class="an-lbl" x="0.8" y="-2.4" font-size="2">スタートライン</text>
      <circle class="an-mark" cx="${AN.markX}" cy="${AN.markY}" r="0.9"/><text class="an-lbl" x="${AN.markX + 1.6}" y="${AN.markY - 1.2}" font-size="2">1マーク</text>
      <g class="an-trails"></g><g class="an-boats"></g></svg>
      <div class="an-phase"></div>
      <button type="button" class="an-re" aria-label="もう一度再生">↻ もう一度</button></div>
    <p class="an-cap"></p>
    <p class="an-note">本物の寸法(艇3m・1マークまで100m)で描いています。スリットは予想STの順に1艇ずつ、スローで切ります(0.01秒=18cm)。1マークの回り方は決まり手ごとの典型の形、着順はその勝ち筋の本線。</p></div>`;
}

const qb = (a, c, b, n = 24) => Array.from({ length: n + 1 }, (_, k) => {
  const t = k / n, u = 1 - t;
  return [u * u * a[0] + 2 * u * t * c[0] + t * t * b[0], u * u * a[1] + 2 * u * t * c[1] + t * t * b[1]];
});
function anPath(segs) {
  const pts = [], marks = [];
  for (const s of segs) { pts.push(...(pts.length ? s.slice(1) : s)); marks.push(pts.length - 1); }
  const cum = [0];
  for (let i = 1; i < pts.length; i++) cum.push(cum[i - 1] + Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]));
  return { pts, cum, at: marks.map((i) => cum[i]) };  // at = 各区切り(スリット・ターン入口・出口・ゴール)までの距離
}
function anPos(p, s) {
  const { pts, cum } = p;
  if (s <= 0) return { x: pts[0][0], y: pts[0][1], i: 0 };
  let lo = 0, hi = cum.length - 1;
  if (s >= cum[hi]) return { x: pts[hi][0], y: pts[hi][1], i: hi };
  while (hi - lo > 1) { const m = (lo + hi) >> 1; if (cum[m] < s) lo = m; else hi = m; }
  const f = (s - cum[lo]) / (cum[hi] - cum[lo] || 1);
  return { x: pts[lo][0] + f * (pts[hi][0] - pts[lo][0]), y: pts[lo][1] + f * (pts[hi][1] - pts[lo][1]), i: lo };
}

// シナリオから各艇の動き(スリットの順番、ターンの半径、ターンの早さ、最後の順位)を決める
function anModel(r, x) {
  const st = Object.fromEntries(slitRows(r).map((s) => [s.b.lane, s]));
  const sts = Object.values(st).map((s) => s.st);
  const stMin = sts.length ? Math.min(...sts) : 0.15;
  const boats = r.boats.map((b) => ({ lane: b.lane, c: courseOf(r, b), p: b.p_win, s: st[b.lane] }));
  const byC = Object.fromEntries(boats.map((b) => [b.c, b]));
  const combo = (x.best && x.best.combo || "").split("-").map(Number);
  const order = [x.lane, combo[1], combo[2]].filter((v, i, a) => v && a.indexOf(v) === i);
  boats.slice().sort((a, b) => b.p - a.p).forEach((b) => { if (!order.includes(b.lane)) order.push(b.lane); });
  const A = boats.find((b) => b.lane === x.lane), ca = A.c, type = x.type || (ca === 1 ? "逃げ" : "差し");
  for (const b of boats) {
    b.stv = b.s ? b.s.st : 0.17;
    b.dash = b.c >= 4;
    b.v = b.dash ? 18 : 15;        // ラインを切るときの速さ(m/秒)。ダッシュ勢は全速、スロー勢は加速の途中
    // ターンの形: 本物は全艇がブイのすぐそばで小さく回る(半径4〜9m)。外の艇ほど「少し遅れて・少し外・少し先(ブイを過ぎたところ)」で回る
    b.r = 4.5 + (b.c - 1) * 1.6;   // ターンの半径(m)
    b.ax = (b.c - 1) * 1.8;        // 回り始めの中心のずれ(m)。ブイより先で回る=遅れて回る
    b.d = (b.c - 1) * 0.1;         // ターン入口に着く遅れ(秒)
    b.vt = 1; b.drift = 1.5;       // 出口で外へ流れる量(m)
    b.rank = order.indexOf(b.lane);
  }
  const in1 = byC[1];
  if (type === "逃げ" || ca === 1) {
    A.r = 4.5; A.ax = 0; A.d = -0.15; A.vt = 1.15; A.drift = 1;     // 先に回って、小さく
    const B = boats.find((b) => b.lane === order[1]);
    if (B && B.c === 2) { B.r = 4.2; B.ax = 2.5; B.d = 0.3; } else if (B) { B.r = 6; B.ax = 3; B.d = 0.2; }
  } else if (type === "まくり") {
    A.r = 8; A.ax = 4; A.d = -0.45; A.vt = 1.4; A.drift = 3;         // 全速のまま外から、先に回り切る
    for (const b of boats) if (b.c < ca) { b.r = 4 + b.c * 1.4; b.ax = b.c * 1.6; b.d = 0.35 + b.c * 0.08; b.vt = 0.8; }  // 引き波で遅れる
    const F = byC[ca + 1];
    if (F) { F.r = 9.5; F.ax = 6; F.d = 0.1; }
  } else if (type === "まくり差し") {
    A.r = 4.5; A.ax = 3.5; A.d = 0.1; A.vt = 1.15;                   // 内の艇の間を割って、遅めに小さく
    if (in1 && in1 !== A) { in1.r = 6.5; in1.ax = 0.5; in1.d = -0.1; in1.drift = 3; }  // 1号艇は少し膨らむ
    for (const b of boats) if (b.c > 1 && b.c < ca) { b.r = 7 + b.c * 0.8; b.ax = 1 + b.c * 1.2; b.d = 0.15; b.vt = 0.85; }
  } else {  // 差し(抜き・恵まれなどもこの形で見せる)
    if (in1 && in1 !== A) { in1.r = 7; in1.ax = 0.5; in1.d = -0.05; in1.drift = 3.5; }  // 1号艇のターンが膨らむ
    A.r = 3.8; A.ax = 2.5; A.d = 0.25; A.vt = 1.1; A.drift = 0.5;    // その内側を、遅れて小さく差す
  }
  // 本物の時間(大時計の0秒が基準)で各艇の節目を決め、表示の時間へは「スリットだけスロー」の時計で写す
  const stMax = Math.min(stMin + 0.25, Math.max(...boats.map((b) => b.stv)));
  const SIM0 = -2.0, SLOW = 8, FAST = 2.3;
  const w1 = stMin - 0.15, w2 = stMax + 0.12;                 // スローにする本物の時間の範囲
  const d1 = w1 - SIM0, d2 = d1 + (w2 - w1) * SLOW;            // 表示の秒
  const disp = (sim) => sim < w1 ? sim - SIM0 : sim < w2 ? d1 + (sim - w1) * SLOW : d2 + (sim - w2) / FAST;
  const sim = (t) => t < d1 ? SIM0 + t : t < d2 ? w1 + (t - d1) / SLOW : w2 + (t - d2) * FAST;  // 表示の秒 → 大時計の秒
  let tEnd = 0;
  for (const b of boats) {
    const y0 = AN.laneY(b.c);
    const run = b.v * (b.stv - SIM0);                            // 本物の速さで、0秒の2秒前にいた場所
    const p0 = [-run, y0], p1 = [0, y0], p2 = [14, y0 + (b.c - 1) * -0.15];
    // 1マークへ: 外の艇ほど内へ絞りながら、ブイのそば(半径 r、中心はブイより ax 先)へ入る
    const cx = AN.markX + b.ax, e = [cx, AN.markY + b.r];
    const ctrl = [AN.markX - 18 - (b.c - 1) * 2, AN.markY + b.r + (y0 - AN.markY - b.r) * 0.25];
    // ターン: 小さく回って(減速)、出口は外へ少し流れる(ドリフト)。半円ではなく、出口が広がる形
    const arc = Array.from({ length: 31 }, (_, k) => {
      const f = k / 30, th = Math.PI / 2 - Math.PI * f, rr = b.r + b.drift * f * f;
      return [cx + rr * Math.cos(th), AN.markY + rr * Math.sin(th)];
    });
    const xo = arc[30];
    const fin = [AN.markX - 22 - b.rank * 8, xo[1] - 0.8 - (b.rank % 2) * 0.9];
    b.path = anPath([[p0, p1], [p1, p2], qb(p2, ctrl, e), arc, qb(xo, [AN.markX - 26, xo[1] - 0.4], fin)]);
    const tLine = b.stv, tIn = tLine + (b.path.at[2] - b.path.at[0]) / 18.5 + b.d;   // 直線は秒速18.5m
    const vTurn = (7.5 + 0.35 * b.r) * b.vt, tOut = tIn + (b.path.at[3] - b.path.at[2]) / vTurn;  // ターン中は減速(半径が小さいほど遅い)
    const tFin = tOut + (b.path.at[4] - b.path.at[3]) / 17;
    b.T = [disp(SIM0), disp(tLine), disp(tIn), disp(tOut), disp(tFin)];  // 表示の秒: 出発・スリット・ターン入口・出口・決着
    // 表示の秒 → 進んだ距離。スローの切れ目(w1, w2)でも節目を打ち、スローの間は本物どおりゆっくり進む
    const P = b.path, k = [[b.T[0], 0], [disp(w1), b.v * (w1 - SIM0)], [b.T[1], P.at[0]], [disp(w2), P.at[0] + 18.5 * (w2 - tLine)],
      [b.T[2], P.at[2]], [b.T[3], P.at[3]], [b.T[4], P.at[4]]];
    b.keys = k.filter((q, i) => i === 0 || (q[0] > k[i - 1][0] && q[1] >= k[i - 1][1] && q[1] <= P.at[4]));
    tEnd = Math.max(tEnd, b.T[4]);
  }
  const tSlitMax = disp(stMax), T2 = Math.min(...boats.map((b) => b.T[2])), T3 = Math.max(...boats.map((b) => b.T[3]));
  const lines = {
    "逃げ": `${x.lane}号艇が先にターンして逃げる`,
    "差し": `${in1 && in1 !== A ? in1.lane + "号艇のターンが膨らんだ内を、" : ""}${x.lane}号艇が差す`,
    "まくり": `${x.lane}号艇がスリットで先手、内の艇の外から一気にまくる`,
    "まくり差し": `${x.lane}号艇が内の艇の間を割って、1マークで差し込む`,
  };
  const slit = slitRows(r).filter((s) => s.atk || s.dent).map((s) => `${s.b.lane}号艇${s.atk ? "が攻め" : "が凹み"}`).join("・");
  const first = boats.slice().sort((a, b) => a.tSlit - b.tSlit)[0];
  return { boats, type, fastest: stMin, sim, T: [0, disp(stMin), tSlitMax, T2, T3, tEnd],
    cap: [`スタート: ${first.lane}号艇が最初にラインを切る${slit ? "。" + slit + "の隊形" : ""}`, `1マーク: ${lines[type] || lines["差し"]}`,
      `決着: ${order.slice(0, 3).join("-")}(この展開の中で${Math.round((x.best.p_cond || 0) * 100)}%)`] };
}

function anDraw(el, m, t) {
  const T = m.T, svg = el.querySelector("svg");
  const tr = svg.querySelector(".an-trails"), bg = svg.querySelector(".an-boats");
  if (!tr.childElementCount) {
    tr.innerHTML = m.boats.map((b) => `<polyline class="an-tr l${b.lane}" points=""/>`).join("");
    bg.innerHTML = m.boats.map((b) => `<g class="an-bt l${b.lane}"><path class="an-hull" d="${BOAT}"/><text y="0.62" x="-0.25" font-size="1.75" text-anchor="middle">${b.lane}</text><text class="an-flag" font-size="1.7"></text></g>`).join("");
  }
  const atSlit = t >= T[1] - 0.25 && t < T[2] + 0.5;
  const phase = t < T[3] - 0.6 ? 0 : t < T[5] - 0.3 ? 1 : 2;
  const clock = m.sim(t);
  el.querySelector(".an-phase").textContent = atSlit ? `スリット！ 大時計 ${Math.max(0, clock).toFixed(2)}` : phase === 0 && t > T[2] ? "1マークへ" : ["スタート", "1マーク", "決着"][phase];
  const cap = el.querySelector(".an-cap");
  if (cap.dataset.p !== String(phase)) { cap.dataset.p = phase; cap.textContent = m.cap[phase]; }
  let sx = 0, sy = 0;
  m.boats.forEach((b, i) => {
    const P = b.path, ks = b.keys;
    let s = P.at[4];
    for (let k = 1; k < ks.length; k++) if (t <= ks[k][0]) { const f = (t - ks[k - 1][0]) / (ks[k][0] - ks[k - 1][0]); s = ks[k - 1][1] + Math.max(0, f) * (ks[k][1] - ks[k - 1][1]); break; }
    const p = anPos(P, s), q = anPos(P, s + 0.6);  // 少し先の点から向きを取る
    const ang = Math.hypot(q.x - p.x, q.y - p.y) > 0.01 ? Math.atan2(q.y - p.y, q.x - p.x) * 180 / Math.PI : 0;
    sx += p.x; sy += p.y;
    tr.children[i].setAttribute("points", P.pts.slice(0, p.i + 1).concat([[p.x, p.y]]).map((q2) => q2[0].toFixed(2) + "," + q2[1].toFixed(2)).join(" "));
    const g = bg.children[i];
    g.setAttribute("transform", `translate(${p.x.toFixed(2)},${p.y.toFixed(2)})`);
    g.querySelector(".an-hull").setAttribute("transform", `rotate(${ang.toFixed(1)})`);
    // スリット: 切った艇から順に予想STと「攻め/凹み」。いちばん速い艇は強調。決着: 着順
    const crossed = t >= b.T[1] - 0.05;
    const slitTxt = b.s ? `${fmtST(b.s.st)}${b.s.atk ? " 攻め" : b.s.dent ? " 凹み" : ""}` : "";
    const flag = atSlit && crossed ? slitTxt : t >= T[5] - 0.2 && b.rank < 3 ? `${b.rank + 1}着` : "";
    const fe = g.querySelector(".an-flag");
    if (fe.textContent !== flag) {
      const fin = t >= T[5] - 0.2;  // スリットでは艇の前、決着では艇の上に出す
      fe.textContent = flag;
      fe.setAttribute("class", "an-flag" + (!fin && b.s && b.s.atk ? " atk" : fin ? " fin" : "") + (atSlit && b.s && b.s.st === m.fastest ? " fast" : ""));
      fe.setAttribute("x", fin ? 0 : 2.4); fe.setAttribute("y", fin ? -1.6 : 0.6); fe.setAttribute("text-anchor", fin ? "middle" : "start");
    }
  });
  // カメラ: 先頭集団の真ん中を追う。スリットは寄り、ターンは少し引き、決着は全体
  const n = m.boats.length, cx = sx / n, cy = sy / n;
  const W = phase === 2 ? AN.cam.fin : phase === 1 ? AN.cam.turn : AN.cam.start, H = W * 232 / 360;
  const want = phase === 2 ? [AN.markX - 45, AN.markY - 2, W, H] : [cx + (phase === 1 ? 6 : 10), Math.max(cy, AN.markY + (phase ? 2 : 10)) - (phase ? 4 : 0), W, H];
  const cam = el._cam || (el._cam = want.slice());
  const k = t < 0.05 ? 1 : 0.1;
  for (let j = 0; j < 4; j++) cam[j] += (want[j] - cam[j]) * k;
  svg.setAttribute("viewBox", `${(cam[0] - cam[2] / 2).toFixed(2)} ${(cam[1] - cam[3] / 2).toFixed(2)} ${cam[2].toFixed(2)} ${cam[3].toFixed(2)}`);
}

function anPlay(el, i) {
  const r = state.data && state.data.races.find((x) => x.race_id === el.dataset.id);
  const x = r && r.tenkai && r.tenkai.scenarios && r.tenkai.scenarios[i];
  if (!x) return;
  el.querySelectorAll(".an-chip").forEach((c) => c.setAttribute("aria-pressed", c.dataset.i === String(i)));
  const m = anModel(r, x);
  el.querySelector(".an-trails").innerHTML = "";
  el._cam = null;
  if (el._raf) cancelAnimationFrame(el._raf);
  el._i = i;
  state.anSel[el.dataset.id] = i;
  state.anSeen.add(el.dataset.id);
  const end = m.T[5] + AN.hold;
  if (anReduce()) { anDraw(el, m, end); return; }
  const t0 = performance.now();
  const step = (now) => {
    const t = (now - t0) / 1000;
    anDraw(el, m, Math.min(t, end));
    el._raf = t < end ? requestAnimationFrame(step) : 0;
  };
  el._raf = requestAnimationFrame(step);
}

// 初めて見えたときに1回だけ自動で再生する(2分ごとの描き直しでは再生し直さない)
const anObs = "IntersectionObserver" in window ? new IntersectionObserver((es) => es.forEach((e) => {
  if (e.isIntersecting && !state.anSeen.has(e.target.dataset.id)) anPlay(e.target, e.target._i || 0);
}), { threshold: 0.5 }) : null;
function setupAnims(root) {
  $$(".anim", root).forEach((el) => {
    if (el._ready) return;
    el._ready = true;
    el.addEventListener("click", (ev) => {
      const c = ev.target.closest(".an-chip");
      if (c) { anPlay(el, +c.dataset.i); return; }
      if (ev.target.closest(".an-re")) anPlay(el, el._i || 0);
    });
    const r = state.data.races.find((x) => x.race_id === el.dataset.id);
    const i = Math.min(state.anSel[el.dataset.id] || 0, r ? r.tenkai.scenarios.length - 1 : 0);
    el._i = i;
    el.querySelectorAll(".an-chip").forEach((c) => c.setAttribute("aria-pressed", c.dataset.i === String(i)));
    if (r) { const md = anModel(r, r.tenkai.scenarios[i]); anDraw(el, md, md.T[5] + 0.01); }  // まず決着の形を出しておく
    if (anObs && !anReduce()) anObs.observe(el);
  });
}

// ---- 公式サイトへのリンクと公式のコンピュータ予想 ----
const OFFICIAL = "https://www.boatrace.jp/owpc/pc/race/";
function officialHTML(r) {
  const id = String(r.race_id || "");
  if (id.length < 12) return "";
  const q = `?rno=${+id.slice(10, 12)}&jcd=${id.slice(8, 10)}&hd=${id.slice(0, 8)}`;
  const links = [["racelist", "出走表"], ["beforeinfo", "直前情報"], ["odds3t", "オッズ"], ["pcexpect", "コンピュータ予想"], ["raceresult", "結果"]]
    .map(([p, n]) => `<a href="${OFFICIAL}${p}${q}" target="_blank" rel="noopener">${n}</a>`).join("");
  let pcx = "";
  const x = r.pcx;
  if (x && x.marks && Object.keys(x.marks).length) {
    const ms = Object.entries(x.marks).sort((a, b) => a[1] - b[1]).map(([lane, k]) => `<span class="pm">${MARKS[k - 1] || ""}${tile(+lane)}</span>`).join("");
    const f3 = (x.focus3 || []).slice(0, 4).map((c) => tri(c)).join("");
    const ai = r.top && r.top[0] ? r.top[0].combo : "";
    const same = ai && (x.focus3 || []).includes(ai);
    pcx = `<div class="pcx"><div class="pcx-h">公式のコンピュータ予想</div>
      <div class="pcx-m">${ms}</div>${f3 ? `<div class="pcx-f">${f3}${ai ? `<span class="pcx-ai">${same ? "AIの本命と一致" : "AIの本命は別"}</span>` : ""}</div>` : ""}</div>`;
  }
  return `<div class="official">${pcx}<div class="olinks"><span class="k">公式サイト</span>${links}</div></div>`;
}

function resultHTML(r) {
  if (!r.result) return "";
  return `<div class="result">結果 ${tri(r.result.tri_combo)}<span class="pay">${r.result.tri_pay.toLocaleString()}円</span>${r.result.kimarite ? `<span class="kim">${esc(r.result.kimarite)}</span>` : ""}</div>`;
}

// 理論ぶつけ: 検証ラボの理論のうち、このレースに当てはまるもの(買い目ではない。札でデータの強さを示す)
function theoriesHTML(r) {
  const ns = r.theories || [];
  if (!ns.length) return "";
  const sm = r.th_sum || {};
  const lanes = (ls) => (ls || []).map((l) => `<span class="lane l${l}">${l}</span>`).join("");
  const item = (n) => `<li class="th ${esc(n.kind)}"><div class="th-h"><b>${esc(n.title)}</b>${lanes(n.lanes)}<span class="th-b">${esc(n.badge)}</span></div>
    <p>${esc(n.text)}</p>${n.gen ? `<p class="th-gen">ゲンさん「${esc(n.gen)}」</p>` : ""}${n.lab_title ? `<p class="th-lab">検証ラボ『${esc(n.lab_title)}』</p>` : ""}</li>`;
  const head = sm.conflict
    ? `<p class="th-conf">悩ましいレース: インに有利(${esc((sm.plus || []).join("・"))})と、不利(${esc((sm.minus || []).join("・"))})がぶつかっている</p>` : "";
  const first = ns.slice(0, 4).map(item).join("");
  const rest = ns.slice(4).map(item).join("");
  return `<div class="theories"><h3>理論ぶつけ<small>当てはまる理論${ns.length}つ。買い目ではなく、考え方のヒント</small></h3>${head}<ul>${first}</ul>${rest ? `<details><summary>ほかに${ns.length - 4}つ</summary><ul>${rest}</ul></details>` : ""}</div>`;
}

function stageHTML(r) {
  return r.stage === "late"
    ? `<div class="stage late">展示を反映した直前予想(${esc(r.updated_at)})</div>`
    : `<div class="stage">朝の予想(展示前)</div>`;
}

// 見る順: AIのひと言 → 荒れ度 → 結果 → 本命 → 期待値の買い目 → AIの狙い目 → 展開予測(アニメ・シナリオ・スリット) → 各艇 → ほかの候補 → 公式サイト
const bodyHTML = (r) => stageHTML(r) + aiLine(r) + arashiHTML(r) + theoriesHTML(r) + resultHTML(r) + honmeiHTML(r) + evHTML(r) + pickHTML(r) + tenkaiHTML(r) + boatsHTML(r) + combosHTML(r) + officialHTML(r);

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
  if (r.pick && r.pick.some((x) => x.hit)) b.push("狙い目的中");
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
      <span class="vr"><b>${esc(r.venue)}</b><span class="n">${r.rno}R</span>${r.stage === "late" ? `<span class="late" title="直前予想"></span>` : ""}${!r.result && arashiLevel(r) >= 5 ? `<span class="are">荒れ</span>` : ""}${!r.result && r.th_sum && r.th_sum.conflict ? `<span class="nayam" title="理論がぶつかる悩ましいレース">悩</span>` : ""}</span>
      <span class="hits">${hitBadge(r)}</span>${right}</summary>
    <div class="body">${bodyHTML(r)}</div></details>`;
}

// ---- 今日の荒れそうなレース ----
// 予想モデルの「1号艇が負ける確率」が高い順に、まだ締切前のレースを3つ。理由は本物と確かめた型だけ(ST・決まり手・前づけ・今節の足・モーター)。
// 荒れそう=当てやすい・儲かる、ではない(1号艇が負けることもオッズに織り込まれている。荒れ狙いの検証 E7 で確認)
function anaReasons(r) {
  const out = [];
  const inB = r.boats.find((b) => courseOf(r, b) === 1) || r.boats[0];
  const t = inB.traits || {};
  const st = t.st_pred != null && r.stage === "late" ? t.st_pred : t.st;
  const inBad = [];
  if (t.nige != null && t.nige < 0.39) inBad.push(`逃げ率${Math.round(t.nige * 100)}%`);
  if (st != null && st >= 0.18) inBad.push(`ST ${fmtST(st)}`);
  if (t.series != null && t.series <= -0.27) inBad.push("今節の足△");
  else if (t.motor != null && t.motor <= -0.15) inBad.push("モーター△");
  if (t.f != null && t.f >= 1) inBad.push("F持ち");
  if (inBad.length) out.push(`${inB.lane}号艇に不安材料(${inBad.slice(0, 2).join("・")})`);
  for (const b of r.boats) {
    const c = courseOf(r, b);
    if (c < 2 || c > 5) continue;
    const u = b.traits || {};
    const types = [["まくり", u.makuri, 0.048], ["差し", u.sashi, 0.042], ["まくり差し", u.mz, 0.040]]
      .filter(([, v, th]) => v != null && v >= th).sort((x, y) => y[1] / y[2] - x[1] / x[2]);
    const bst = u.st_pred != null && r.stage === "late" ? u.st_pred : u.st;
    if (types.length) out.push(`${b.lane}号艇は${types[0][0]}型${bst != null && bst <= 0.144 ? `でST速い(${fmtST(bst)})` : ""}`);
    else if (bst != null && bst <= 0.135) out.push(`${b.lane}号艇のST速い(${fmtST(bst)})`);
  }
  return out.slice(0, 3);
}
function anaRaces() {
  if (!state.data || state.day !== jst().date) return [];
  return state.data.races.filter((r) => !finished(r) && r.arashi && r.arashi.in_lose != null && (minsLeft(r) == null || minsLeft(r) > 0))
    .sort((a, b) => b.arashi.in_lose - a.arashi.in_lose).slice(0, 3);
}
const xlen = (s) => [...s].reduce((n, ch) => n + ((ch.codePointAt(0) < 0x1100 || (ch.codePointAt(0) >= 0xff61 && ch.codePointAt(0) <= 0xff9f)) ? 1 : 2), 0);
function anaText(list) {
  const d = jst().date;
  const lines = list.map((r, i) => `${"①②③"[i]} ${r.venue}${r.rno}R(${r.deadline}) 1号艇が負ける${Math.round(r.arashi.in_lose * 100)}%`);
  const why = list[0] ? anaReasons(list[0]) : [];
  const head = `今日の荒れそうなレース🌊 ${+d.slice(5, 7)}/${+d.slice(8)}\n\n${lines.join("\n")}`;
  for (let k = why.length; k >= 0; k--) {
    const w = k ? `\n\n${list[0].venue}${list[0].rno}R:${why.slice(0, k).join("、")}` : "";
    const body = `${head}${w}\n\n荒れそう=当てやすい、ではないです。どのレースが荒れると思う?`;
    if (xlen(body) <= 280) return body;
  }
  return `${head}\n\nどのレースが荒れると思う?`;
}
function anaHTML() {
  const list = anaRaces();
  if (!list.length) return "";
  const items = list.map((r) => {
    const why = anaReasons(r);
    return `<li><button type="button" class="ana-go" data-id="${r.race_id}"><span class="ana-vr"><b>${esc(r.venue)}</b> ${r.rno}R <small>${esc(r.deadline || "")}締切</small></span>
      <span class="ana-p">1号艇が負ける<b>${Math.round(r.arashi.in_lose * 100)}%</b></span></button>
      ${why.length ? `<p class="ana-why">${esc(why.join("。"))}</p>` : ""}</li>`;
  }).join("");
  return `<section class="box ana"><h3>今日の荒れそうなレース<small>締切前・AIの確率順</small></h3><ol>${items}</ol>
    <p>荒れ度の一番上(5段階の5)は、過去に1号艇が74%負けました。ただ、荒れることもオッズに織り込まれているので、荒れそうなレースを買えば儲かるわけではありません。</p>
    <button type="button" class="ana-copy">Xの投稿文をコピー</button></section>`;
}
function setupAna(box) {
  $$(".ana-go", box).forEach((b) => b.onclick = () => {
    const el = $(`details.row[data-id="${b.dataset.id}"], section.next[data-id="${b.dataset.id}"]`, box);
    if (!el) return;
    if (el.tagName === "DETAILS") { el.open = true; state.open.add(b.dataset.id); }
    el.scrollIntoView({ behavior: "smooth", block: "start" });
  });
  const c = $(".ana-copy", box);
  if (c) c.onclick = () => copyText(anaText(anaRaces()), c);
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
  let html = state.venue === "all" ? anaHTML() : "";
  if (up.length) {
    html += `<div class="now-grid"><div><h2 class="sect">次の締切</h2>${heroHTML(up[0])}</div><div>`;
    if (up.length > 1) html += `<h2 class="sect">このあと</h2><div class="list">${up.slice(1).map(rowHTML).join("")}</div>`;
    html += `</div></div>`;
  }
  if (done.length) html += `<h2 class="sect">終わったレース</h2><div class="list">${done.map(rowHTML).join("")}</div>`;
  box.innerHTML = html;
  setupAnims(box);
  setupAna(box);
}

function renderBets() {
  const box = $("#tab-bets");
  const races = visibleRaces().filter((r) => (r.bets && r.bets.length) || (r.pick && r.pick.length));
  const late = state.data.races.filter((r) => r.stage === "late").length;
  let html = `<p class="note">締切の約30分前から、展示とオッズを取り込んで5分ごとに更新します。確率×オッズ(期待値)が100%以上の組を出します。120%以上は赤で強調。直前予想 ${late} / ${state.data.races.length} レース</p>
    <p class="note">「期待値のある買い目」(赤枠)はモデルとオッズを合わせた確率で計算するので、めったに出ません(出たらLINEで通知)。「AIの狙い目」はモデルの確率だけで計算した参考の組で、まだ勝てる根拠はありません。</p>`;
  if (!races.length) {
    box.innerHTML = html + `<div class="empty">今のところ期待値の高い買い目はありません。締切が近づくと出てきます。</div>`;
    return;
  }
  const up = races.filter((r) => !finished(r)).sort(byTime);
  const done = races.filter(finished).sort((a, b) => byTime(b, a));
  if (up.length) html += `<div class="cards">${up.map(heroHTML).join("")}</div>`;
  if (done.length) html += `<h2 class="sect">終わったレース</h2><div class="list">${done.map(rowHTML).join("")}</div>`;
  box.innerHTML = html;
  setupAnims(box);
}

function stat(k, v, cls = "") { return `<div class="stat"><div class="k">${k}</div><div class="v ${cls}">${v}</div></div>`; }

// 表示中の日の途中成績(終わったレースの結果は直前予想の更新のたびに付く)。1点100円で買ったとして計算
function todayBox() {
  const races = (state.data && state.data.races || []).filter((r) => r.result);
  if (!races.length) return "";
  const acc = () => ({ races: 0, bets: 0, hits: 0, ret: 0 });
  const top = acc(), pick = acc(), ev = acc();
  const add = (a, list, r) => {
    if (!list || !list.length) return;
    a.races++;
    for (const b of list) { a.bets++; if (b.combo === r.result.tri_combo) { a.hits++; a.ret += r.result.tri_pay; } }
  };
  for (const r of races) {
    add(top, r.top && r.top[0] ? [r.top[0]] : [], r);
    add(pick, r.pick, r);
    add(ev, r.bets, r);
  }
  const pl = (v) => (v >= 0 ? "+" : "−") + Math.abs(v).toLocaleString() + "円";
  const block = (title, a, note) => {
    if (!a.bets) return "";
    const roi = a.ret / (a.bets * 100), prof = a.ret - a.bets * 100;
    return `<h4 class="tb">${title}</h4><div class="stats">${stat("回収率", Math.round(roi * 100) + "<small>%</small>", roi >= 1 ? "good" : "bad")}
      ${stat("収支", pl(prof), prof >= 0 ? "good" : "bad")}</div>
      <p class="tbn">的中 ${a.hits}本 / ${a.bets}点(${a.races}レース)・払戻 ${a.ret.toLocaleString()}円${note ? "。" + note : ""}</p>`;
  };
  return `<div class="box"><h3>${state.data.date === jst().date ? "今日" : esc(state.data.date)}の成績<small>途中経過</small></h3>
    <p>結果の出た ${races.length} レースを、1点100円で買ったとして計算</p>
    ${block("本命(3連単1点)", top, "")}
    ${block("AIの狙い目(参考)", pick, "")}
    ${block("期待値のある買い目", ev, "")}</div>`;
}

// ---- 期待値で買った場合の検証 ----
// 全期間(scripts/upset_eval.py --walk-forward → docs/data/ev_check.json): 各レースより前のデータだけで学習したモデルの確率 × 確定オッズ
const pc0 = (x) => x == null ? "-" : `${Math.round(x * 100)}%`;
const ci0 = (c) => c ? `${Math.round(c[0] * 100)}〜${Math.round(c[1] * 100)}%` : "-";
const ymd = (s) => `${String(s).slice(0, 4)}/${+String(s).slice(4, 6)}/${+String(s).slice(6, 8)}`;
function evCheckHTML(d) {
  const a = d.all;
  const pr = a.pick_rule, ev = a.all_ev100;
  const band = (b) => b.band[1] == null ? `${Math.round(b.band[0] * 100)}%以上` : `${Math.round(b.band[0] * 100)}〜${Math.round(b.band[1] * 100)}%`;
  const rows = a.bands.map((b) => `<tr><td>${band(b)}</td><td>${b.bets.toLocaleString()}</td><td>${b.hits}</td>
    <td class="${b.roi >= 1 ? "good" : ""}">${pc0(b.roi)}</td><td>${ci0(b.roi_ci90)}</td></tr>`).join("");
  const half = (h, n) => h ? `${n}(${ymd(h.period[0])}〜${ymd(h.period[1])})${pc0(h.pick_rule.roi)}` : "";
  const bl = a.blend_ev100;
  return `<div class="box"><h3>期待値で買った場合の検証<small>全期間</small></h3>
    <p>${ymd(a.period[0])} 〜 ${ymd(a.period[1])} のオッズのある ${a.races.toLocaleString()} レースを、そのレースより前のデータだけで学習したモデルで予想し直し、確定オッズで1点100円買った場合(本番より少し甘め: 本番は締切前のオッズで判断)。</p>
    <h4 class="tb">AIの狙い目と同じ買い方<small>期待値100%以上を高い順に3点まで</small></h4>
    <div class="stats">${stat("回収率", pc0(pr.roi), pr.roi >= 1 ? "good" : "bad")}${stat("ブレの幅", ci0(pr.roi_ci90))}
      ${stat("点数", pr.bets.toLocaleString())}${stat("的中", `${pr.hits}<small>本</small>`)}</div>
    <p class="tbn">${half(d.first_half, "前半")}・${half(d.second_half, "後半")}。期待値100%以上を全部買うと ${pc0(ev.roi)}(${ev.bets.toLocaleString()}点)</p>
    <h4 class="tb">期待値の帯ごと</h4>
    <div class="scroll"><table class="tbl"><thead><tr><th>期待値</th><th>点数</th><th>的中</th><th>回収率</th><th>ブレの幅</th></tr></thead>
    <tbody>${rows}</tbody></table></div>
    <p class="tbn">「ブレの幅」は、同じ買い方を続けても、たまたまでこのくらい上下するという目安(統計でいう90%区間)。期待値が高い組ほど当たりにくく、見積もりのずれも大きい。${bl ? `モデルとオッズを合わせた本当の期待値で100%を超えた組は、この期間で ${bl.bets.toLocaleString()}点だけ(「期待値のある買い目」がめったに出ないのはこのため)。` : ""}</p></div>`;
}
// 全期間の検証がまだ無いとき: 学習レポートの直近のテスト期間の分
function evRecentHTML(e) {
  const evRows = e.ev_blend.map((r, i) => `<tr><td>${Math.round(r.ev_min * 100)}%以上</td><td>${r.bets}</td>
    <td>${r.hit_rate != null ? pct1(r.hit_rate) + "%" : "-"}</td><td>${r.roi != null ? (r.roi * 100).toFixed(0) + "%" : "-"}</td>
    <td>${e.ev_model[i].roi != null ? (e.ev_model[i].roi * 100).toFixed(0) + "%" : "-"}</td></tr>`).join("");
  return `<div class="box"><h3>期待値で買った場合の検証<small>直近</small></h3>
    <p>${e.period[0]} 〜 ${e.period[1]} の ${e.races} レース。締切時オッズで1点100円、実際の払戻金で計算。</p>
    <div class="scroll"><table class="tbl"><thead><tr><th>期待値</th><th>点数</th><th>的中率</th><th>回収率</th><th>モデル単体</th></tr></thead>
    <tbody>${evRows}</tbody></table></div></div>`;
}

// ---- 出目の期待値(過去の回収率) ----
// 公式の結果(2023-10〜)から、条件ごとに「その出目を買い続けたら」の的中と回収率。総当たりの検証(scripts/deme_scan.py)の結果も添える
const DEME = { data: null, v: "all", c: "all", r: "all", q: "3-256-256" };
const ALL120 = [];
for (let a = 1; a <= 6; a++) for (let b = 1; b <= 6; b++) for (let c = 1; c <= 6; c++) if (a !== b && b !== c && a !== c) ALL120.push(`${a}-${b}-${c}`);
// 「3-256-256」「1-2-全」「BOX135」などを3連単の組に展開する
function expandDeme(q) {
  q = String(q || "").replace(/\s/g, "").replace(/[ー－―]/g, "-").replace(/[０-９]/g, (d) => String.fromCharCode(d.charCodeAt(0) - 65248)).toUpperCase();
  const box = q.match(/^BOX([1-6]{3,6})$/);
  if (box) { const s = new Set(box[1]); return ALL120.filter((c) => c.split("-").every((x) => s.has(x))); }
  const parts = q.split("-");
  if (parts.length !== 3) return [];
  const sets = parts.map((p) => p === "全" ? new Set("123456") : /^[1-6]+$/.test(p) ? new Set(p) : null);
  if (sets.some((x) => !x)) return [];
  return ALL120.filter((c) => c.split("-").every((x, i) => sets[i].has(x)));
}
const yen = (v) => Math.round(v).toLocaleString();
function demeHTML() {
  const d = DEME.data;
  if (!d) return `<h3>出目の期待値<small>過去の回収率</small></h3><p>読み込み中…</p>`;
  const key = `${DEME.r === "all" ? DEME.v : "all"}|${DEME.c}|${DEME.r}`;
  const cell = d.cells[key];
  const opt = (vals, cur, lab) => vals.map((v) => `<option value="${esc(v)}"${v === cur ? " selected" : ""}>${esc(lab ? lab(v) : v)}</option>`).join("");
  const sel = `<div class="dm-sel">
    <label>場<select data-k="v"${DEME.r !== "all" ? " disabled" : ""}>${opt(["all", ...d.venues], DEME.r === "all" ? DEME.v : "all", (v) => v === "all" ? "全場" : v)}</select></label>
    <label>種別<select data-k="c">${opt(["all", ...d.cats], DEME.c, (v) => v === "all" ? "すべて" : v)}</select></label>
    <label>R<select data-k="r">${opt(["all", ...Array.from({ length: 12 }, (_, i) => String(i + 1))], DEME.r, (v) => v === "all" ? "すべて" : v + "R")}</select></label></div>`;
  let body = "";
  if (!cell) body = `<p>この条件はレースが少ないので出していません。</p>`;
  else {
    const roi = (h, p, n, k = 1) => n ? (p * 10) / (n * k * 100) : null;
    const pc = (x) => x == null ? "-" : `${Math.round(x * 100)}%`;
    const cls = (x) => x != null && x >= 1 ? "good" : "";
    // 入力した出目・フォーメーション
    const cs = expandDeme(DEME.q);
    let qrow = "";
    if (DEME.q) {
      if (!cs.length) qrow = `<p class="dm-q-err">「3-256-256」「1-2-全」「BOX135」の形で入力してください</p>`;
      else {
        const idx = cs.map((c) => ALL120.indexOf(c));
        const sum = (arr) => idx.reduce((a, i) => a + arr[i], 0);
        const h = sum(cell.h), p = sum(cell.p), h1 = sum(cell.h1), p1 = sum(cell.p1);
        const r3 = roi(h, p, cell.n, cs.length), r1 = roi(h1, p1, cell.n1, cs.length);
        qrow = `<div class="dm-q-res"><div><b>${esc(DEME.q)}</b>(${cs.length}点)</div>
          <div class="stats">${stat("回収率(全期間)", pc(r3), r3 >= 1 ? "good" : "bad")}${stat("直近1年", pc(r1), r1 != null && r1 >= 1 ? "good" : "bad")}
          ${stat("的中", `${h}<small>本</small>`)}${stat("的中率", pct1(h / cell.n) + "%")}</div>
          <p class="tbn">${cell.n.toLocaleString()}レースで毎回${cs.length * 100}円 → 払戻 ${yen(p * 10)}円${h ? `(平均 ${yen((p * 10) / h)}円)` : ""}</p></div>`;
      }
    }
    const rows = ALL120.map((c, i) => ({ c, h: cell.h[i], r: roi(cell.h[i], cell.p[i], cell.n), r1: roi(cell.h1[i], cell.p1[i], cell.n1), avg: cell.h[i] ? cell.p[i] * 10 / cell.h[i] : 0 }))
      .filter((x) => x.h >= 10).sort((a, b) => b.r - a.r).slice(0, 12);
    const all = cell.p.reduce((a, b) => a + b, 0) * 10 / (cell.n * 120 * 100);
    body = `${qrow}<h4 class="tb">回収率の高い出目(10本以上当たったもの)</h4>
      <p class="tbn">${cell.n.toLocaleString()}レース(直近1年 ${cell.n1.toLocaleString()})。120通りを全部買うと回収率 ${pc(all)}</p>
      <div class="scroll"><table class="tbl dm"><thead><tr><th>出目</th><th>的中</th><th>平均配当</th><th>回収率</th><th>直近1年</th></tr></thead><tbody>
      ${rows.map((x) => `<tr><td>${tri(x.c)}</td><td>${x.h}<small>本</small></td><td>${yen(x.avg)}</td><td class="${cls(x.r)}">${pc(x.r)}</td><td class="${cls(x.r1)}">${pc(x.r1)}</td></tr>`).join("")}
      </tbody></table></div>`;
  }
  const sc = d.scan || {};
  const band = (sc.bands || []).find((b) => b.disc[0] === 1);
  const w = d.watch;
  const wrows = (w && w.items || []).map((x) => {
    const f = x.fwd || {};
    const cond = x.cond.replace(/^(場|種別):/, "").replace("準優勝戦", "準優").replace("×1号艇:", "×1号艇");
    return `<tr><td class="l">${esc(cond)}<br><b>${esc(x.strat)}</b></td><td>${Math.round(x.roi_disc * 100)}→${Math.round(x.roi_conf * 100)}%</td>
      <td class="${f.roi >= 1 ? "good" : ""}">${f.races ? `${Math.round(f.roi * 100)}%<br><small>${f.hits}本/${f.races}R</small>` : "まだなし"}</td></tr>`;
  }).join("");
  return `<h3>出目の期待値<small>過去の回収率</small></h3>
    <p>${esc(d.period[0])} 〜 ${esc(d.period[1])} の公式の結果から、その出目を毎回100円ずつ買い続けた場合の成績。</p>
    ${sel}<div class="dm-q"><input type="text" inputmode="text" value="${esc(DEME.q)}" placeholder="例 3-256-256 / 1-2-全 / BOX135" aria-label="出目・フォーメーション"></div>
    ${body}
    <p class="note dm-note">注意: 回収率100%超えの出目があっても、たまたまの可能性が高いです。約${(sc.n_tests || 0).toLocaleString()}通り(出目×条件)を総当たりした検証では、前半2年で100〜120%だった買い方の後半1年の平均は${band ? Math.round(band.conf_mean * 100) : "-"}%、ブレの幅の下限まで100%を超えたものは${sc.passed ?? 0}件でした。</p>
    ${wrows ? `<h4 class="tb">出目ウォッチ<small>${esc(w.since)} の検証で前半・後半とも100%超え → その後のレースで追跡</small></h4>
      <div class="scroll"><table class="tbl dm"><thead><tr><th class="l">条件・出目</th><th>検証時(前半→後半)</th><th>その後の回収率</th></tr></thead><tbody>${wrows}</tbody></table></div>` : ""}`;
}
async function renderDeme() {
  const el = $("#deme-box");
  if (!el) return;
  if (!DEME.data) {
    el.innerHTML = demeHTML();
    try { DEME.data = await getJSON("api/data/deme.json"); } catch (e) { el.innerHTML = `<h3>出目の期待値</h3><p>集計を準備中です。</p>`; return; }
  }
  const box = $("#deme-box");
  if (!box) return;
  box.innerHTML = demeHTML();
  if (!box._wired) {
    box._wired = true;
    box.addEventListener("change", (e) => {
      const k = e.target.dataset && e.target.dataset.k;
      if (k) { DEME[k] = e.target.value; renderDeme(); }
    });
    let tm = 0;
    box.addEventListener("input", (e) => {
      if (!e.target.matches(".dm-q input")) return;
      clearTimeout(tm);
      tm = setTimeout(() => {
        DEME.q = e.target.value.trim();
        const pos = e.target.selectionStart;
        renderDeme();
        const inp = $("#deme-box .dm-q input");
        if (inp) { inp.focus(); try { inp.setSelectionRange(pos, pos); } catch (_) { } }
      }, 350);
    });
  }
}

async function renderTrack() {
  const box = $("#tab-track");
  let track = { days: [] }, rep = null;
  // 成績・検証レポートは予想とは別のジョブが書くので、読めなくても(古い鍵・作り直し中など)ログイン画面には戻さず、その欄だけ出さない
  let repNote = "";
  try { track = await getJSON("api/data/track.json"); } catch (e) { /* まだ無い(翌朝から集計) */ }
  try { rep = await getJSON("api/data/report.json"); } catch (e) { repNote = e instanceof Locked ? "検証レポートを作り直し中です。しばらくすると見られます。" : ""; }
  let evc = null;
  try { evc = await getJSON("api/data/ev_check.json"); } catch (e) { /* まだ無い(全期間の検証が終わると出る) */ }
  const t = track.days.reduce((a, d) => {
    for (const k of ["races", "top1_hit", "bets", "bet_hits", "invest", "return", "pick_races", "pick_bets", "pick_hits", "pick_return"]) a[k] = (a[k] || 0) + (d[k] || 0);
    return a;
  }, {});
  let html = todayBox();
  html += `<div class="box"><h3>実際の成績</h3>`;
  if (t.races) {
    const roi = t.invest ? t.return / t.invest : 0;
    html += `<p>${track.days[0].date} 〜 ${track.days[track.days.length - 1].date}(${track.days.length}日、${t.races}レース)</p>
      <div class="stats">${stat("期待値買いの回収率", t.invest ? (roi * 100).toFixed(0) + "%" : "-", roi >= 1 ? "good" : "bad")}
      ${stat("収支(1点100円)", (t.return - t.invest >= 0 ? "+" : "") + (t.return - t.invest).toLocaleString() + "円")}
      ${stat("買い目の的中率", t.bets ? pct1(t.bet_hits / t.bets) + "%" : "-")}
      ${stat("本命3連単の的中率", pct1(t.top1_hit / t.races) + "%")}</div>`;
    if (t.pick_bets) {
      const nr = t.pick_return / (t.pick_bets * 100), np = t.pick_return - t.pick_bets * 100;
      html += `<h3 class="sub">AIの狙い目(参考)</h3><p>締切前のオッズで判断した本番と同じ条件の成績。${t.pick_races}レース・${t.pick_bets}点</p>
        <div class="stats">${stat("回収率", (nr * 100).toFixed(0) + "%", nr >= 1 ? "good" : "bad")}
        ${stat("収支(1点100円)", (np >= 0 ? "+" : "") + np.toLocaleString() + "円")}
        ${stat("的中", `${t.pick_hits}<small>本</small>`)}${stat("的中率", pct1(t.pick_hits / t.pick_bets) + "%")}</div>`;
    }
  } else html += `<p>予想を始めた翌朝から集計します。</p>`;
  html += `</div>`;
  html += evc ? evCheckHTML(evc) : (rep && rep.ev ? evRecentHTML(rep.ev) : "");
  html += `<div class="box deme" id="deme-box"></div>`;
  if (!rep && repNote) html += `<div class="box"><p>${repNote}</p></div>`;
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
    if (st.top_features) {
      html += `<div class="box"><h3>よく効いている要素</h3><p>${Object.keys(st.top_features).slice(0, 10).map(esc).join("、")}</p></div>`;
    }
  }
  box.innerHTML = html;
  renderDeme();
}

// ---- 記事(グレードレースの下書き: 毎朝 cards ブランチの ura/ に置かれる) ----
const URA = { index: null, open: null, cache: {} };
async function copyText(text, btn) {
  try { await navigator.clipboard.writeText(text); } catch (e) {
    const ta = document.createElement("textarea"); ta.value = text; document.body.appendChild(ta); ta.select();
    try { document.execCommand("copy"); } catch (e2) { }
    ta.remove();
  }
  if (btn) { const t = btn.textContent; btn.textContent = "コピーしました"; setTimeout(() => btn.textContent = t, 1500); }
}
// 出した記事の記録(reports/published.json)は、GitHub の issue「公開: <key> note|X」から足す(publish_log.yml が記録して閉じる)
const REPO = "cfwjr7jbvh-ctrl/kyotei-yosou";
function pubText(pub) {
  if (!pub || !pub.length) return "";
  return " ・ 出した: " + pub.map((p) => `${p.channel}${p.slot ? " " + p.slot : ""} ${+p.date.slice(5, 7)}/${+p.date.slice(8)}${p.no ? `(第${p.no}号)` : ""}`).join("、");
}
function pubIssueURL(key, channel, slot) {
  const d = new Date(Date.now() + 9 * 3600e3).toISOString().slice(0, 10);
  const body = `url: (ここに出した${channel === "note" ? "記事" : "投稿"}のURLを貼る)\ndate: ${d}` + (slot ? `\nslot: ${slot}` : "") +
    `\n\n(このまま「Submit」で記録されます。日付は出した日。URLは後から --update でも直せます)`;
  return `https://github.com/${REPO}/issues/new?title=${encodeURIComponent(`公開: ${key} ${channel}`)}&body=${encodeURIComponent(body)}`;
}
function uraMeta(it) {
  const hd = `${+it.hd.slice(4, 6)}/${+it.hd.slice(6)}`;
  const pub = pubText(it.pub);
  if (it.grade === "LAB") return `毎週の検証 ・ ${hd}` + (pub || " ・ まだ出していない");
  if (it.grade === "毎日") return `毎日の理論ぶつけ ・ ${hd}の分(その日に出す)` + pub;
  if (it.grade === "X") return `今日の X 投稿 ・ ${hd}の分` + pub;
  if (it.grade === "大一番") return (it.stars ? `<b class="ura-stars">注目度${esc(it.stars)}</b> ` : "") + `大一番の1レース特集 ・ ${esc(it.venue)} ${hd}(その日に出す)` + pub;
  return (it.stars ? `<b class="ura-stars" title="注目度(買う人・見る人が多そうか)">注目度${esc(it.stars)}</b> ` : "") +
    `${esc(it.venue)} ${hd}〜 ・ 出場${it.n}人 ・ 注目${(it.picks || []).length}人` + pub;
}
async function xStatsHTML() {
  let st = null, rep = null;
  try { st = await (await fetch("reports/x_stats.json?t=" + Date.now())).json(); } catch (e) { }
  try { rep = await getJSON("api/data/x_replies.json"); } catch (e) { }
  if (!st && !rep) return "";
  let html = "";
  if (st && st.by_kind) {
    const rows = Object.entries(st.by_kind).sort((a, b) => b[1].impressions - a[1].impressions).map(([k, v]) =>
      `<tr><td>${esc(k)}</td><td>${v.n}</td><td>${v.impressions}</td><td>${v.react_pct ?? "-"}%</td><td>${v.profile_per_1000 ?? "-"}</td><td>${v.replies}</td><td>${v.votes ?? 0}</td></tr>`).join("");
    html += `<div class="ura-sec"><h3>X の反応(投稿の種類ごとの平均)<small> ${esc(st.asof || "")}${st.followers != null ? ` ・ フォロワー ${st.followers}` : ""}</small></h3>
      <div class="scroll"><table class="tbl"><thead><tr><th>種類</th><th>本</th><th>表示</th><th>反応率</th><th>プロフへ<br>(1000表示)</th><th>返信</th><th>票</th></tr></thead><tbody>${rows}</tbody></table></div></div>`;
  }
  if (rep && rep.replies && rep.replies.length) {
    html += `<div class="ura-sec"><h3>返信待ち(${rep.replies.length}件)</h3>` + rep.replies.slice(0, 20).map((r) =>
      `<div class="ura-post"><div class="n"><span>@${esc(r.from)} ${esc((r.at || "").slice(5, 16).replace("T", " "))}</span><a href="${esc(r.url)}" target="_blank" rel="noopener">開く</a></div>${esc(r.text)}</div>`).join("") + `</div>`;
  }
  return html;
}

async function renderUra() {
  const box = $("#tab-ura");
  if (URA.open) return renderUraOne(box, URA.open);
  box.innerHTML = `<div class="empty">読み込み中…</div>`;
  try { URA.index = await getJSON("api/data/ura/index.json"); } catch (e) {
    box.innerHTML = `<div class="empty">${e instanceof Locked ? "記事の下書きは作り直し中です。しばらくすると見られます。" : "グレードレース(SG・G1)の初日が近づくと、ここに下書きが出ます。"}</div>`;
    return;
  }
  const items = URA.index.items || [];
  let html = await xStatsHTML();
  html += `<p class="ura-note">SG・G1 の初日の${URA.index.days_before}日前から、毎朝作り直します(${esc(URA.index.asof)})。note の本文、X の投稿、選手カードの画像をここからコピー・保存できます。</p>`;
  html += items.length ? `<div class="ura-list">` + items.map((it) =>
    `<button class="ura-item" data-key="${esc(it.key)}"><span class="g">${esc(it.grade)}</span><span class="t">${esc(it.title)}</span><span class="m">${uraMeta(it)}</span></button>`).join("") + `</div>`
    : `<div class="empty">いま対象の節はありません。</div>`;
  box.innerHTML = html;
  $$(".ura-item", box).forEach((b) => b.onclick = () => { URA.open = b.dataset.key; renderUra(); window.scrollTo({ top: 0 }); });
}
async function renderUraOne(box, key) {
  if (!URA.cache[key]) {
    box.innerHTML = `<div class="empty">読み込み中…</div>`;
    try { URA.cache[key] = await getJSON(`api/data/ura/${key}.json`); } catch (e) { URA.open = null; return renderUra(); }
  }
  const d = URA.cache[key];
  const body = d.x.split("\n").filter((l) => !/^(画像|出し方):/.test(l)).join("\n");
  const posts = body.split(/\n(?=--- 投稿)/).filter((x) => x.startsWith("--- 投稿")).map((x) => {
    const m = x.match(/^--- 投稿(\d+)\((\d+)(?:字|\/\d+)\)(.*?) ---\n([\s\S]*?)\n*$/);
    return m ? { n: m[1], len: m[2], warn: m[3].trim(), body: m[4].trim() } : null;
  }).filter(Boolean);
  const tail = (d.x.split("\n").filter((l) => /^(画像|出し方):/.test(l))).join("\n");
  let html = `<div class="ura-head"><button id="ura-back">← 一覧</button><h2>${esc(d.title)}</h2></div>
  <p class="ura-note">${uraMeta(d)} ・ 集計 ${esc(d.asof)}${d.missing && d.missing.length ? ` ・ 見つからない選手 ${d.missing.length}人` : ""}</p>
  <div class="ura-sec"><h3>記事(確認用)</h3><p>出す前に、見出しと数字を読んで直してください。</p>
    <div class="ura-btns"><button id="ura-open">別のタブで開く</button><button class="sub" id="ura-inline">ここで読む</button></div><div id="ura-frame"></div></div>
  <div class="ura-sec"><h3>友達に共有</h3><p>紙面をそのまま画像(${(d.pages || []).length}枚)かPDFで送れます。LINEなどの共有画面が開きます。リンクで送ることもできます。</p>
    <div class="ura-btns">${(d.pages || []).length ? `<button id="ura-share-img">画像で共有</button>` : ""}${d.pdf ? `<button id="ura-share-pdf">PDFで共有</button>` : ""}
      <button class="sub" id="ura-share">リンクで共有</button><button class="sub" id="ura-share-copy">リンクをコピー</button></div><p class="ura-note" id="ura-share-url"></p></div>
  <div class="ura-sec"><h3>note の本文</h3><p>無料と有料の切れ目の線が入っています。タイトル案は冒頭。</p>
    <div class="ura-btns"><button id="ura-copy-note">本文をコピー</button></div></div>
  <div class="ura-sec"><h3>出したら記録</h3><p>出した日と URL を履歴に残します(GitHub の画面が開くので「Submit」を押すだけ)。${(d.pub || []).length ? "記録ずみ: " + esc(pubText(d.pub).replace(" ・ 出した: ", "")) : "まだ出していません。"}</p>
    <div class="ura-btns">${d.grade === "X" ? "" : `<a class="btn-link" href="${pubIssueURL(key, "note")}" target="_blank" rel="noopener">note に出した</a>`}${d.grade === "X" ? "" : `<a class="btn-link sub" href="${pubIssueURL(key, "X")}" target="_blank" rel="noopener">X に出した</a>`}</div></div>
  <div class="ura-sec"><h3>X の投稿案</h3>${posts.map((p) => {
    const slot = (p.warn.match(/^(\d{1,2}:\d{2})/) || [])[1];
    const done = (d.pub || []).some((x) => x.channel === "X" && (!slot || x.slot === slot));
    return `<div class="ura-post"><div class="n"><span>投稿${p.n}(${p.len}字)${p.warn ? " " + esc(p.warn) : ""}${done ? " ・ 出した" : ""}</span><button data-copy="${p.n}">コピー</button>${d.grade === "X" && slot && !done ? `<a class="btn-link sub" href="${pubIssueURL(key, "X", slot)}" target="_blank" rel="noopener">出した</a>` : ""}</div>${esc(p.body)}</div>`;
  }).join("")}
    ${tail ? `<p class="ura-note" style="margin-top:8px;white-space:pre-wrap">${esc(tail)}</p>` : ""}</div>
  <div class="ura-sec"><h3>${d.grade === "X" ? "画像" : "選手カードの画像"}(${d.images.length}枚)</h3><p>${d.grade === "X" ? "長押しかタップで保存して、同じ番号の投稿に添付。" : "長押しかタップで保存。投稿1に注目1人目、投稿2に相性のいい選手。出場全員ぶんは「推し名簿」用。"}</p>
    <div class="ura-btns"><button class="sub" id="ura-imgs-load">${d.grade === "X" ? "画像を表示" : "早見表と注目選手"}(${d.images.filter((x) => !x.extra).length}枚)</button>${d.images.some((x) => x.extra) ? `<button class="sub" id="ura-imgs-all">出場全員(${d.images.filter((x) => x.extra).length}枚)</button>` : ""}</div><div class="ura-imgs" id="ura-imgs"></div></div>`;
  box.innerHTML = html;
  $("#ura-back").onclick = () => { URA.open = null; renderUra(); };
  $("#ura-open").onclick = () => {
    const url = URL.createObjectURL(new Blob(["\ufeff", d.html], { type: "text/html;charset=utf-8" }));
    window.open(url, "_blank");
  };
  $("#ura-inline").onclick = (e) => {
    const f = $("#ura-frame");
    f.innerHTML = f.innerHTML ? "" : `<iframe class="ura-frame" sandbox="allow-same-origin" srcdoc="${esc(d.html)}"></iframe>`;
    e.target.textContent = f.innerHTML ? "閉じる" : "ここで読む";
  };
  $("#ura-copy-note").onclick = (e) => copyText(d.note, e.target);
  const shareURL = async () => {
    const raw = await crypto.subtle.exportKey("raw", KEY);
    const k = await crypto.subtle.importKey("raw", raw, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
    const sig = new Uint8Array(await crypto.subtle.sign("HMAC", k, new TextEncoder().encode("share:" + key)));
    const tok = [...sig].map((b) => b.toString(16).padStart(2, "0")).join("").slice(0, 20);
    return `${location.origin}/s/${key}/${tok}`;
  };
  $("#ura-share").onclick = async (e) => {
    const url = await shareURL();
    $("#ura-share-url").textContent = url;
    if (navigator.share) { try { await navigator.share({ title: d.title, text: `ミカタ新聞 ${d.title}`, url }); } catch (err) { } }
    else copyText(url, e.target);
  };
  $("#ura-share-copy").onclick = async (e) => { const url = await shareURL(); $("#ura-share-url").textContent = url; copyText(url, e.target); };
  const shareFiles = async (btn, list, mime, field) => {
    const t = btn.textContent; btn.disabled = true; btn.textContent = "準備中…";
    try {
      const files = [];
      for (const f of list) {
        const x = await getJSON(`api/data/ura/${f.file}`);
        const bin = Uint8Array.from(atob(x[field]), (c) => c.charCodeAt(0));
        files.push(new File([bin], x.name, { type: mime }));
      }
      if (navigator.share && navigator.canShare && navigator.canShare({ files })) await navigator.share({ title: d.title, files });
      else {
        // 共有画面が使えない端末では、1枚ずつ保存
        for (const f of files) { const a = document.createElement("a"); a.href = URL.createObjectURL(f); a.download = f.name; a.click(); }
      }
    } catch (err) { if (!/abort/i.test(String(err))) alert("共有できませんでした: " + err); }
    btn.disabled = false; btn.textContent = t;
  };
  if ($("#ura-share-img")) $("#ura-share-img").onclick = (e) => shareFiles(e.target, d.pages, "image/png", "png");
  if ($("#ura-share-pdf")) $("#ura-share-pdf").onclick = (e) => shareFiles(e.target, [{ file: d.pdf }], "application/pdf", "pdf");
  $$("[data-copy]", box).forEach((b) => b.onclick = () => copyText(posts.find((p) => p.n === b.dataset.copy).body, b));
  const loadImgs = async (e, list) => {
    e.target.disabled = true;
    const wrap = $("#ura-imgs");
    for (const im of list) {
      try {
        const x = await getJSON(`api/data/ura/${im.file}`);
        const src = "data:image/png;base64," + x.png;
        wrap.insertAdjacentHTML("beforeend", `<figure><img src="${src}" alt="${esc(x.name)}"><figcaption><span>${esc(x.name.replace(/^\d+_|\.png$/g, ""))}</span><a href="${src}" download="${esc(x.name)}">保存</a></figcaption></figure>`);
      } catch (err) { wrap.insertAdjacentHTML("beforeend", `<p class="ura-note">${esc(im.name)} は読めませんでした</p>`); }
    }
    e.target.hidden = true;
  };
  $("#ura-imgs-load").onclick = (e) => loadImgs(e, d.images.filter((x) => !x.extra));
  if ($("#ura-imgs-all")) $("#ura-imgs-all").onclick = (e) => loadImgs(e, d.images.filter((x) => x.extra));
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
  if (state.tab === "ura") renderUra();
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
  if (!state.data || state.day !== jst().date || state.tab === "track" || state.tab === "ura") return;
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
    $("#venues").hidden = state.tab === "track" || state.tab === "ura";
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
