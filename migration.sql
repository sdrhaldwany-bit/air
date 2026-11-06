CREATE TABLE "hosted_bots" (
	"id" text PRIMARY KEY,
	"platform" text DEFAULT 'telegram' NOT NULL,
	"token" text NOT NULL,
	"username" text DEFAULT '' NOT NULL,
	"persona" text DEFAULT '' NOT NULL,
	"secret" text NOT NULL,
	"enabled" boolean DEFAULT true NOT NULL,
	"created_at" timestamp DEFAULT now(),
	"updated_at" timestamp DEFAULT now()
);
