/*
 * Proxy for Telegram Bot API and Discord REST API calls made from the chat.
 * The bot token comes from the user's browser with each call and is never stored
 * on the server or sent to the AI model.
 *
 *  POST /api/bot { platform: "telegram", token, method: "sendMessage", params: {...} }
 *  POST /api/bot { platform: "discord",  token, method: "POST", path: "/channels/1/messages", body: {...} }
 */

const MAX_OUT = 15000;
const DISCORD_METHODS = new Set(["GET", "POST", "PUT", "PATCH", "DELETE"]);

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" },
  });

async function forward(url, init) {
  const res = await fetch(url, { ...init, signal: AbortSignal.timeout(20000) });
  const text = await res.text();
  let data;
  try {
    data = JSON.parse(text);
  } catch {
    data = text.slice(0, MAX_OUT);
  }
  let out = typeof data === "string" ? data : JSON.stringify(data, null, 1);
  if (out.length > MAX_OUT) out = out.slice(0, MAX_OUT) + "\n…[تم اختصار الناتج]";
  return { status: res.status, ok: res.ok, output: out };
}

export default async (req) => {
  if (req.method !== "POST") return json({ error: "Method not allowed" }, 405);
  let b;
  try {
    b = await req.json();
  } catch {
    return json({ error: "طلب غير صالح" }, 400);
  }
  const token = String(b?.token || "").trim();

  try {
    if (b?.platform === "telegram") {
      if (!/^\d{5,15}:[A-Za-z0-9_-]{30,60}$/.test(token)) return json({ error: "توكن تيليجرام غير صالح" }, 400);
      const method = String(b.method || "");
      if (!/^[A-Za-z]{2,40}$/.test(method)) return json({ error: "اسم دالة تيليجرام غير صالح" }, 400);
      const params = b.params && typeof b.params === "object" ? b.params : {};
      const r = await forward(`https://api.telegram.org/bot${token}/${method}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(params),
      });
      return json(r);
    }

    if (b?.platform === "discord") {
      if (!/^[A-Za-z0-9_.-]{50,100}$/.test(token)) return json({ error: "توكن ديسكورد غير صالح" }, 400);
      const method = String(b.method || "GET").toUpperCase();
      if (!DISCORD_METHODS.has(method)) return json({ error: "نوع الطلب غير مدعوم" }, 400);
      let path = String(b.path || "");
      if (!path.startsWith("/")) path = "/" + path;
      if (!/^\/[A-Za-z0-9_\-/.@%?=&,:~]*$/.test(path) || path.includes("..") || path.includes("//")) {
        return json({ error: "مسار ديسكورد غير صالح" }, 400);
      }
      const headers = { Authorization: `Bot ${token}`, "User-Agent": "DiscordBot (norestrictions-ai-chat, 1.0)" };
      const init = { method, headers };
      if (b.body !== undefined && method !== "GET" && method !== "DELETE") {
        headers["Content-Type"] = "application/json";
        init.body = JSON.stringify(b.body);
      }
      if (b.reason) headers["X-Audit-Log-Reason"] = encodeURIComponent(String(b.reason).slice(0, 400));
      const r = await forward(`https://discord.com/api/v10${path}`, init);
      return json(r);
    }

    return json({ error: "المنصة غير مدعومة (telegram أو discord فقط)" }, 400);
  } catch (e) {
    return json({ error: `تعذر الاتصال بالمنصة: ${e.message}` }, 502);
  }
};

export const config = { path: "/api/bot" };
