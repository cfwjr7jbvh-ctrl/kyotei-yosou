// 返信用の小さなカード(2026-10-08 ユーザー「返信には画像ダメなんだっけ?」「作ったほうがいいかな?」)。
// アプリの「ひと言リプの下書き」の横に、レースごとの数字1つを大きく描いた 1080×1080 の画像を出す(長押しで保存して返信に添付)。
// 宣伝っぽく見えないように @ は入れず、ミカタの顔を小さく。同じ画像を使い回さないよう、レース名・締切・理論ごとに中身が変わる。
const RC_GULL = "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 300 300\" width=\"160\" height=\"160\" role=\"img\" aria-label=\"\u30ab\u30e2\u30e1\u306e\u8a18\u8005\u30df\u30ab\u30bf\"><defs><clipPath id=\"g160gullm\"><circle cx=\"150\" cy=\"150\" r=\"121\"/></clipPath></defs><circle cx=\"150\" cy=\"150\" r=\"150\" fill=\"#ffffff\"/><g clip-path=\"url(#g160gullm)\"><g transform=\"translate(136 182) scale(1.45) translate(-188 -98)\"><path d=\"M 58 200 L 90 182 C 102 152 125 139 146 133 C 134 110 140 70 176 58 C 206 48 229 72 227 100 C 226 118 219 130 213 138 C 241 160 246 205 221 232 C 196 258 141 262 111 245 C 99 238 93 229 89 221 Z\" fill=\"#ffffff\" stroke=\"#14212c\" stroke-width=\"5\" stroke-linejoin=\"round\"/><path d=\"M 105 170 C 130 150 185 155 207 186 C 217 206 202 228 172 232 C 142 236 110 225 92 212 Z\" fill=\"#a9b4bb\" stroke=\"#14212c\" stroke-width=\"5\" stroke-linejoin=\"round\"/><path d=\"M 223 92 C 242 91 259 95 271 102 C 266 108 257 108 249 106 L 223 108 Z\" fill=\"#f2c230\" stroke=\"#14212c\" stroke-width=\"4\" stroke-linejoin=\"round\"/><path d=\"M 223 108 L 250 107 C 256 111 254 118 246 118 C 236 117 229 115 223 114 Z\" fill=\"#f2c230\" stroke=\"#14212c\" stroke-width=\"4\" stroke-linejoin=\"round\"/><circle cx=\"246.5\" cy=\"112\" r=\"3.6\" fill=\"#c8141c\"/><path d=\"M 224 109.5 Q 220.6 109.2 218.9 106.3\" stroke=\"#14212c\" stroke-width=\"2.6\" stroke-linecap=\"round\" fill=\"none\"/><circle cx=\"199\" cy=\"90\" r=\"5.8\" fill=\"#14212c\"/><path d=\"M 192.4 87.6 A 6.6 6.6 0 0 1 205.6 87.6 Q 199 85.2 192.4 87.6 Z\" fill=\"#ffffff\"/><path d=\"M 192.2 87.8 Q 199 85.2 205.8 87.8\" stroke=\"#14212c\" stroke-width=\"3\" stroke-linecap=\"round\" fill=\"none\"/></g></g><circle cx=\"150\" cy=\"150\" r=\"128\" fill=\"none\" stroke=\"#c8141c\" stroke-width=\"13\"/></svg>";
const RC_LANE_BG = ["#ffffff", "#17191c", "#e3141b", "#0b5fb4", "#f5d00a", "#12904a"], RC_LANE_FG = ["#111111", "#ffffff", "#ffffff", "#ffffff", "#111111", "#ffffff"];
const RC_F = "'Hiragino Sans','Hiragino Kaku Gothic ProN','Noto Sans CJK JP','Noto Sans JP',sans-serif";

function rcWhat(what) {   // 「1号艇の1着」→「1号艇が勝つ割合」(主語を書く)
  let m = /^(.+?)の1着$/.exec(what || "");
  if (m) return `${m[1]}が勝つ割合`;
  m = /^(.+?)の3着以内$/.exec(what || "");
  if (m) return `${m[1]}が3着以内に入る割合`;
  return `${what}の割合`;
}
// 「だから何?」の1行(2026-10-08 ユーザー「狙い目じゃ無いけど、みんなが気づいていない貴重な情報かもしれない感を出したほうが価値上がる」)。
// 検証ラボの「人気とのくらべ」(edge)から。買い目は書かない
function rcPoint(n) {   // 2行([1行目, 2行目])。行の切れ目を言葉の切れ目にそろえる
  const up = n.b >= n.a, one = /^(\d号艇|1コースの艇)/.exec(n.what || "");
  const who = one ? one[1] : "この艇";
  if (n.edge === 1) return up ? ["人気以上に来ている形。", "この数字は、まだあまり知られていないかも"] : ["下がるとみんな思いすぎ。", `${who}は人気ほどは崩れていない`];
  if (n.edge === -1) return up ? ["強いのは本当。でも人気が集まりすぎて、", "そのぶん来ていない"] : [`${who}は人気のわりにひかえめ。`, "人気が集まりすぎていないか見ておきたい"];
  if (n.edge === 0) return ["人気にもちゃんと出ている差。", "ここから差がつくのは、2着・3着の並び"];
  return up ? ["出走表だけでは見えない数字。", "3着までの相手を選ぶときに"] : ["出走表だけでは見えない数字。", "相手を選び直す材料に"];
}
// 「妙味のヒント」(2026-10-08 ユーザー「どこに妙味があるか知りたいのよみんなは」「個人の予想を楽しくするってコンセプトとシナジーが出る形で」)。
// 答えを渡すのではなく、ずれている場所を指して、最後は読む人が決める(ミカタは予想を押しつけない。決めるのはキミ)。
// 1) このレースで、ミカタの見立てが人気(締切前のオッズ)より大きい艇(展示速報と同じ線)
// 2) 無ければ、理論の「人気とのくらべ」(人気以上・ひかえめ)
// 3) どちらも無ければ、人気どおり → 差がつくのは2着・3着の並び。買い目は書かない
function rcAnswer(o) {
  const m = o.myomi, n = o.num;
  const up = n.b >= n.a, one = /^(\d号艇|1コースの艇)/.exec(n.what || ""), who = one ? one[1] : "この艇";
  if (m && m.lane) return { hl: true, at: m.at, lines: [`${m.lane}号艇が、人気より上`, `ミカタの見立て${Math.round(m.p * 100)}%・人気${Math.round(m.m * 100)}%(人気の${(m.p / m.m).toFixed(1)}倍)`, "頭で狙う? 2・3着に置く? 決めるのはキミ"] };
  if (n.edge === -1) return { hl: true, lines: up ? ["強いのは本当。でも人気が集まりすぎ", "そのぶん、人気ほどは来ていない", "信じて買う? あえて外す? 決めるのはキミ"]
    : [`${who}は、人気のわりにひかえめ`, "人気が集まりすぎていないか見ておきたい", `${who}を信じる? 外から崩す? 決めるのはキミ`] };
  if (n.edge === 1) return { hl: true, lines: up ? ["人気以上に来ている形", "この数字は、まだあまり知られていないかも", "乗ってみる? 決めるのはキミ"]
    : ["下がるとみんな思いすぎ", `${who}は、人気ほどは崩れていない`, "見限る? 残す? 決めるのはキミ"] };
  if (m) return { hl: false, at: m.at, lines: ["人気とミカタの見立てが、ほぼ同じ", "差がつくのは、2着・3着の並び", "キミの並びは?"] };
  return { hl: false, lines: ["出走表だけでは見えない数字", up ? "3着までの相手に入れる? 決めるのはキミ" : "相手を選び直す? 決めるのはキミ"] };
}
function rcPct(v) { return v < 10 ? `${v.toFixed(1)}%` : `${Math.round(v)}%`; }
function rcWrap(ctx, text, maxW) {
  const out = []; let line = "";
  for (const ch of text) {
    if (ctx.measureText(line + ch).width > maxW && line) {
      if ("、。)」』%".includes(ch)) { line += ch; continue; }   // 句読点を行頭にしない
      out.push(line); line = ch;
    } else line += ch;
  }
  if (line) out.push(line);
  return out;
}

// o: {race:"桐生12R", deadline:"20:45", title:"今節2連勝中", lanes:[1], num:{what, ref, a, b}}
// t: 0〜1(棒が伸びる進み具合。1 で最後の形)。gull: 先に読み込んだミカタの顔
function drawReplyCard(x, o, t, gull) {
  const W = 1080, H = 1080;
  const n = o.num, up = n.b >= n.a, col = up ? "#c8141c" : "#0b5fb4";
  const e = (u) => 1 - Math.pow(1 - Math.min(1, Math.max(0, u)), 3);
  x.textAlign = "left"; x.textBaseline = "alphabetic";
  x.fillStyle = "#f4efdf"; x.fillRect(0, 0, W, H);
  x.fillStyle = "#17191c"; x.fillRect(0, 0, W, 220);
  x.fillStyle = "#ffe100"; x.font = `900 34px ${RC_F}`;
  x.fillText("ミカタ検証ラボ ・ 数えてみた", 60, 76);
  x.fillStyle = "#ffffff"; x.font = `900 96px ${RC_F}`; x.fillText(o.race, 60, 180);
  const rw = x.measureText(o.race).width;
  if (o.deadline) { x.fillStyle = "#d9dde0"; x.font = `700 40px ${RC_F}`; x.fillText(`締切 ${o.deadline}`, 60 + rw + 30, 176); }
  RC_LANE_BG.forEach((b, i) => { x.fillStyle = b; x.fillRect(i * (W / 6) + 2, 224, W / 6 - 4, 12); });
  let y = 320;
  x.font = `900 64px ${RC_F}`; x.fillStyle = "#14212c";
  const tw = Math.min(x.measureText(o.title).width, 760);
  x.fillText(o.title, 60, y, 760);
  let lx = 60 + tw + 24;
  for (const l of (o.lanes || []).slice(0, 2)) {
    x.fillStyle = RC_LANE_BG[l - 1]; x.fillRect(lx, y - 56, 64, 68);
    x.strokeStyle = "#111111"; x.lineWidth = 4; x.strokeRect(lx, y - 56, 64, 68);
    x.fillStyle = RC_LANE_FG[l - 1]; x.font = `900 48px ${RC_F}`; x.textAlign = "center"; x.fillText(String(l), lx + 32, y + 2); x.textAlign = "left";
    lx += 80;
  }
  x.font = `700 42px ${RC_F}`; x.fillStyle = "#4d5a66";
  for (const ln of rcWrap(x, `${o.title}のとき、${rcWhat(n.what)}は?`, W - 120).slice(0, 2)) { y += 64; x.fillText(ln, 60, y); }
  // 2本の棒(くらべる相手 → この条件)。1本目が先に、2本目が少し遅れて伸び、最後に差の旗
  const lo = Math.max(0, Math.floor((Math.min(n.a, n.b) - Math.abs(n.b - n.a) * 2 - 5) / 5) * 5), hi = Math.max(n.a, n.b) * 1.08;
  const bx = 60, bw = 560, px = (v) => bx + (v - lo) / (hi - lo) * bw;
  const d = n.b - n.a, dt = `${d >= 0 ? "+" : "−"}${Math.abs(d) < 10 ? Math.abs(d).toFixed(1) : Math.round(Math.abs(d))}`;
  const rows = [[n.ref || "ふだん", n.a, "#9a937f", "", e(t / 0.6)], [o.title.length <= 10 ? o.title : "この条件", n.b, col, dt, e((t - 0.25) / 0.6)]];
  y += 92;
  for (const [lbl, v, cc, flag, k] of rows) {
    x.fillStyle = "#14212c"; x.font = `900 42px ${RC_F}`; x.fillText(lbl, bx, y);
    if (flag && t >= 0.9) {
      const lw = x.measureText(lbl).width;
      x.font = `900 40px ${RC_F}`;
      const fw = x.measureText(flag).width + 46, fx = bx + lw + 22, fy = y - 40;
      x.fillStyle = cc; x.beginPath(); x.moveTo(fx, fy); x.lineTo(fx + fw, fy); x.lineTo(fx + fw - 16, fy + 26); x.lineTo(fx + fw, fy + 52); x.lineTo(fx, fy + 52); x.closePath(); x.fill();
      x.fillStyle = "#ffffff"; x.fillText(flag, fx + 14, fy + 42);
    }
    y += 24;
    const vv = lo + (v - lo) * k;
    if (k > 0) {
      x.fillStyle = cc; x.fillRect(bx, y, Math.max(2, px(vv) - bx), 92);
      x.font = `900 104px ${RC_F}`; x.fillStyle = "#14212c"; x.fillText(k >= 1 ? rcPct(v) : rcPct(vv), px(vv) + 24, y + 88);
    }
    y += 148;
  }
  // 妙味のヒント(だから何?)
  y += 6;
  const ans = rcAnswer(o);
  x.fillStyle = "#c8141c"; x.font = `900 30px ${RC_F}`; x.fillText(`妙味のヒント${ans.at ? `(${ans.at}のオッズで)` : ""}`, 60, y);
  ans.lines.forEach((ln, i) => {
    const last = i === ans.lines.length - 1 && ans.lines.length === 3;
    y += i === 0 ? 48 : 44;
    if (ans.hl && i === 0) { x.fillStyle = "#c8141c"; x.font = `900 40px ${RC_F}`; }
    else if (last) { x.fillStyle = "#4d5a66"; x.font = `900 32px ${RC_F}`; }
    else { x.fillStyle = "#14212c"; x.font = `900 34px ${RC_F}`; }
    x.fillText(ln, 60, y, W - 120);
  });
  if (gull) { try { x.drawImage(gull, 60, H - 96, 68, 68); } catch (err) { /* 顔が描けなくても出す */ } }
  x.fillStyle = "#4d5a66"; x.font = `700 28px ${RC_F}`;
  x.fillText("ミカタ ・ 公式の成績データ(2023年10月〜)で数えました", 144, H - 70);
  x.fillStyle = "#c8141c"; x.font = `900 28px ${RC_F}`; x.fillText("こういう見方もあるよ", 144, H - 34);
}

let RC_GULL_IMG = null;
async function rcGull() {
  if (RC_GULL_IMG) return RC_GULL_IMG;
  const img = new Image();
  img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(RC_GULL);
  await new Promise((ok) => { img.onload = ok; img.onerror = ok; });
  RC_GULL_IMG = img.naturalWidth ? img : null;
  return RC_GULL_IMG;
}

// 静止画(PNG の data URL)
async function replyCardURL(o) {
  const c = document.createElement("canvas"); c.width = 1080; c.height = 1080;
  drawReplyCard(c.getContext("2d"), o, 1, await rcGull());
  return c.toDataURL("image/png");
}

// 動く版(GIF。長押しで写真に保存でき、X の返信に付けると自動で動く)。棒が伸びて数字が数え上がり、旗が出て4秒止まって、また最初から
async function replyCardGIF(o, size = 720) {
  const gull = await rcGull();
  const c = document.createElement("canvas"); c.width = size; c.height = size;
  const x = c.getContext("2d", { willReadFrequently: true });
  const frames = [], delays = [];
  const N = 16;
  for (let i = 0; i <= N; i++) {
    x.setTransform(size / 1080, 0, 0, size / 1080, 0, 0);
    drawReplyCard(x, o, i / N, gull);
    frames.push(x.getImageData(0, 0, size, size).data);
    delays.push(i === N ? 400 : (i === 0 ? 40 : 8));
  }
  return URL.createObjectURL(new Blob([gifEncode(frames, delays, size, size)], { type: "image/gif" }));
}

// ---- 小さな GIF の書き出し(外のライブラリを使わない)。色は、カードで使う色そのまま+6×6×6 の色(文字のふちのにじみ用)
const RC_KEY = ["#f4efdf", "#14212c", "#17191c", "#ffe100", "#ffffff", "#4d5a66", "#9a937f", "#c8141c", "#0b5fb4", "#d9dde0", "#111111", "#000000"]
  .concat(RC_LANE_BG, RC_LANE_FG);
function rcPalette() {
  const pal = [], key = new Map();
  for (const h of RC_KEY) {
    const v = parseInt(h.slice(1), 16);
    if (!key.has(v) && pal.length < 40) { key.set(v, pal.length); pal.push([(v >> 16) & 255, (v >> 8) & 255, v & 255]); }
  }
  while (pal.length < 40) pal.push([0, 0, 0]);
  for (let r = 0; r < 6; r++) for (let g = 0; g < 6; g++) for (let b = 0; b < 6; b++) pal.push([r * 51, g * 51, b * 51]);
  return { pal, key };
}
function gifEncode(frames, delays, w, h) {
  const { pal, key } = rcPalette();
  const out = [];
  const w16 = (v) => { out.push(v & 255, (v >> 8) & 255); };
  for (const ch of "GIF89a") out.push(ch.charCodeAt(0));
  w16(w); w16(h); out.push(0xf7, 0, 0);
  for (const [r, g, b] of pal) out.push(r, g, b);
  out.push(0x21, 0xff, 0x0b); for (const ch of "NETSCAPE2.0") out.push(ch.charCodeAt(0)); out.push(3, 1, 0, 0, 0);
  const idx = new Uint8Array(w * h);
  frames.forEach((px, f) => {
    for (let i = 0, j = 0; i < idx.length; i++, j += 4) {
      const v = (px[j] << 16) | (px[j + 1] << 8) | px[j + 2];
      const k = key.get(v);
      idx[i] = k !== undefined ? k : 40 + Math.round(px[j] / 51) * 36 + Math.round(px[j + 1] / 51) * 6 + Math.round(px[j + 2] / 51);
    }
    out.push(0x21, 0xf9, 4, 0x04); w16(delays[f]); out.push(0, 0);
    out.push(0x2c); w16(0); w16(0); w16(w); w16(h); out.push(0);
    out.push(8);
    const data = gifLZW(idx, 8);
    for (let i = 0; i < data.length; i += 255) { const n = Math.min(255, data.length - i); out.push(n); for (let k = 0; k < n; k++) out.push(data[i + k]); }
    out.push(0);
  });
  out.push(0x3b);
  return new Uint8Array(out);
}
function gifLZW(idx, minSize) {   // omggif と同じやり方(コードの長さを増やす時機を、読む側とそろえる)
  const clear = 1 << minSize, eoi = clear + 1, out = [];
  let size = minSize + 1, next = eoi + 1, table = new Map(), cur = 0, shift = 0;
  const emit = (code) => { cur |= code << shift; shift += size; while (shift >= 8) { out.push(cur & 255); cur >>>= 8; shift -= 8; } };
  emit(clear);
  let ib = idx[0];
  for (let i = 1; i < idx.length; i++) {
    const k = idx[i], keyv = (ib << 8) | k, c = table.get(keyv);
    if (c !== undefined) { ib = c; continue; }
    emit(ib);
    if (next === 4096) { emit(clear); next = eoi + 1; size = minSize + 1; table = new Map(); }
    else { if (next >= (1 << size)) size++; table.set(keyv, next++); }
    ib = k;
  }
  emit(ib); emit(eoi);
  if (shift > 0) out.push(cur & 255);
  return out;
}
