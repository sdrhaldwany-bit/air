import { pgTable, serial, text, timestamp, integer, boolean, index } from "drizzle-orm/pg-core";

// A paired phone (Termux / Pydroid). `id` is the SHA-256 of the secret device key.
export const devices = pgTable("devices", {
  id: text().primaryKey(),
  kind: text().notNull().default("termux"),
  info: text().notNull().default(""),
  lastSeen: timestamp("last_seen").defaultNow(),
  createdAt: timestamp("created_at").defaultNow(),
});

// Commands queued from the chat and executed by the device agent.
export const jobs = pgTable(
  "jobs",
  {
    id: serial().primaryKey(),
    deviceId: text("device_id").notNull().references(() => devices.id, { onDelete: "cascade" }),
    command: text().notNull(),
    status: text().notNull().default("pending"), // pending | running | cancel | done
    output: text().notNull().default(""),
    exitCode: integer("exit_code"),
    createdAt: timestamp("created_at").defaultNow(),
    finishedAt: timestamp("finished_at"),
  },
  (t) => [index("jobs_device_status_idx").on(t.deviceId, t.status)]
);

// A Telegram bot hosted serverless on Netlify: it replies to people automatically
// through a webhook, with no phone / Termux needed. `id` is the SHA-256 of the token
// and is used in the public webhook path. The token is stored so the function can
// answer incoming messages when the browser is closed.
export const hostedBots = pgTable("hosted_bots", {
  id: text().primaryKey(),
  platform: text().notNull().default("telegram"),
  token: text().notNull(),
  username: text().notNull().default(""),
  persona: text().notNull().default(""),
  secret: text().notNull(),
  enabled: boolean().notNull().default(true),
  createdAt: timestamp("created_at").defaultNow(),
  updatedAt: timestamp("updated_at").defaultNow(),
});
