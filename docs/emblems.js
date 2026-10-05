// 自動生成: python -c 'from kyotei.emblem import js_module; print(js_module())' > docs/emblems.js
const EMBLEMS = {"スタート職人": {"c": "#e8453c", "k": "ST"}, "展示STを信じていい": {"c": "#3b82e6", "k": "展"}, "本番で踏み込む": {"c": "#f2772b", "k": "踏"}, "イン逃げ番長": {"c": "#2c3e50", "k": "逃"}, "差し職人": {"c": "#2eaa5e", "k": "差"}, "まくり屋": {"c": "#d6336c", "k": "捲"}, "まくり差しの職人": {"c": "#8e5bd6", "k": "捲差"}, "外からでも届く": {"c": "#1aa3b8", "k": "外"}, "前づけの仕掛け人": {"c": "#d99a1e", "k": "前"}, "展示は控えめ、本番で化ける": {"c": "#b04fc9", "k": "化"}, "上り調子": {"c": "#f06a3a", "k": "昇"}, "舟券に絡む安定感": {"c": "#3a9c6c", "k": "安"}, "展示タイム番長": {"c": "#0f8a7e", "k": "展王"}};
const EMBLEM_ALIAS = {"急成長中": "上り調子"};
function emblem(tag, size = 22) {
  tag = EMBLEM_ALIAS[tag] || tag;
  const d = EMBLEMS[tag];
  if (!d) return "";
  const fs = d.k.length === 1 ? 58 : d.k === "ST" ? 44 : 34, y = d.k.length === 1 ? 70 : d.k === "ST" ? 66 : 62;
  return `<svg class="emb" viewBox="0 0 100 100" width="${size}" height="${size}" role="img" aria-label="${tag}の紋章"><circle cx="50" cy="50" r="47" fill="${d.c}" stroke="#14212c" stroke-width="4"/><text x="50" y="${y}" font-family="Dela Gothic One, 'Zen Kaku Gothic New', sans-serif" font-size="${fs}" fill="#fff" text-anchor="middle">${d.k}</text></svg>`;
}
