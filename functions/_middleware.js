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
<meta name="robots" content="noindex"><title>競艇AI予想</title>
<style>
:root{--bg:#f3f5f8;--card:#fff;--ink:#0d1b2a;--muted:#5b6b7d;--line:#e1e6ec;--accent:#ff6a13;--bad:#c23b3b}
@media (prefers-color-scheme:dark){:root{--bg:#0a1420;--card:#121f2f;--ink:#e8eef5;--muted:#93a3b5;--line:#22344a}}
body{margin:0;background:var(--bg);color:var(--ink);font-family:system-ui,"Hiragino Sans",sans-serif;min-height:100vh;display:grid;place-items:center;padding:16px}
form{width:100%;max-width:340px;background:var(--card);border:1px solid var(--line);border-radius:16px;padding:24px 20px;display:grid;gap:12px}
h1{margin:0;font-size:20px}p{margin:0;color:var(--muted);font-size:13px}
input{font:inherit;font-size:16px;padding:12px;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--ink)}
button{font:inherit;font-weight:700;font-size:15px;border:0;border-radius:10px;padding:12px;background:var(--accent);color:#fff}
.msg{min-height:1.2em;color:var(--bad)}
</style></head><body>
<form id="f"><h1>競艇AI予想</h1><p>自分専用のページです。パスワードを入力してください。</p>
<input type="text" name="username" value="kyotei" autocomplete="username" hidden>
<input id="pw" type="password" autocomplete="current-password" placeholder="パスワード" required autofocus>
<button>ひらく</button><p class="msg" id="m"></p></form>
<script>
const b64d=s=>Uint8Array.from(atob(s.trim()),c=>c.charCodeAt(0));
const b64e=u=>btoa(String.fromCharCode(...new Uint8Array(u)));
document.getElementById("f").onsubmit=async e=>{
  e.preventDefault();const pw=document.getElementById("pw").value,m=document.getElementById("m");
  m.textContent="確認中…";
  const r=await fetch("/__login",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({password:pw})});
  if(!r.ok){m.textContent="パスワードが違います";return;}
  try{ // 予想データの暗号を解く鍵も、同じパスワードから作って端末に保存
    const salt=b64d(await (await fetch("/data/salt.txt")).text());
    const base=await crypto.subtle.importKey("raw",new TextEncoder().encode(pw),"PBKDF2",false,["deriveKey"]);
    const key=await crypto.subtle.deriveKey({name:"PBKDF2",salt,iterations:250000,hash:"SHA-256"},base,{name:"AES-GCM",length:256},true,["decrypt"]);
    localStorage.setItem("kyotei_key",b64e(await crypto.subtle.exportKey("raw",key)));
  }catch(err){}
  location.replace(location.pathname==="/__login"?"/":location.href);
};
</script></body></html>`, { status: 401, headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" } });
}

export async function onRequest(context) {
  const { request, env, next } = context;
  const url = new URL(request.url);
  const secret = env.APP_PASSWORD;
  if (!secret) return new Response("APP_PASSWORD が未設定です(Cloudflare の環境変数で設定してください)", { status: 503 });

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
