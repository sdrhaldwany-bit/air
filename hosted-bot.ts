import { createHash, randomBytes, timingSafeEqual } from "node:crypto";
import { eq } from "drizzle-orm";
import { db } from "../../db/index.js";
import { hostedBots } from "../../db/schema.js";

/*
 * Telegram bots that run on Netlify itself (no phone / Termux needed).
 *
 *  Browser:  POST /api/hosted-bot/enable  { token, persona } -> sets the webhook, bot replies with AI 24/7
 *            POST /api/hosted-bot/disable { token }
 *            POST /api/hosted-bot/status  { token }
 *  Telegram: POST /api/hosted-bot/hook/<id>  (webhook, checked with a secret header)
 */

const API_URL = process.env.NR_API_URL || "https://api.aiwithnorestrictions.com/v1/chat/completions";
const MODEL = process.env.NR_MODEL || "notrack-uncensored";
const TG_TOKEN_RE = /^\d{5,15}:[A-Za-z0-9_-]{30,60}$/;

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" },
  });

const idOf = (token: string) => createHash("sha256").update(token).digest("hex").slice(0, 40);

async function tg(token: string, method: string, params: unknown, ms = 15000) {
  const r = await fetch(`https://api.telegram.org/bot${token}/${method}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params ?? {}),
    signal: AbortSignal.timeout(ms),
  });
  return (await r.json().catch(() => ({ ok: false, description: `HTTP ${r.status}` }))) as any;
}

async function aiReply(persona: string, userName: string, text: string) {
  const apiKey = process.env.NR_API_KEY;
  if (!apiKey) return null;
  const system =
    (persona.trim() || "أنت بوت تيليجرام ودود ومفيد. رد باختصار وبلغة المرسل.") +
    "\nأنت تتحدث داخل تيليجرام؛ اكتب نصاً عادياً قصيراً بدون كتل كود تنفيذية.";
  const r = await fetch(API_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${apiKey}` },
    body: JSON.stringify({
      model: MODEL,
      messages: [
        { role: "system", content: system },
        { role: "user", content: `${userName}: ${text}`.slice(0, 4000) },
      ],
      temperature: 0.7,
      max_tokens: 800,
    }),
    signal: AbortSignal.timeout(40000),
  });
  const d: any = await r.json().catch(() => null);
  const reply = d?.choices?.[0]?.message?.content;
  return typeof reply === "string" && reply.trim() ? reply.trim().slice(0, 4000) : null;
}

function sameSecret(a: string, b: string) {
  const x = Buffer.from(a), y = Buffer.from(b);
  return x.length === y.length && timingSafeEqual(x, y);
}

export default async (req: Request) => {
  const url = new URL(req.url);
  const parts = url.pathname.split("/").filter(Boolean); // api, hosted-bot, action, [id]
  const action = parts[2];
  if (req.method !== "POST") return json({ error: "Method not allowed" }, 405);

  try {
    /* ---------- Telegram webhook ---------- */
    if (action === "hook") {
      const id = parts[3] || "";
      const [bot] = await db.select().from(hostedBots).where(eq(hostedBots.id, id));
      const given = req.headers.get("x-telegram-bot-api-secret-token") || "";
      if (!bot || !bot.enabled || !sameSecret(given, bot.secret)) return json({ ok: true });

      const update: any = await req.json().catch(() => ({}));
      const msg = update.message || update.edited_message;
      const text: string = msg?.text || msg?.caption || "";
      if (!msg || !text || msg.from?.is_bot) return json({ ok: true });

      const chatType = msg.chat?.type;
      const uname = bot.username.toLowerCase();
      // In groups, reply only when mentioned, replied to, or a /command is used.
      if (chatType !== "private") {
        const mentioned = uname && text.toLowerCase().includes("@" + uname);
        const repliedToBot = msg.reply_to_message?.from?.username?.toLowerCase() === uname;
        if (!mentioned && !repliedToBot && !text.startsWith("/")) return json({ ok: true });
      }

      await tg(bot.token, "sendChatAction", { chat_id: msg.chat.id, action: "typing" }, 5000).catch(() => {});
      const clean = uname ? text.replace(new RegExp("@" + uname, "ig"), "").trim() : text;
      const reply =
        clean === "/start"
          ? "أهلاً! 👋 أرسل لي أي سؤال وسأرد عليك."
          : (await aiReply(bot.persona, msg.from?.first_name || "مستخدم", clean).catch(() => null)) ||
            "عذراً، حدث خطأ مؤقت. حاول مرة أخرى.";
      await tg(bot.token, "sendMessage", {
        chat_id: msg.chat.id,
        text: reply,
        reply_to_message_id: chatType === "private" ? undefined : msg.message_id,
      });
      return json({ ok: true });
    }

    /* ---------- browser side ---------- */
    const body: any = await req.json().catch(() => ({}));
    const token = String(body?.token || "").trim();
    if (!TG_TOKEN_RE.test(token)) return json({ error: "توكن تيليجرام غير صالح" }, 400);
    const id = idOf(token);

    if (action === "enable") {
      const me = await tg(token, "getMe", {});
      if (!me.ok) return json({ error: "التوكن غير صحيح أو ملغي" }, 400);
      const persona = String(body.persona || "").slice(0, 3000);
      const secret = randomBytes(24).toString("hex");
      const username = String(me.result?.username || "");
      await db
        .insert(hostedBots)
        .values({ id, token, username, persona, secret, enabled: true })
        .onConflictDoUpdate({
          target: hostedBots.id,
          set: { token, username, persona, secret, enabled: true, updatedAt: new Date() },
        });
      const hook = await tg(token, "setWebhook", {
        url: `${url.origin}/api/hosted-bot/hook/${id}`,
        secret_token: secret,
        allowed_updates: ["message", "edited_message"],
        drop_pending_updates: false,
      });
      if (!hook.ok) return json({ error: "تعذر ضبط الـ webhook: " + (hook.description || "") }, 502);
      return json({ ok: true, username, running: true, note: "البوت يعمل الآن على الخادم 24/7 بدون الهاتف" });
    }

    if (action === "disable") {
      await tg(token, "deleteWebhook", {});
      await db.update(hostedBots).set({ enabled: false, updatedAt: new Date() }).where(eq(hostedBots.id, id));
      return json({ ok: true, running: false });
    }

    if (action === "status") {
      const [bot] = await db.select().from(hostedBots).where(eq(hostedBots.id, id));
      const info = await tg(token, "getWebhookInfo", {});
      return json({
        ok: true,
        running: !!bot?.enabled && String(info.result?.url || "").includes(id),
        persona: bot?.persona || "",
        pending: info.result?.pending_update_count ?? 0,
        lastError: info.result?.last_error_message || null,
      });
    }

    return json({ error: "Not found" }, 404);
  } catch (e: any) {
    console.error("hosted bot error", e);
    return json({ error: "خطأ في الخادم: " + (e?.message || "") }, 500);
  }
};

export const config = { path: "/api/hosted-bot/*" };
