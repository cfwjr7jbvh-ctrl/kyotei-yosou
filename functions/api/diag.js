// 動作確認用: 公式サイトに届くか、AIが使えるかを表示する。
export async function onRequestGet({ env }) {
  const out = { now: new Date().toISOString() };
  const hd = new Date(Date.now() + 9 * 3600e3).toISOString().slice(0, 10).replace(/-/g, "");
  for (const [name, url] of [["公式トップ", `https://www.boatrace.jp/owpc/pc/race/index?hd=${hd}`],
                             ["番組表ファイル", `http://www1.mbrace.or.jp/od2/B/${hd.slice(0, 6)}/b${hd.slice(2)}.lzh`]]) {
    const t0 = Date.now();
    try {
      const r = await fetch(url, { headers: { "User-Agent": "Mozilla/5.0 (personal kyotei app)" } });
      const buf = await r.arrayBuffer();
      out[name] = { status: r.status, bytes: buf.byteLength, ms: Date.now() - t0 };
    } catch (e) { out[name] = { error: String(e) }; }
  }
  if (env.AI) {
    const t0 = Date.now();
    try {
      const res = await env.AI.run(env.AI_MODEL || "@cf/openai/gpt-oss-120b",
        { messages: [{ role: "user", content: "「接続テスト成功」とだけ日本語で返してください。" }], max_tokens: 60 });
      out.AI = { ok: true, ms: Date.now() - t0, sample: JSON.stringify(res).slice(0, 300) };
    } catch (e) { out.AI = { ok: false, error: String(e?.message || e) }; }
  } else out.AI = { ok: false, error: "AI binding なし" };
  const ok = out["公式トップ"]?.status === 200 && out.AI?.ok;
  const html = `<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>接続テスト</title><body style="font-family:system-ui;padding:16px;line-height:1.6">
<h2>${ok ? "✅ すべてOK" : "⚠️ 一部NG"}</h2><pre style="white-space:pre-wrap;font-size:12px">${JSON.stringify(out, null, 1).replace(/</g, "&lt;")}</pre></body>`;
  return new Response(html, { headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" } });
}
