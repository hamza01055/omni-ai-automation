# Channel integration setup

Every channel works in **sandbox mode** with no credentials at all — the mock
adapter runs the full pipeline locally. This document covers switching a channel
to **live**.

A channel goes live the moment its credentials appear in `.env`. There is no
separate toggle. `GET /health/ready` reports the current mode for each channel,
and the Settings page shows the same thing.

---

## What is actually verified

Honesty about state, per development rule 17:

| Capability | WhatsApp | Instagram | Facebook | X |
|------------|----------|-----------|----------|---|
| Webhook signature verification | Tested | Tested | Tested | Implemented |
| Inbound parsing | Tested | Tested | Tested | Tested |
| Delivery receipts | Tested | n/a | Implemented | n/a |
| Outbound send | Implemented¹ | Implemented¹ | Implemented¹ | Implemented¹ |
| Content publishing | n/a² | Implemented¹ | Implemented¹ | Implemented¹ |

¹ Written against the platform's documented endpoint; not verified end to end,
because that needs a live Business account. Failures return the platform's own
error message rather than being swallowed.

² WhatsApp has no feed to publish to.

---

## WhatsApp Cloud API

**You need:** a Meta developer account, a Business app, and a phone number that
is not registered to the WhatsApp consumer app.

1. Create an app at <https://developers.facebook.com/apps> — type **Business**.
2. Add the **WhatsApp** product.
3. From *WhatsApp → API Setup*, copy the **Phone number ID** and the temporary
   access token. The temporary token expires in 24 hours; for anything beyond a
   first test, create a System User in Business Settings and issue a permanent
   token with `whatsapp_business_messaging` and `whatsapp_business_management`.
4. From *App Settings → Basic*, copy the **App Secret**.
5. Invent a verify token — any random string you also put in `.env`.

```bash
WHATSAPP_ACCESS_TOKEN=EAAG...
WHATSAPP_PHONE_NUMBER_ID=123456789012345
WHATSAPP_APP_SECRET=abc123...
WHATSAPP_VERIFY_TOKEN=pick-any-random-string
```

**Webhook.** Meta requires a publicly resolvable HTTPS URL. In development:

```bash
ngrok http 5678
```

Then in *WhatsApp → Configuration → Webhook*, set the callback URL to
`https://<your-tunnel>/webhook/whatsapp`, enter the same verify token, and
subscribe to the **messages** field.

Meta immediately sends a `GET` with `hub.challenge`. The workflow forwards it to
`/api/internal/webhooks/whatsapp`, which echoes the challenge as plain text —
JSON-wrapping it fails verification.

**Note on the 24-hour window.** WhatsApp only allows free-form replies within 24
hours of the customer's last message. Outside it you must use an approved
message template. Template support is not implemented; sends outside the window
will be rejected by Meta and recorded as failed.

---

## Instagram

**You need:** an Instagram *Professional* account linked to a Facebook Page.
Personal accounts cannot use this API.

1. In the same Meta app, add the **Instagram** product.
2. Link your Instagram Professional account to a Facebook Page.
3. Request these permissions: `instagram_basic`, `instagram_manage_messages`,
   and `instagram_content_publish` if you want to publish posts.
4. Generate a Page access token — Instagram messaging uses the Page token, not
   a separate Instagram one.

```bash
META_APP_ID=...
META_APP_SECRET=...
META_VERIFY_TOKEN=pick-any-random-string
INSTAGRAM_ACCESS_TOKEN=EAAG...
INSTAGRAM_BUSINESS_ACCOUNT_ID=178414...
```

Subscribe to `messages`, `messaging_postbacks` and `comments`. Callback URL:
`https://<your-tunnel>/webhook/instagram`.

**Two things that surprise people:**

- Instagram sends **two unrelated event shapes**: `messaging` for DMs and
  `changes` for comments. The adapter handles both and turns them into the same
  unified message, distinguished by `conversation_id` (`comment:{media_id}` for
  comments).
- **Feed posts require media.** The API is a two-step create-container /
  publish flow and needs a publicly reachable image or video URL — it cannot
  accept raw bytes and cannot post text alone. `publish_post()` returns a clear
  error rather than failing mysteriously at publish time.

Permissions require App Review before they work for accounts other than your own.

---

## Facebook Page

1. Add the **Messenger** product to the Meta app.
2. Under *Messenger → Settings*, generate a Page access token.
3. Permissions: `pages_messaging`, `pages_manage_metadata`, and
   `pages_manage_posts` for publishing.

```bash
FACEBOOK_ACCESS_TOKEN=EAAG...
FACEBOOK_PAGE_ID=1234567890
```

Subscribe to `messages` and `messaging_postbacks`. Callback URL:
`https://<your-tunnel>/webhook/facebook`.

The adapter drops echoes (`is_echo`) and any event whose sender is the Page
itself, so your own outbound messages do not loop back in as customer messages.

---

## X (Twitter)

**You need:** an X developer account with at least Basic tier. The Free tier
allows posting but not reading mentions.

1. Create a project and app at <https://developer.x.com>.
2. Set app permissions to **Read and Write**.
3. Generate consumer keys and an access token/secret pair.

```bash
X_API_KEY=...
X_API_SECRET=...
X_ACCESS_TOKEN=...
X_ACCESS_SECRET=...
X_BEARER_TOKEN=...
```

**Why X polls instead of receiving webhooks.** The Account Activity API — the
push-based product — is gated behind a separate approval process that most
accounts do not have. Rather than ship a webhook handler that would never fire,
WF-04 polls `GET /2/users/:id/mentions` every five minutes, and the backend
holds the cursor so a missed run catches up instead of reprocessing.

`XAdapter.parse_webhook()` *does* handle Account Activity payloads, so if you
are approved for it, switching is a trigger swap in WF-04 and nothing else.

**Other constraints:**

- Write operations need OAuth 1.0a user-context signing, not the bearer token.
  The adapter implements the signing.
- Posts are capped at 280 characters. The adapter refuses to send longer text
  rather than letting X truncate it — WF-04 passes `max_chars: 280` to the
  support agent so replies are drafted to fit.
- DMs need elevated access. `send_message()` replies in-thread as a public
  tweet, which is why WF-04 holds public replies to a stricter confidence bar
  than the DM channels.
- Media upload uses the older v1.1 endpoint and is not implemented.

---

## Verifying a channel went live

```bash
curl -s http://localhost:8000/health/ready | python3 -m json.tool
```

Each channel reports `"mode": "live"` or `"mode": "sandbox"` plus its
capabilities. A channel showing `sandbox` after you added credentials means the
backend container has not picked up the new `.env` — restart it:

```bash
docker compose restart backend
```

---

## Where credentials live

Environment variables today. The `channel_credentials` table exists with Fernet
encryption at rest and is wired into the security layer, but per-tenant
credential storage (letting each organization connect its own accounts through
the Settings UI) lands in Step 5. Until then, one deployment serves one set of
platform accounts.

Never commit `.env`. `.gitignore` excludes it; `.env.example` is the template.
