import { createHash } from "node:crypto";
import { and, eq, inArray, lt } from "drizzle-orm";
import { db } from "../../db/index.js";
import { devices, jobs } from "../../db/schema.js";

/*
 * Bridge between the chat page and a phone running agent.py (Termux / Pydroid).
 *
 *  Browser:  POST /api/device/run     { key, command }  -> { id }
 *            GET  /api/device/result?key=&id=           -> job (long-polls until done)
 *            GET  /api/device/status?key=               -> { online, kind, info }
 *  Agent:    POST /api/device/poll    { key, kind, info } -> { jobs: [...] } (long-poll)
 *            POST /api/device/done    { key, id, output, exitCode }
 *
 * The secret key is generated in the browser and only its SHA-256 is stored.
 */

const KEY_RE = /^[a-f0-9]{64}$/;
const MAX_COMMAND = 8000;
const MAX_OUTPUT = 20000;
const JOB_TTL_MS = 3 * 60 * 1000; // never run commands that waited longer than this
const ONLINE_MS = 30 * 1000;
const TICK_MS = 200; // how often long-polls re-check the database

async function isOnline(deviceId: string) {
  const [d] = await db.select({ lastSeen: devices.lastSeen }).from(devices).where(eq(devices.id, deviceId));
  return !!d?.lastSeen && Date.now() - d.lastSeen.getTime() < ONLINE_MS;
}

// Long-poll a job until it finishes or `ms` elapses.
async function waitJob(id: number, deviceId: string, ms: number) {
  const until = Date.now() + ms;
  for (;;) {
    const [job] = await db
      .select()
      .from(jobs)
      .where(and(eq(jobs.id, id), eq(jobs.deviceId, deviceId)));
    if (!job) return null;
    if (job.status === "done" || Date.now() + TICK_MS > until) {
      const online = job.status === "done" ? true : await isOnline(deviceId);
      return { id: job.id, status: job.status, output: job.output, exitCode: job.exitCode, online };
    }
    await sleep(TICK_MS);
  }
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" },
  });

const hashKey = (key: string) => createHash("sha256").update(key).digest("hex");
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

async function readKey(req: Request, url: URL) {
  let body: any = {};
  if (req.method === "POST") {
    try {
      body = await req.json();
    } catch {
      body = {};
    }
  }
  const key = String(body.key ?? url.searchParams.get("key") ?? "").toLowerCase();
  return { key: KEY_RE.test(key) ? key : null, body };
}

export default async (req: Request) => {
  const url = new URL(req.url);
  const action = url.pathname.split("/").pop();
  const { key, body } = await readKey(req, url);
  if (!key) return json({ error: "مفتاح الجهاز غير صالح" }, 400);
  const deviceId = hashKey(key);

  try {
    /* ---------- agent side ---------- */
    if (action === "poll" && req.method === "POST") {
      const kind = String(body.kind || "termux").slice(0, 20);
      const info = String(body.info || "").slice(0, 300);
      await db
        .insert(devices)
        .values({ id: deviceId, kind, info, lastSeen: new Date() })
        .onConflictDoUpdate({ target: devices.id, set: { kind, info, lastSeen: new Date() } });

      // Expire old pending commands so nothing stale runs after a reconnect.
      await db
        .update(jobs)
        .set({ status: "done", output: "[انتهت صلاحية الأمر قبل أن يستلمه الجهاز]", exitCode: -1, finishedAt: new Date() })
        .where(and(eq(jobs.deviceId, deviceId), eq(jobs.status, "pending"), lt(jobs.createdAt, new Date(Date.now() - JOB_TTL_MS))));

      const wait = Math.min(Math.max(Number(body.wait) || 20, 0), 25) * 1000;
      const until = Date.now() + wait;
      do {
        const claimed = await db
          .update(jobs)
          .set({ status: "running" })
          .where(and(eq(jobs.deviceId, deviceId), eq(jobs.status, "pending")))
          .returning({ id: jobs.id, command: jobs.command });
        if (claimed.length) return json({ jobs: claimed });
        if (Date.now() + TICK_MS > until) break;
        await sleep(TICK_MS);
      } while (true);
      await db.update(devices).set({ lastSeen: new Date() }).where(eq(devices.id, deviceId));
      return json({ jobs: [] });
    }

    // Lightweight heartbeat the agent sends every few seconds, even while a command runs.
    if (action === "ping" && req.method === "POST") {
      await db.update(devices).set({ lastSeen: new Date() }).where(eq(devices.id, deviceId));
      // Tell the agent which of its running commands the user asked to stop.
      const cancel = await db
        .select({ id: jobs.id })
        .from(jobs)
        .where(and(eq(jobs.deviceId, deviceId), eq(jobs.status, "cancel")));
      return json({ ok: true, cancel: cancel.map((c) => c.id) });
    }

    if (action === "cancel" && req.method === "POST") {
      const id = Number(body.id);
      if (!Number.isInteger(id)) return json({ error: "id غير صالح" }, 400);
      // Pending jobs are dropped right away; running ones are killed by the agent on its next ping.
      await db
        .update(jobs)
        .set({ status: "done", output: "[أُلغي الأمر قبل تنفيذه]", exitCode: -1, finishedAt: new Date() })
        .where(and(eq(jobs.id, id), eq(jobs.deviceId, deviceId), eq(jobs.status, "pending")));
      await db
        .update(jobs)
        .set({ status: "cancel" })
        .where(and(eq(jobs.id, id), eq(jobs.deviceId, deviceId), eq(jobs.status, "running")));
      return json({ ok: true });
    }

    if (action === "done" && req.method === "POST") {
      const id = Number(body.id);
      if (!Number.isInteger(id)) return json({ error: "id غير صالح" }, 400);
      await db
        .update(jobs)
        .set({
          status: "done",
          output: String(body.output ?? "").slice(-MAX_OUTPUT),
          exitCode: Number.isInteger(body.exitCode) ? body.exitCode : null,
          finishedAt: new Date(),
        })
        .where(and(eq(jobs.id, id), eq(jobs.deviceId, deviceId), inArray(jobs.status, ["running", "cancel", "pending"])));
      await db.update(devices).set({ lastSeen: new Date() }).where(eq(devices.id, deviceId));
      return json({ ok: true });
    }

    /* ---------- browser side ---------- */
    if (action === "status" && req.method === "GET") {
      const [d] = await db.select().from(devices).where(eq(devices.id, deviceId));
      if (!d) return json({ paired: false, online: false });
      const online = !!d.lastSeen && Date.now() - d.lastSeen.getTime() < ONLINE_MS;
      return json({ paired: true, online, kind: d.kind, info: d.info, lastSeen: d.lastSeen });
    }

    if (action === "run" && req.method === "POST") {
      const command = String(body.command || "").trim();
      if (!command) return json({ error: "الأمر فارغ" }, 400);
      if (command.length > MAX_COMMAND) return json({ error: "الأمر طويل جداً" }, 400);
      // Accept the command even if the phone dropped briefly: it waits (up to JOB_TTL_MS)
      // until the agent reconnects instead of failing immediately.
      const [d] = await db.select({ id: devices.id }).from(devices).where(eq(devices.id, deviceId));
      if (!d) return json({ error: "لم يتم ربط الجهاز بعد. اضغط «📱 ربط الجهاز» وشغّل agent.py على هاتفك." }, 409);
      const [job] = await db.insert(jobs).values({ deviceId, command }).returning({ id: jobs.id });
      // Wait here for quick commands so the browser gets the result in a single request.
      const wait = Math.min(Math.max(Number(body.wait) || 0, 0), 20) * 1000;
      const result = wait ? await waitJob(job.id, deviceId, wait) : null;
      return json(result || { id: job.id, status: "pending", online: await isOnline(deviceId) }, 201);
    }

    if (action === "result" && req.method === "GET") {
      const id = Number(url.searchParams.get("id"));
      if (!Number.isInteger(id)) return json({ error: "id غير صالح" }, 400);
      const result = await waitJob(id, deviceId, 20000);
      if (!result) return json({ error: "الأمر غير موجود" }, 404);
      return json(result);
    }

    if (action === "unpair" && req.method === "POST") {
      await db.delete(devices).where(eq(devices.id, deviceId));
      return json({ ok: true });
    }

    return json({ error: "Not found" }, 404);
  } catch (err: any) {
    console.error("device bridge error", err);
    return json({ error: "خطأ في الخادم، حاول مرة أخرى" }, 500);
  }
};

export const config = { path: "/api/device/*" };
