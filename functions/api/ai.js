// アプリ内AI(Cloudflare Workers AI の無料枠)。レースのデータを渡して質問に答える。
const SYSTEM = `あなたは競艇(ボートレース)の予想アプリに内蔵されたアシスタントです。
- 渡された「レースのデータ」(AIモデルの確率、オッズ、期待値、展示タイム、展示ST、選手の成績など)を根拠に、日本語で簡潔に答えます。
- データにないことは推測だと明示し、断定しません。
- 期待値は「確率×オッズ」。1を超えても必ず当たるわけではないことを踏まえて説明します。
- 舟券は20歳以上、余裕資金の範囲で楽しむよう、必要に応じて一言添えます。
- スマホで読みやすいよう、要点を短く。`;

function textOf(res) {
  if (!res) return "";
  if (typeof res === "string") return res;
  if (typeof res.response === "string") return res.response;
  if (res.result) return textOf(res.result);
  const c = res.choices?.[0]?.message?.content;
  if (typeof c === "string") return c;
  if (Array.isArray(res.output)) {
    return res.output.filter((o) => o.type === "message")
      .flatMap((o) => o.content || []).map((p) => p.text || "").join("");
  }
  return "";
}

export async function onRequestPost({ request, env }) {
  if (!env.AI) return Response.json({ error: "AI が未設定です" }, { status: 503 });
  let body;
  try { body = await request.json(); } catch (e) { return Response.json({ error: "bad json" }, { status: 400 }); }
  const context = String(body.context || "").slice(0, 12000);
  const history = (Array.isArray(body.messages) ? body.messages : []).slice(-8)
    .filter((m) => (m.role === "user" || m.role === "assistant") && typeof m.content === "string")
    .map((m) => ({ role: m.role, content: m.content.slice(0, 2000) }));
  if (!history.length || history[history.length - 1].role !== "user") {
    return Response.json({ error: "質問がありません" }, { status: 400 });
  }
  const messages = [{ role: "system", content: SYSTEM + (context ? "\n\n# レースのデータ\n" + context : "") }, ...history];
  const model = env.AI_MODEL || "@cf/openai/gpt-oss-120b";
  try {
    const res = await env.AI.run(model, { messages, max_tokens: 900 });
    const text = textOf(res).trim();
    return Response.json({ text: text || "(回答が空でした。もう一度聞いてみてください)", model });
  } catch (e) {
    const msg = String(e?.message || e);
    const quota = /limit|quota|neuron|429/i.test(msg);
    return Response.json({ error: quota ? "今日の無料枠を使い切りました。明日の朝9時(日本時間)にリセットされます。" : "AIの呼び出しに失敗しました: " + msg }, { status: quota ? 429 : 502 });
  }
}
