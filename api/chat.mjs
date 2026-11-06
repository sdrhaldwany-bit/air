import { lookup } from "node:dns/promises";
import { isIP } from "node:net";

const API_URL =
  process.env.NR_API_URL ||
  "https://api.aiwithnorestrictions.com/v1/chat/completions";

const MODEL = process.env.NR_MODEL || "notrack-uncensored";
const MAX_HISTORY = 20;
const MAX_PAGE_CHARS = 12000;
const MAX_TOOL_ROUNDS = 2;
const TOTAL_BUDGET_MS = 45000;

const SYSTEM_PROMPT = `أنت مساعد ذكي ترد بلغة المستخدم.
لديك أدوات للبحث وقراءة صفحات الإنترنت:
1) للبحث اكتب فقط: <<SEARCH: عبارة البحث>>
2) لقراءة صفحة اكتب فقط: <<FETCH: https://example.com>>
3) إذا طلب المستخدم فتح موقع في متصفحه، أدرج الرابط مباشرة بصيغة Markdown.
يمكنك طلب حتى 3 عمليات بحث أو قراءة في الرد الواحد.
لا تخترع محتوى صفحات لم تقرأها. اعرض المصادر التي استخدمتها.
استخدم Markdown في الإجابة.`;

const URL_RE = /https?:\/\/[^\s<>"'` )\]]+/gi;
const TOOL_RE = /<<\s*(FETCH|SEARCH)\s*:\s*([^>\n]+?)\s*>>/gi;

function isPrivateIp(ip) {
  if (isIP(ip) === 4) {
    const [a, b] = ip.split(".").map(Number);
    return (
      a === 0 || a === 10 || a === 127 ||
      (a === 169 && b === 254) ||
      (a === 172 && b >= 16 && b <= 31) ||
      (a === 192 && b === 168) ||
      (a === 100 && b >= 64 && b <= 127) ||
      a >= 224
    );
  }

  const v = ip.toLowerCase();

  if (v.startsWith("::ffff:")) {
    return isPrivateIp(v.slice(7));
  }

  return (
    v === "::" ||
    v === "::1" ||
    v.startsWith("fc") ||
    v.startsWith("fd") ||
    v.startsWith("fe80")
  );
}

async function assertPublicUrl(raw) {
  const url = new URL(raw);

  if (!["http:", "https:"].includes(url.protocol)) {
    throw new Error("بروتوكول الرابط غير مسموح");
  }

  const host = url.hostname.replace(/^\[|\]$/g, "");

  if (/^(localhost|.*\.local|.*\.internal)$/i.test(host)) {
    throw new Error("عنوان الرابط غير مسموح");
  }

  const addresses = isIP(host)
    ? [{ address: host }]
    : await lookup(host, { all: true });

  if (
    !addresses.length ||
    addresses.some(x => isPrivateIp(x.address))
  ) {
    throw new Error("عنوان الرابط غير مسموح");
  }

  return url;
}

async function safeFetch(raw, init = {}, timeoutMs = 9000) {
  let url = await assertPublicUrl(raw);

  for (let i = 0; i < 5; i++) {
    const response = await fetch(url, {
      ...init,
      redirect: "manual",
      headers: {
        "User-Agent": "Mozilla/5.0",
        "Accept-Language": "ar,en;q=0.8",
        ...(init.headers || {})
      },
      signal: AbortSignal.timeout(timeoutMs)
    });

    const location = response.headers.get("location");

    if (
      response.status >= 300 &&
      response.status < 400 &&
      location
    ) {
      url = await assertPublicUrl(
        new URL(location, url).toString()
      );
      continue;
    }

    return {
      response,
      url: url.toString()
    };
  }

  throw new Error("عدد التحويلات كبير جداً");
}

function decodeEntities(s) {
  return s
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;|&apos;/g, "'");
}

function htmlToText(html) {
  return decodeEntities(
    html
      .replace(
        /<(script|style|noscript|svg|iframe|template)[\s\S]*?<\/\1>/gi,
        " "
      )
      .replace(/<!--[\s\S]*?-->/g, " ")
      .replace(
        /<(br|\/p|\/div|\/li|\/h[1-6]|\/tr|\/section|\/article)[^>]*>/gi,
        "\n"
      )
      .replace(/<[^>]+>/g, " ")
  )
    .replace(/[ \t\f\v]+/g, " ")
    .replace(/\n\s*\n+/g, "\n")
    .trim();
}

async function readPage(raw) {
  try {
    const { response, url } = await safeFetch(raw);

    if (!response.ok) {
      return {
        url,
        title: url,
        error: `HTTP ${response.status}`
      };
    }

    const type = response.headers.get("content-type") || "";
    const body = (await response.text()).slice(0, 500000);

    let title = url;
    let text = body;

    if (/html|xml/i.test(type) || /^\s*</.test(body)) {
      const match = body.match(
        /<title[^>]*>([\s\S]*?)<\/title>/i
      );

      if (match) {
        title = decodeEntities(match[1]).trim() || url;
      }

      text = htmlToText(body);
    } else if (!/text|json|javascript|csv/i.test(type)) {
      return {
        url,
        title,
        error: "نوع الملف غير مدعوم"
      };
    }

    return {
      url,
      title,
      text: text.slice(0, MAX_PAGE_CHARS)
    };
  } catch (error) {
    return {
      url: raw,
      title: raw,
      error: error.message
    };
  }
}

async function searchWeb(query) {
  try {
    const { response } = await safeFetch(
      `https://www.bing.com/search?format=rss&count=8&q=${encodeURIComponent(query)}`
    );

    const xml = await response.text();
    const results = [];

    for (const [, item] of xml.matchAll(
      /<item>([\s\S]*?)<\/item>/g
    )) {
      const get = tag => {
        const m = item.match(
          new RegExp(`<${tag}>([\\\\s\\\\S]*?)</${tag}>`)
        );

        return m
          ? decodeEntities(
              m[1].replace(/<!\[CDATA\[|\]\]>/g, "")
            ).trim()
          : "";
      };

      const url = get("link");

      if (url) {
        results.push({
          title: get("title"),
          url,
          snippet: get("description")
        });
      }

      if (results.length >= 8) break;
    }

    return { query, results };
  } catch (error) {
    return {
      query,
      results: [],
      error: error.message
    };
  }
}

function formatPage(page) {
  if (page.error) {
    return `[تعذر قراءة ${page.url}: ${page.error}]`;
  }

  return `### ${page.title}
الرابط: ${page.url}

${page.text}`;
}

function formatSearch(data) {
  if (!data.results.length) {
    return `[لا توجد نتائج بحث عن ${data.query}]`;
  }

  return `### نتائج البحث عن: ${data.query}
${data.results
  .map(
    (r, i) =>
      `${i + 1}. ${r.title}\n${r.url}\n${r.snippet}`
  )
  .join("\n\n")}`;
}

async function callModel(apiKey, messages, timeoutMs) {
  const controller = new AbortController();

  const timer = setTimeout(
    () => controller.abort(),
    Math.max(3000, timeoutMs)
  );

  try {
    const upstream = await fetch(API_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${apiKey}`
      },
      body: JSON.stringify({
        model: MODEL,
        messages,
        temperature: 0.7,
        max_tokens: 2048,
        stream: false
      }),
      signal: controller.signal
    });

    const text = await upstream.text();

    let data;

    try {
      data = JSON.parse(text);
    } catch {
      throw new Error(
        "استجابة غير مفهومة من خدمة الذكاء الاصطناعي"
      );
    }

    if (!upstream.ok) {
      throw new Error(
        data?.error?.message ||
        `خدمة الذكاء الاصطناعي أعادت HTTP ${upstream.status}`
      );
    }

    const reply = data?.choices?.[0]?.message?.content;

    if (typeof reply !== "string" || !reply.trim()) {
      throw new Error(
        "لم يصل رد من خدمة الذكاء الاصطناعي"
      );
    }

    return reply;
  } finally {
    clearTimeout(timer);
  }
}

function compactHistory(messages) {
  return messages
    .filter(
      m =>
        m &&
        ["user", "assistant"].includes(m.role) &&
        typeof m.content === "string" &&
        m.content.trim()
    )
    .slice(-MAX_HISTORY)
    .map(m => ({
      role: m.role,
      content: m.content.slice(-12000)
    }));
}

async function handleChat(body) {
  const started = Date.now();

  const remaining = () =>
    TOTAL_BUDGET_MS - (Date.now() - started);

  const apiKey = process.env.NR_API_KEY;

  if (!apiKey) {
    throw new Error(
      "مفتاح NR_API_KEY غير مضبوط في إعدادات Vercel."
    );
  }

  const history = compactHistory(body?.messages || []);

  if (!history.length) {
    throw new Error("لا توجد رسائل لإرسالها.");
  }

  const messages = [
    {
      role: "system",
      content: SYSTEM_PROMPT
    },
    ...history
  ];

  const sources = [];
  const last = messages[messages.length - 1];

  if (last.role === "user") {
    const urls = [
      ...new Set(last.content.match(URL_RE) || [])
    ].slice(0, 3);

    if (urls.length) {
      const pages = await Promise.all(
        urls.map(readPage)
      );

      pages.forEach(p => {
        if (!p.error) {
          sources.push({
            title: p.title,
            url: p.url
          });
        }
      });

      messages[messages.length - 1] = {
        role: "user",
        content:
          last.content +
          "\n\n[محتوى الروابط المرسلة]\n" +
          pages.map(formatPage).join("\n\n---\n\n")
      };
    }
  }

  let reply = await callModel(
    apiKey,
    messages,
    remaining() - 1500
  );

  for (
    let round = 0;
    round < MAX_TOOL_ROUNDS;
    round++
  ) {
    const calls = [
      ...reply.matchAll(TOOL_RE)
    ].slice(0, 3);

    if (!calls.length || remaining() < 8000) {
      break;
    }

    const outputs = await Promise.all(
      calls.map(async ([, kind, arg]) => {
        if (kind.toUpperCase() === "FETCH") {
          const page = await readPage(arg.trim());

          if (!page.error) {
            sources.push({
              title: page.title,
              url: page.url
            });
          }

          return formatPage(page);
        }

        return formatSearch(
          await searchWeb(arg.trim())
        );
      })
    );

    messages.push({
      role: "assistant",
      content: reply
    });

    messages.push({
      role: "user",
      content:
        "[نتائج أدوات البحث وقراءة الصفحات]\n" +
        outputs.join("\n\n---\n\n") +
        "\n\nأكمل الإجابة للمستخدم اعتماداً على النتائج."
    });

    reply = await callModel(
      apiKey,
      messages,
      remaining() - 1500
    );
  }

  reply = reply.replace(TOOL_RE, "").trim() ||
    "لم أتمكن من إكمال الإجابة.";

  const seen = new Set();

  const uniqueSources = sources.filter(s => {
    if (seen.has(s.url)) return false;
    seen.add(s.url);
    return true;
  });

  return {
    reply,
    sources: uniqueSources
  };
}

export default async function handler(req, res) {
  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");

    return res.status(405).json({
      error: "Method not allowed"
    });
  }

  try {
    let body = req.body;

    if (typeof body === "string") {
      try {
        body = JSON.parse(body);
      } catch {
        return res.status(400).json({
          error: "طلب غير صالح"
        });
      }
    }

    if (!body || typeof body !== "object") {
      return res.status(400).json({
        error: "طلب غير صالح"
      });
    }

    const result = await handleChat(body);

    res.setHeader("Cache-Control", "no-store");

    return res.status(200).json(result);
  } catch (error) {
    const message =
      error?.name === "AbortError"
        ? "انتهت مهلة الاتصال بخدمة الذكاء الاصطناعي."
        : error?.message || "حدث خطأ غير معروف";

    return res.status(500).json({
      error: message
    });
  }
}
