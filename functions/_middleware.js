// すべてのページ・データ・APIの手前で動くパスワード保護。
// パスワードは Cloudflare の環境変数(Secret)APP_PASSWORD に入れる。
const COOKIE = "ky_auth";
const DAYS = 90;
const enc = new TextEncoder();

async function sign(secret, msg) {
  const key = await crypto.subtle.importKey("raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = await crypto.subtle.sign("HMAC", key, enc.encode(msg));
  return [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function safeEqual(a, b) {
  if (a.length !== b.length) return false;
  let d = 0;
  for (let i = 0; i < a.length; i++) d |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return d === 0;
}

async function validCookie(request, secret) {
  const m = (request.headers.get("Cookie") || "").match(new RegExp(`(?:^|; )${COOKIE}=([^;]+)`));
  if (!m) return false;
  const [exp, sig] = decodeURIComponent(m[1]).split(".");
  if (!exp || !sig || Number(exp) < Date.now() / 1000) return false;
  return safeEqual(sig, await sign(secret, "kyotei:" + exp));
}

function loginPage() {
  return new Response(`<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="robots" content="noindex"><title>競艇ミカタ</title>
<style>
:root{--bg:#e8edf1;--card:#fff;--ink:#102230;--muted:#5c6f80;--line:#d2dbe2;--accent:#102230;--accent-ink:#fff;--bad:#d3141c}
@media (prefers-color-scheme:dark){:root{--bg:#0b141d;--card:#121e2a;--ink:#e6edf3;--muted:#8fa1b2;--line:#233343;--accent:#e6edf3;--accent-ink:#102230;--bad:#ff4a4f}}
body{margin:0;background:var(--bg);color:var(--ink);font-family:system-ui,"Hiragino Sans",sans-serif;min-height:100vh;display:grid;place-items:center;padding:16px}
form{width:100%;max-width:360px;background:var(--card);border-top:5px solid var(--ink);border-radius:4px 4px 14px 14px;padding:24px 20px;display:grid;gap:12px}
.flags{display:flex;gap:2px;margin-bottom:2px}.flags i{width:5px;height:20px;border-radius:1px}
h1{margin:0;font-size:20px}p{margin:0;color:var(--muted);font-size:13px}
input{font:inherit;font-size:16px;padding:12px;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--ink)}
button{font:inherit;font-weight:700;font-size:16px;border:0;border-radius:8px;padding:12px;background:var(--accent);color:var(--accent-ink)}
.msg{min-height:1.2em;color:var(--bad)}
</style></head><body>
<form id="f"><span class="flags" aria-hidden="true"><i style="background:#fff;box-shadow:inset 0 0 0 1px #102230"></i><i style="background:#3a3f45"></i><i style="background:#e3141b"></i><i style="background:#0b5fb4"></i><i style="background:#f5d00a"></i><i style="background:#12904a"></i></span><h1>競艇ミカタ</h1><p>自分専用のページです。パスワードを入力してください。</p>
<input type="text" name="username" value="kyotei" autocomplete="username" hidden>
<input id="pw" type="password" autocomplete="current-password" placeholder="パスワード" required autofocus>
<button>ひらく</button><p class="msg" id="m"></p></form>
<script>
const b64d=s=>Uint8Array.from(atob(s.trim()),c=>c.charCodeAt(0));
const b64e=u=>btoa(String.fromCharCode(...new Uint8Array(u)));
document.getElementById("f").onsubmit=async e=>{
  e.preventDefault();const pw=document.getElementById("pw").value,m=document.getElementById("m");
  m.textContent="確認中…";m.style.color="var(--muted)";
  const r=await fetch("/__login",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({password:pw})});
  if(!r.ok){m.style.color="var(--bad)";m.textContent="パスワードが違います";return;}
  try{ // 予想データの暗号を解く鍵も、同じパスワードから作って端末に保存
    const salt=b64d(await (await fetch("/data/salt.txt")).text());
    const base=await crypto.subtle.importKey("raw",new TextEncoder().encode(pw),"PBKDF2",false,["deriveKey"]);
    const key=await crypto.subtle.deriveKey({name:"PBKDF2",salt,iterations:250000,hash:"SHA-256"},base,{name:"AES-GCM",length:256},true,["decrypt"]);
    localStorage.setItem("kyotei_key",b64e(await crypto.subtle.exportKey("raw",key)));
  }catch(err){}
  m.textContent="ログインしました。ページを読み込んでいます…";
  location.replace(location.pathname==="/__login"?"/":location.href);
};
</script></body></html>`, { status: 401, headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" } });
}

export async function onRequest(context) {
  const { request, env, next } = context;
  const url = new URL(request.url);
  const secret = env.APP_PASSWORD;
  if (!secret) return new Response("APP_PASSWORD が未設定です(Cloudflare の環境変数で設定してください)", { status: 503 });

  if (url.pathname.startsWith("/s/")) return next();   // 記事の共有ページ(リンクを知っている人だけ。functions/s/)
  if (url.pathname === "/__login" && request.method === "POST") {
    let pw = "";
    try { pw = String((await request.json()).password || ""); } catch (e) { }
    if (!safeEqual(await sign(secret, "pw:" + pw), await sign(secret, "pw:" + secret))) {
      await new Promise((r) => setTimeout(r, 800)); // 総当たり対策
      return new Response("NG", { status: 401 });
    }
    const exp = Math.floor(Date.now() / 1000) + DAYS * 86400;
    const val = encodeURIComponent(`${exp}.${await sign(secret, "kyotei:" + exp)}`);
    return new Response("OK", { headers: { "Set-Cookie": `${COOKIE}=${val}; Path=/; Max-Age=${DAYS * 86400}; HttpOnly; Secure; SameSite=Lax` } });
  }
  if (url.pathname === "/__logout") {
    return new Response(null, { status: 302, headers: { Location: "/", "Set-Cookie": `${COOKIE}=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Lax` } });
  }
  if (await validCookie(request, secret)) {
    const res = await next();
    const out = new Response(res.body, res);
    out.headers.set("X-Robots-Tag", "noindex");
    return out;
  }
  const isPageVisit = request.method === "GET" && (request.headers.get("Accept") || "").includes("text/html");
  if (!isPageVisit && (url.pathname.startsWith("/api/") || url.pathname.startsWith("/data/"))) {
    return new Response(JSON.stringify({ error: "login required" }), { status: 401, headers: { "content-type": "application/json" } });
  }
  return loginPage();
}
