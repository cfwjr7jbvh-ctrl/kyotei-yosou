// 予想データ(暗号化済みJSON)を GitHub から取り次ぐ。
// データが更新されるたびにサイトを作り直さなくて済むよう、静的ファイルではなくここから読む。
// - days/<今日>.json : live ブランチ(5分ごとの直前予想)→ main の docs/data/days/ の順に探す(過去の日は main 優先)
// - cards/*.json    : cards ブランチ(選手カード、毎朝更新)
// - ura/*.json      : cards ブランチ(グレードレースの記事の下書き、毎朝更新)
// - replies/*.json  : live ブランチ(返信先の候補、15分おき)
// - それ以外        : main の docs/data/
// リポジトリを非公開にしたら、Cloudflare の Secret「GITHUB_TOKEN」(読み取り専用のトークン)を入れる。
const REPO = "cfwjr7jbvh-ctrl/kyotei-yosou";

async function fromGitHub(ref, path, token) {
  const headers = { "User-Agent": "kyotei-yosou" };
  let url;
  if (token) {  // 非公開リポジトリ用(API経由。キャッシュされないので最新)
    url = `https://api.github.com/repos/${REPO}/contents/${path}?ref=${ref}`;
    headers.Authorization = `Bearer ${token}`;
    headers.Accept = "application/vnd.github.raw";
  } else {
    url = `https://raw.githubusercontent.com/${REPO}/${ref}/${path}?t=${Math.floor(Date.now() / 30000)}`;
  }
  const r = await fetch(url, { headers, cf: { cacheTtl: 20 } });
  return r.ok ? r : null;
}

export async function onRequestGet({ params, env }) {
  const path = (params.path || []).join("/");
  if (!/^[\w\-.\/]+\.json$/.test(path) || path.includes("..")) {
    return new Response("bad path", { status: 400 });
  }
  const today = new Date(Date.now() + 9 * 3600e3).toISOString().slice(0, 10);  // 日本時間の今日
  const tries = path === `days/${today}.json`
    ? [["live", path], ["main", `docs/data/${path}`]]   // 今日は直前予想(live)を優先
    : path.startsWith("days/")
      ? [["main", `docs/data/${path}`], ["live", path]]  // 過去の日は結果付きの main を優先
      : path.startsWith("replies/")
        ? [["live", path]]                                // 返信先の候補(直前予想のループが15分おきに置く)
      : path.startsWith("cards/") || path.startsWith("ura/")
        ? [["cards", path]]                               // 選手カード・記事の下書き(履歴を積み上げない cards ブランチ)
        : [["main", `docs/data/${path}`]];
  for (const [ref, p] of tries) {
    const r = await fromGitHub(ref, p, env.GITHUB_TOKEN);
    if (r) {
      return new Response(r.body, {
        headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
      });
    }
  }
  return new Response("not found", { status: 404 });
}
