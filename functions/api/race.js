// 公式サイトのレースページを取ってくる中継役(スマホから直接は取れないため)。
// 決まったページ・決まった形式のパラメータだけを通す。
const PAGES = new Set(["beforeinfo", "odds3t", "oddstf", "raceresult", "racelist", "index"]);
const TTL = { odds3t: 10, oddstf: 10, beforeinfo: 30, raceresult: 300, racelist: 300, index: 120 };

export async function onRequestGet({ request }) {
  const q = new URL(request.url).searchParams;
  const page = q.get("page") || "";
  const hd = q.get("hd") || "";
  const jcd = q.get("jcd") || "";
  const rno = q.get("rno") || "";
  if (!PAGES.has(page) || !/^\d{8}$/.test(hd) || (page !== "index" && (!/^\d{2}$/.test(jcd) || !/^\d{1,2}$/.test(rno)))) {
    return new Response("bad request", { status: 400 });
  }
  const base = "https://www.boatrace.jp/owpc/pc/race/";
  const target = page === "index" ? `${base}index?hd=${hd}` : `${base}${page}?rno=${Number(rno)}&jcd=${jcd}&hd=${hd}`;
  const t0 = Date.now();
  let r;
  try {
    r = await fetch(target, {
      headers: { "User-Agent": "Mozilla/5.0 (personal kyotei app; low-frequency)", "Accept-Language": "ja" },
      cf: { cacheTtl: TTL[page], cacheEverything: true },
    });
  } catch (e) {
    return new Response("upstream error: " + e, { status: 502 });
  }
  return new Response(r.body, {
    status: r.status,
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": `private, max-age=${Math.min(TTL[page], 30)}`,
      "x-upstream-status": String(r.status),
      "x-upstream-ms": String(Date.now() - t0),
    },
  });
}
