// 動作確認用: 公式サイトに届くか、AIが使えるかを表示する(並行実行・20秒で打ち切り)。
const timeout = (ms) => new Promise((_, rej) => setTimeout(() => rej(new Error(`${ms / 1000}秒でタイムアウト`)), ms));

async function probe(url) {
  const t0 = Date.now();
  try {
    const r = await Promise.race([fetch(url, { headers: { "User-Agent": "Mozilla/5.0 (personal kyotei app)" } }), timeout(15000)]);
    const buf = await r.arrayBuffer();
    return { status: r.status, bytes: buf.byteLength, ms: Date.now() - t0 };
  } catch (e) { return { error: String(e?.message || e), ms: Date.now() - t0 }; }
}

async function ai(env) {
  if (!env.AI) return { ok: false, error: "AI binding なし" };
  const t0 = Date.now();
  try {
    const res = await Promise.race([env.AI.run(env.AI_MODEL || "@cf/openai/gpt-oss-120b",
      { messages: [{ role: "user", content: "「接続テスト成功」とだけ日本語で返してください。" }], max_tokens: 60 }), timeout(20000)]);
    return { ok: true, ms: Date.now() - t0, sample: JSON.stringify(res).slice(0, 300) };
  } catch (e) { return { ok: false, error: String(e?.message || e), ms: Date.now() - t0 }; }
}

export async function onRequestGet({ env }) {
  const hd = new Date(Date.now() + 9 * 3600e3).toISOString().slice(0, 10).replace(/-/g, "");
  const [top, lzh, aiRes] = await Promise.all([
    probe(`https://www.boatrace.jp/owpc/pc/race/index?hd=${hd}`),
    probe(`http://www1.mbrace.or.jp/od2/B/${hd.slice(0, 6)}/b${hd.slice(2)}.lzh`),
    ai(env),
  ]);
  const out = { "公式トップ": top, "番組表ファイル": lzh, AI: aiRes };
  const ok = top.status === 200 && aiRes.ok;
  const html = `<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>接続テスト</title><body style="font-family:system-ui;padding:16px;line-height:1.6">
<h2>${ok ? "✅ すべてOK" : "⚠️ 一部NG"}</h2><pre style="white-space:pre-wrap;font-size:12px">${JSON.stringify(out, null, 1).replace(/</g, "&lt;")}</pre>
<p><a href="/">アプリへ戻る</a></p></body>`;
  return new Response(html, { headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" } });
}
