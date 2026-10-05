// 記事の共有ページ: /s/<key>/<token> を知っている人だけが読める(パスワード不要。LINE などで友達に送る用)。
// token はアプリが作る(予想データの鍵から HMAC)。サーバーは APP_PASSWORD から同じ鍵を作って照合し、
// cards ブランチの ura/<key>.json(暗号化済み)を解いて紙面(HTML)だけを返す。note 用の本文や X の投稿案は返さない。
const REPO = "cfwjr7jbvh-ctrl/kyotei-yosou";
const enc = new TextEncoder();
const b64d = (s) => Uint8Array.from(atob(s.trim()), (c) => c.charCodeAt(0));
let KEY_CACHE = null;

async function siteKey(password) {
  if (KEY_CACHE) return KEY_CACHE;
  const r = await fetch(`https://raw.githubusercontent.com/${REPO}/main/docs/data/salt.txt`, { cf: { cacheTtl: 3600 } });
  const salt = b64d(await r.text());
  const base = await crypto.subtle.importKey("raw", enc.encode(password), "PBKDF2", false, ["deriveKey"]);
  KEY_CACHE = await crypto.subtle.deriveKey({ name: "PBKDF2", salt, iterations: 250000, hash: "SHA-256" }, base,
    { name: "AES-GCM", length: 256 }, true, ["decrypt"]);
  return KEY_CACHE;
}

async function hmacHex(rawKey, msg) {
  const k = await crypto.subtle.importKey("raw", rawKey, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = await crypto.subtle.sign("HMAC", k, enc.encode(msg));
  return [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export async function onRequestGet({ params, env }) {
  const parts = (params.path || []);
  const [key, token] = parts;
  if (!key || !token || !/^[\w]+$/.test(key) || !/^[0-9a-f]{20}$/.test(token)) return new Response("not found", { status: 404 });
  if (!env.APP_PASSWORD) return new Response("設定がありません", { status: 503 });
  const aes = await siteKey(env.APP_PASSWORD);
  const raw = await crypto.subtle.exportKey("raw", aes);
  const want = (await hmacHex(raw, "share:" + key)).slice(0, 20);
  let d = 0;
  for (let i = 0; i < 20; i++) d |= want.charCodeAt(i) ^ token.charCodeAt(i);
  if (d !== 0) return new Response("not found", { status: 404 });
  const r = await fetch(`https://raw.githubusercontent.com/${REPO}/cards/ura/${key}.json?t=${Math.floor(Date.now() / 300000)}`, { cf: { cacheTtl: 300 } });
  if (!r.ok) return new Response("記事がまだありません(毎朝作り直しています)", { status: 404, headers: { "content-type": "text/plain; charset=utf-8" } });
  const obj = await r.json();
  if (!obj || obj.enc !== 1) return new Response("not found", { status: 404 });
  const pt = await crypto.subtle.decrypt({ name: "AES-GCM", iv: b64d(obj.iv) }, aes, b64d(obj.ct));
  const art = JSON.parse(new TextDecoder().decode(pt));
  const html = `<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="robots" content="noindex,nofollow">${art.html}
<div style="max-width:960px;margin:0 auto;padding:0 16px 32px;font:13px/1.6 system-ui,sans-serif;color:#5e5848">この記事はミカタ新聞の読者から共有されたページです。買い目は売っていません。舟券は20歳になってから。</div></body></html>`;
  return new Response(html, { headers: { "content-type": "text/html; charset=utf-8", "cache-control": "private, max-age=300", "X-Robots-Tag": "noindex" } });
}
