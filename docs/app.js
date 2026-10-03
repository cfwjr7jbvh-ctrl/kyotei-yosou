"use strict";
const $ = (s, el = document) => el.querySelector(s);
const pct = (p, d = 1) => (p * 100).toFixed(d) + "%";
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const state = { day: null, data: null, venue: "all" };

async function getJSON(path) {
  const r = await fetch(path + "?t=" + Date.now());
  if (!r.ok) throw new Error(path);
  return r.json();
}

function boatRow(b, maxP) {
  const meta = [b.class, b.age ? b.age + "歳" : "", b.branch,
    b.nat_win_rate != null ? "勝率" + Number(b.nat_win_rate).toFixed(2) : "",
    b.motor_2rate != null ? "機" + Number(b.motor_2rate).toFixed(0) + "%" : "",
    b.exhibit_time != null ? "展示" + Number(b.exhibit_time).toFixed(2) : "",
    b.course != null && b.course !== b.lane ? b.course + "コース" : ""].filter(Boolean).join(" ・ ");
  return `<li class="boat">
    <span class="lane l${b.lane}">${b.lane}</span>
    <div class="who"><div class="n">${esc(b.name)}</div><div class="d">${esc(meta)}</div>
      <div class="bar"><i style="width:${Math.max(2, (b.p_win / maxP) * 100)}%"></i></div></div>
    <div class="pw">${pct(b.p_win)}<small>1着率</small></div></li>`;
}

function raceCard(r) {
  const el = $("#race-tpl").content.firstElementChild.cloneNode(true);
  $(".v", el).textContent = r.venue;
  $(".r", el).textContent = r.rno + "R";
  $(".type", el).textContent = r.race_type || "";
  const badge = $(".badge", el);
  badge.textContent = r.stage === "late" ? "直前 " + r.updated_at : "朝予想";
  if (r.stage === "late") badge.classList.add("late");
  $("time", el).textContent = r.deadline ? "締切 " + r.deadline : "";
  const maxP = Math.max(...r.boats.map((b) => b.p_win));
  $(".boats", el).innerHTML = r.boats.map((b) => boatRow(b, maxP)).join("");
  const res = r.result;
  let html = "";
  if (r.bets && r.bets.length) {
    html += `<h4>期待値のある買い目(3連単)</h4>` + r.bets.map((b) => `
      <div class="bet${b.hit ? " hit" : ""}"><span class="c">${b.combo}</span>
        <span class="meta">確率 ${pct(b.prob)} ・ オッズ ${b.odds}倍</span>
        <span class="ev">${b.ev.toFixed(2)}<small>期待値</small></span></div>`).join("");
  }
  html += `<h4>予想上位(3連単)</h4><div class="chips">` + r.top.slice(0, 6).map((t) =>
    `<span class="chip${res && res.tri_combo === t.combo ? " hit" : ""}"><span class="c">${t.combo}</span>
     <span class="p">${pct(t.prob)}${t.odds ? " ・" + t.odds + "倍" : ""}</span></span>`).join("") + `</div>`;
  if (res) html += `<div class="result">結果 <b>${res.tri_combo}</b> ・ 払戻 <b>${res.tri_pay.toLocaleString()}円</b></div>`;
  $(".picks", el).innerHTML = html;
  return el;
}

function renderEV() {
  const box = $("#tab-ev");
  const races = state.data.races;
  const withBets = races.filter((r) => r.bets && r.bets.length);
  const lateN = races.filter((r) => r.stage === "late").length;
  box.innerHTML = `<p class="note">締切30分前ごろに展示タイム・進入・オッズを取り込み、確率×オッズ(期待値)が1.2以上の組を表示します。直前更新済み ${lateN} / ${races.length} レース</p>`;
  if (!withBets.length) {
    box.insertAdjacentHTML("beforeend", `<div class="empty">今のところ期待値の高い買い目はありません。<br>締切が近づくと自動で更新されます。</div>`);
    return;
  }
  withBets.forEach((r) => box.appendChild(raceCard(r)));
}

function renderAll() {
  const vs = [...new Set(state.data.races.map((r) => r.venue))];
  $("#venues").innerHTML = ["all", ...vs].map((v) =>
    `<button data-v="${esc(v)}" aria-pressed="${state.venue === v}">${v === "all" ? "すべて" : esc(v)}</button>`).join("");
  const list = $("#all-list");
  list.innerHTML = "";
  state.data.races.filter((r) => state.venue === "all" || r.venue === state.venue)
    .forEach((r) => list.appendChild(raceCard(r)));
}

function stat(k, v, cls = "") { return `<div class="stat"><div class="k">${k}</div><div class="v ${cls}">${v}</div></div>`; }

async function renderTrack() {
  const box = $("#tab-track");
  let track = { days: [] }, rep = null;
  try { track = await getJSON("data/track.json"); } catch (e) { }
  try { rep = await getJSON("data/report.json"); } catch (e) { }
  const t = track.days.reduce((a, d) => {
    for (const k of ["races", "top1_hit", "bets", "bet_hits", "invest", "return"]) a[k] = (a[k] || 0) + d[k];
    return a;
  }, {});
  let html = `<div class="box"><h3>実際の成績(公開後の予想)</h3>`;
  if (t.races) {
    const roi = t.invest ? t.return / t.invest : 0;
    html += `<p>${track.days[0].date} 〜 ${track.days[track.days.length - 1].date}(${track.days.length}日)</p>
      <div class="stats">${stat("期待値買いの回収率", t.invest ? pct(roi) : "-", roi >= 1 ? "good" : "bad")}
      ${stat("収支(1点100円)", (t.return - t.invest).toLocaleString() + "円")}
      ${stat("買い目の的中率", t.bets ? pct(t.bet_hits / t.bets) : "-")}
      ${stat("本命3連単の的中率", pct(t.top1_hit / t.races))}</div>`;
  } else html += `<p>予想の公開後、翌朝から集計されます。</p>`;
  html += `</div>`;
  if (rep) {
    const st = rep.stages.late || rep.stages.early;
    const names = { baseline_lane: "枠番だけ(基準)", gbdt_win: "勾配ブースティング(1着)", gbdt_place: "勾配ブースティング(3着内)",
      rank: "ランキング学習", pl_logit: "条件付きロジット", rating: "レーティング", ensemble: "アンサンブル" };
    const rows = Object.entries(st.metrics).map(([k, m]) => `<tr class="${k === "ensemble" ? "best" : ""}">
      <td>${names[k] || k}</td><td>${m.win_logloss.toFixed(3)}</td><td>${pct(m.win_hit)}</td>
      <td>${pct(m.tri_hit_top1)}</td><td>${pct(m.tri_hit_top5)}</td></tr>`).join("");
    html += `<div class="box"><h3>モデル比較(過去データでの検証)</h3>
      <p>テスト期間 ${rep.period.test[0]} 〜 ${rep.period.test[1]}。誤差(小さいほど良い)と的中率。</p>
      <div class="scroll"><table class="tbl"><thead><tr><th>モデル</th><th>誤差</th><th>1着</th><th>3連単本命</th><th>3連単上位5</th></tr></thead>
      <tbody>${rows}</tbody></table></div></div>`;
    if (rep.ev) {
      const e = rep.ev;
      const evRows = e.ev_blend.map((r, i) => `<tr><td>${r.ev_min.toFixed(1)}以上</td><td>${r.bets}</td>
        <td>${r.hit_rate != null ? pct(r.hit_rate) : "-"}</td><td>${r.roi != null ? pct(r.roi) : "-"}</td>
        <td>${e.ev_model[i].roi != null ? pct(e.ev_model[i].roi) : "-"}</td></tr>`).join("");
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

async function loadDay(day) {
  state.day = day;
  try {
    state.data = await getJSON(`data/days/${day}.json`);
  } catch (e) {
    state.data = { races: [] };
  }
  $("#updated").textContent = `${day} ・ ${state.data.races.length}レース` + (state.data.updated_at ? ` ・ ${state.data.updated_at}更新` : "");
  renderEV();
  renderAll();
}

async function init() {
  let idx = { days: [] };
  try { idx = await getJSON("data/index.json"); } catch (e) { }
  const sel = $("#day");
  sel.innerHTML = idx.days.slice().reverse().map((d) => `<option value="${d}">${d.slice(5).replace("-", "/")}</option>`).join("");
  sel.onchange = () => loadDay(sel.value);
  document.querySelectorAll(".tabs button").forEach((b) => b.onclick = () => {
    document.querySelectorAll(".tabs button").forEach((x) => x.setAttribute("aria-selected", x === b));
    document.querySelectorAll(".panel").forEach((p) => p.hidden = p.id !== "tab-" + b.dataset.tab);
    if (b.dataset.tab === "track") renderTrack();
  });
  $("#venues").onclick = (e) => {
    const v = e.target.closest("button");
    if (v) { state.venue = v.dataset.v; renderAll(); }
  };
  if (idx.latest) await loadDay(idx.latest);
  else { $("#updated").textContent = "予想データの準備中です"; $("#tab-ev").innerHTML = `<div class="empty">最初の予想は、過去データの学習が終わり次第ここに表示されます。</div>`; }
  setInterval(() => { if (state.day === idx.latest) loadDay(state.day); }, 5 * 60 * 1000);
}
init();
