# Ghost Security Monitoring

The Cloudflare Worker `norestrictions-api` provides owner-authenticated defensive security telemetry.

## Owner endpoints

- `GET /owner/security` — returns the latest 100 security events, active temporary IP blocks, and the 24-hour event count.
- `POST /owner/security/analyze` — submits recent event metadata (event type, country/city estimate, HTTP method, route, timestamp) to the existing Workers AI Qwen model for a defensive Arabic risk summary.

Both endpoints require the configured `OWNER_PASSWORD` as a Bearer token and an allowed site Origin. They are not public visitor endpoints.

## Existing protections retained

- Request-size guard and allowed-Origin checks.
- Per-IP rate limiting (60 API requests/minute; 4 image requests/minute).
- Temporary 15-minute IP blocks after repeated rate-limit violations.
- Security alert throttling and optional Telegram alerts.
- D1-backed event and security state storage.

## Privacy and limitations

Telemetry is limited to operational security metadata such as IP address, approximate network-derived country/city, user-agent, HTTP method, route, event type, and timestamp. Do not collect passwords, private files, or chat contents for security analytics. IP geolocation is approximate and must not be treated as a precise physical location.

AI analysis is advisory; existing deterministic rate-limit and block rules remain responsible for enforcement. This does not guarantee protection against every attack. Review Cloudflare WAF, bot protection, DDoS controls, backups, and periodic security testing separately.
