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
  if (t.local != null && t.top3 != null && t.local - t.top3 >= 0.072) add("当地◎", "plus");
  if (t.f != null && t.f >= 1) add("F持ち", "minus");
  if (t.rough != null && t.top3 != null && t.rough - t.top3 >= 0.056) add("荒れ水面◎", "plus");
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
      <div class="who"><b>${esc(b.name)}</b><div class="meta">${meta}</div>${traitChips(r, b)}</div>
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

// ---- 1マークの展開アニメ ----
// 勝ち筋(展開シナリオ)ごとに「スリット隊形 → 1マークの回り方 → 着順」を動かして見せる。
// スリットの並びは予想ST(直前は展示ST込み)、進入は直前なら展示の進入。1マークの回り方は決まり手ごとの典型の形で、
// 実際の航跡のデータではない。着順はそのシナリオの本線(この艇が勝つなら、いちばんありそうな3連単)。
const AN = { slitX: 150, mx: 292, my: 92, y: (c) => 128 + (c - 1) * 16, endX: [50, 84, 114, 142, 167, 190],
  T: [0, 1.4, 2.3, 3.3, 4.2, 5.8], hold: 1.6 };
const anReduce = () => window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
function animHTML(r) {
  const sc = (r.tenkai && r.tenkai.scenarios) || [];
  if (!sc.length || !r.boats || r.boats.length < 6) return "";
  const chips = sc.map((x, i) => `<button type="button" class="an-chip" data-i="${i}" aria-pressed="${i === 0}">${tile(x.lane)}<span>${esc(x.type || "1着")}</span><b>${Math.round(x.p_win * 100)}%</b></button>`).join("");
  return `<div class="anim" data-id="${r.race_id}">
    <h4>1マークの展開<small>勝ち筋を選ぶと動きます</small></h4>
    <div class="an-chips">${chips}</div>
    <div class="an-stage"><svg viewBox="0 0 360 232" role="img" aria-label="スタートから1マークまでの展開のアニメーション">
      <rect class="an-water" x="0" y="0" width="360" height="232" rx="10"/>
      <line class="an-slit" x1="${AN.slitX}" y1="112" x2="${AN.slitX}" y2="226"/>
      <text class="an-lbl" x="${AN.slitX + 4}" y="229">スタートライン</text>
      <circle class="an-mark2" cx="24" cy="${AN.my}" r="4"/><text class="an-lbl" x="32" y="${AN.my + 4}">2マーク</text>
      <circle class="an-mark" cx="${AN.mx}" cy="${AN.my}" r="5"/><text class="an-lbl" x="${AN.mx - 9}" y="${AN.my + 4}" text-anchor="end">1マーク</text>
      <text class="an-phase" x="12" y="24"></text>
      <g class="an-trails"></g><g class="an-boats"></g></svg>
      <button type="button" class="an-re" aria-label="もう一度再生">↻ もう一度</button></div>
    <p class="an-cap"></p>
    <p class="an-note">動きは決まり手ごとの典型の形です。スリットの並びは予想ST、着順はその勝ち筋の本線。</p></div>`;
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

// シナリオから各艇の動き(スリットの位置、ターンの半径、ターンの早さ、最後の順位)を決める
function anModel(r, x) {
  const st = Object.fromEntries(slitRows(r).map((s) => [s.b.lane, s]));
  const sts = Object.values(st).map((s) => s.st);
  const ref = sts.length ? sts.reduce((a, b) => a + b, 0) / sts.length : 0;
  const boats = r.boats.map((b) => ({ lane: b.lane, c: courseOf(r, b), p: b.p_win, s: st[b.lane] }));
  const byC = Object.fromEntries(boats.map((b) => [b.c, b]));
  const combo = (x.best && x.best.combo || "").split("-").map(Number);
  const order = [x.lane, combo[1], combo[2]].filter((v, i, a) => v && a.indexOf(v) === i);
  boats.slice().sort((a, b) => b.p - a.p).forEach((b) => { if (!order.includes(b.lane)) order.push(b.lane); });
  const A = boats.find((b) => b.lane === x.lane), ca = A.c, type = x.type || (ca === 1 ? "逃げ" : "差し");
  for (const b of boats) {
    b.lead = b.s ? Math.max(-26, Math.min(26, (ref - b.s.st) * 240)) : 0;
    b.r = 18 + (b.c - 1) * 7; b.ex = 1; b.d = (b.c - 1) * 0.09; b.cx = AN.mx - 50;
    b.rank = order.indexOf(b.lane);
  }
  const in1 = byC[1];
  if (type === "逃げ" || ca === 1) {
    A.r = 16; A.d = -0.08;
    const B = boats.find((b) => b.lane === order[1]);
    if (B && B.c === 2) { B.r = 12; B.d = 0.14; } else if (B) { B.r = 21; B.d = 0.1; }
  } else if (type === "まくり") {
    A.lead += 14; A.r = 22; A.d = -0.3; A.cx = AN.mx - 95;
    for (const b of boats) if (b.c < ca) { b.r = 30 + b.c * 6; b.ex = 1.25; b.d = 0.12 + b.c * 0.04; }
    const F = byC[ca + 1];
    if (F) { F.r = 32; F.d = 0; }
  } else if (type === "まくり差し") {
    A.lead += 6; A.r = 13; A.d = 0.1; A.cx = AN.mx - 70;
    if (in1 && in1 !== A) { in1.r = 24; in1.ex = 1.2; in1.d = -0.05; }
    for (const b of boats) if (b.c > 1 && b.c < ca) { b.r = 32 + b.c * 4; b.ex = 1.15; b.d = 0.04; }
  } else {  // 差し(抜き・恵まれなどもこの形で見せる)
    if (in1 && in1 !== A) { in1.r = 26; in1.ex = 1.2; in1.d = 0; }
    A.r = 11; A.d = 0.12;
  }
  for (const b of boats) {
    const y0 = AN.y(b.c), dash = b.c >= 4;
    const p0 = [AN.slitX - (dash ? 120 : 62) + b.lead, y0], p1 = [AN.slitX + b.lead, y0], p2 = [AN.slitX + b.lead + 10, y0];
    const e = [AN.mx, AN.my + b.r], xo = [AN.mx, AN.my - b.r];
    const arc = Array.from({ length: 31 }, (_, k) => {
      const th = Math.PI / 2 - (Math.PI * k) / 30;
      return [AN.mx + b.r * b.ex * Math.cos(th), AN.my + b.r * Math.sin(th)];
    });
    const fin = [AN.endX[b.rank], AN.my - 16 - Math.min(b.r, 50) * 0.55 + (b.rank % 2) * 5];
    b.path = anPath([[p0, p1], [p1, p2], qb(p2, [b.cx, e[1]], e), arc, qb(xo, [AN.mx - 70, xo[1]], fin)]);
  }
  const lines = {
    "逃げ": `${x.lane}号艇が先にターンして逃げる`,
    "差し": `${in1 && in1 !== A ? in1.lane + "号艇のターンが膨らんだ内を、" : ""}${x.lane}号艇が差す`,
    "まくり": `${x.lane}号艇がスリットで先手、内の艇の外から一気にまくる`,
    "まくり差し": `${x.lane}号艇が内の艇の間を割って、1マークで差し込む`,
  };
  const slit = slitRows(r).filter((s) => s.atk || s.dent).map((s) => `${s.b.lane}号艇${s.atk ? "が攻め" : "が凹み"}`).join("・");
  return { boats, type, cap: [`スタート: ${slit ? slit + "の隊形" : "予想STの隊形"}`, `1マーク: ${lines[type] || lines["差し"]}`,
    `決着: ${order.slice(0, 3).join("-")}(この展開の中で${Math.round((x.best.p_cond || 0) * 100)}%)`] };
}

function anDraw(el, m, t) {
  const T = AN.T, svg = el.querySelector("svg");
  const tr = svg.querySelector(".an-trails"), bg = svg.querySelector(".an-boats");
  if (!tr.childElementCount) {
    tr.innerHTML = m.boats.map((b) => `<polyline class="an-tr l${b.lane}" points=""/>`).join("");
    bg.innerHTML = m.boats.map((b) => `<g class="an-bt l${b.lane}"><circle r="8.5"/><text y="4.2" text-anchor="middle">${b.lane}</text><text class="an-flag" y="-12" text-anchor="middle"></text></g>`).join("");
  }
  const phase = t < T[2] ? 0 : t < T[4] ? 1 : 2;
  svg.querySelector(".an-phase").textContent = ["スタート", "1マーク", "決着"][phase];
  const cap = el.querySelector(".an-cap");
  if (cap.dataset.p !== String(phase)) { cap.dataset.p = phase; cap.textContent = m.cap[phase]; }
  m.boats.forEach((b, i) => {
    const P = b.path, ks = [[T[0], 0], [T[1], P.at[0]], [T[2], P.at[1]], [T[3] + b.d, P.at[2]], [T[4] + b.d, P.at[3]], [T[5], P.at[4]]];
    let s = P.at[4];
    for (let k = 1; k < ks.length; k++) if (t <= ks[k][0]) { const f = (t - ks[k - 1][0]) / (ks[k][0] - ks[k - 1][0]); s = ks[k - 1][1] + Math.max(0, f) * (ks[k][1] - ks[k - 1][1]); break; }
    const p = anPos(P, s);
    tr.children[i].setAttribute("points", P.pts.slice(0, p.i + 1).concat([[p.x, p.y]]).map((q) => q[0].toFixed(1) + "," + q[1].toFixed(1)).join(" "));
    const g = bg.children[i];
    g.setAttribute("transform", `translate(${p.x.toFixed(1)},${p.y.toFixed(1)})`);
    const flag = t >= T[1] - 0.2 && t < T[3] && b.s ? (b.s.atk ? "攻め" : b.s.dent ? "凹み" : "") : t >= T[5] && b.rank < 3 ? `${b.rank + 1}着` : "";
    const fe = g.querySelector(".an-flag");
    if (fe.textContent !== flag) {
      const fin = t >= T[5];  // スリットでは艇の右、決着では艇の上に出す
      fe.textContent = flag;
      fe.setAttribute("class", "an-flag" + (!fin && b.s && b.s.atk ? " atk" : fin ? " fin" : ""));
      fe.setAttribute("x", fin ? 0 : 12); fe.setAttribute("y", fin ? -12 : 3.5); fe.setAttribute("text-anchor", fin ? "middle" : "start");
    }
  });
}

function anPlay(el, i) {
  const r = state.data && state.data.races.find((x) => x.race_id === el.dataset.id);
  const x = r && r.tenkai && r.tenkai.scenarios && r.tenkai.scenarios[i];
  if (!x) return;
  el.querySelectorAll(".an-chip").forEach((c) => c.setAttribute("aria-pressed", c.dataset.i === String(i)));
  const m = anModel(r, x);
  el.querySelector(".an-trails").innerHTML = "";
  if (el._raf) cancelAnimationFrame(el._raf);
  el._i = i;
  state.anSel[el.dataset.id] = i;
  state.anSeen.add(el.dataset.id);
  const end = AN.T[5] + 0.01;
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
    if (r) anDraw(el, anModel(r, r.tenkai.scenarios[i]), AN.T[5] + 0.01);  // まず決着の形を出しておく
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

function stageHTML(r) {
  return r.stage === "late"
    ? `<div class="stage late">展示を反映した直前予想(${esc(r.updated_at)})</div>`
    : `<div class="stage">朝の予想(展示前)</div>`;
}

// 見る順: AIのひと言 → 荒れ度 → 結果 → 本命 → 期待値の買い目 → AIの狙い目 → 展開予測(アニメ・シナリオ・スリット) → 各艇 → ほかの候補 → 公式サイト
const bodyHTML = (r) => stageHTML(r) + aiLine(r) + arashiHTML(r) + resultHTML(r) + honmeiHTML(r) + evHTML(r) + pickHTML(r) + tenkaiHTML(r) + boatsHTML(r) + combosHTML(r) + officialHTML(r);

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
      <span class="vr"><b>${esc(r.venue)}</b><span class="n">${r.rno}R</span>${r.stage === "late" ? `<span class="late" title="直前予想"></span>` : ""}${!r.result && arashiLevel(r) >= 5 ? `<span class="are">荒れ</span>` : ""}</span>
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
  setupAnims(box);
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
    <p class="note dm-note">注意: 回収率100%超えの出目があっても、たまたまの可能性が高いです。約${(sc.n_tests || 0).toLocaleString()}通り(出目×条件)を総当たりした検証では、前半2年で100〜120%だった買い方の後半1年の平均は${band ? Math.round(band.conf_mean * 100) : "-"}%、信頼区間の下限まで100%を超えたものは${sc.passed ?? 0}件でした。</p>
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
  renderDeme();
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
