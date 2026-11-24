# Help & Feedback: how it works

The **Help & Feedback** page (sidebar → Support) lets users:

- send a **feature request, suggestion, bug report or question**, with an optional 1–5 rating;
- leave an **e-mail address only if they want a reply**, and only with an explicit consent tick;
- choose whether to include **technical details** (app version, browser, screen size, GPU name;
  never audio files or file paths);
- **vote on planned features** ("I want this"), so the most-wanted features are built first;
- see **their own submissions** with a reference number (`FB-XXXXXXXX`);
- read the **FAQ**.

Every new message is **e-mailed to the product owners** when e-mail is configured. The
recipient addresses are private: they are never shown on the site, never sent to the browser,
never logged and never committed.

## Delivery modes

| Mode | When | What the user sees |
|---|---|---|
| **email** | The server has `FEEDBACK_NOTIFY_TO` + SMTP settings (website, or the owner's own PC) | "Sent to the team." |
| **local** | No mail settings (e.g. the Windows app on a user's PC) | "Saved on this computer" + a **Send via GitHub** button that opens a pre-filled public issue |

The Windows app cannot e-mail the owners directly: that would require putting a mail password
inside a public program, where anyone could extract it and send spam from the owners' account.
Once the cloud API exists, the desktop app should POST feedback to it and the server e-mails it.

## Turning on e-mail (owner's PC or a server)

1. Copy `.env.example` to `.env` in the project folder (`.env` is git-ignored), or set the
   same variables as **secrets** in the hosting platform.
2. Set `FEEDBACK_NOTIFY_TO` to the owners' addresses, comma-separated.
3. Gmail sending: `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=465`, `SMTP_SECURITY=ssl`,
   `SMTP_USER` = the sending Gmail address, `SMTP_PASSWORD` = a Gmail **App password**
   (Google Account → Security → 2-Step Verification → App passwords). Never the normal password.
4. Restart the app. The page then says "Sent to the team"; until the password is filled in, e-mail
   stays off and nothing is claimed.

For the website, a transactional mail service (Resend, Brevo, Amazon SES; free tiers of about
100–300 mails/day) is more reliable than Gmail. Only the `SMTP_*` values change.

## API

| Method & path | Purpose |
|---|---|
| `GET /api/support` | `{mode, delivery: "email"\|"local", version, github_issues, categories, tools}` (no addresses) |
| `POST /api/feedback` | `{category, tool, title, message, client, email?, contact_consent?, rating?, diagnostics?}` → `201 {id, created, status, delivery}`; 400 invalid, 429 rate-limited |
| `GET /api/feedback?client=` | The caller's own submissions (no e-mail, diagnostics or client id returned) |
| `GET /api/support/roadmap?client=` | Planned features with vote counts and the caller's own votes |
| `POST /api/support/roadmap/{id}/vote` | `{client, on}`. Idempotent: the latest vote per user wins |

`client` is an anonymous random id kept in the browser (localStorage). On the website it must be
replaced by the logged-in user id (server-side), so nobody can read another person's list.

## Security controls (all tested)

| Threat | Control | Test |
|---|---|---|
| Owners' addresses leaking | Only read server-side from env/.env; never in responses, HTML, logs, repo | `test_recipient_addresses_never_reach_the_browser`, `test_secrets_are_never_committed`, end-to-end mail check |
| E-mail header injection | Addresses validated (no CR/LF, commas, `<>`); subject and title forced to one line | `test_bad_or_injected_email`, `test_header_injection_through_title_is_impossible` |
| Malicious HTML / scripts (XSS) | Stored as plain text; UI escapes everything; e-mails are plain text only | `test_feedback_xss_is_rendered_as_text`, `test_plain_text_with_everything_needed` |
| Spam / flooding | 5 per 10 min per client, 20 per 10 min per IP, max 30 e-mails per hour, honeypot field for bots | `test_rate_limit_*`, `test_hourly_cap`, `test_honeypot_drops_bots_silently` |
| Cross-site request forgery (another site driving the app) | Every POST/PUT/PATCH/DELETE must be same-origin (`Origin`, `Sec-Fetch-Site`); `Origin: null` blocked | `TestGuards::test_cross_site_writes_are_blocked` (15 cases) |
| Huge requests | 64 KB limit on JSON requests (uploads have their own 1 GB limit) | `test_oversized_body_is_rejected` |
| Clickjacking / sniffing | `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` | `test_security_headers` |
| Mail credentials in transit | SSL/STARTTLS required; plaintext only to localhost (testing) | `test_bad_config_rejected`, `test_encrypted_connection_and_login` |
| Lost feedback when mail fails | Saved first, mailed in the background with one retry; result recorded | `test_background_send_retries_then_reports` |
| Secrets in logs | Mail errors log only the error type, never addresses or passwords | `test_background_send_retries_then_reports` |

Not claimed: "unbreakable". Remaining risks are listed below.

## For the cloud team (web deployment)

1. **Storage:** replace `LocalStore` with Postgres (same methods). Suggested tables:
   `feedback(id, created, user_id, category, tool, title, message, rating, email, diagnostics jsonb, status)`,
   `roadmap_votes(item, user_id, on, created, primary key(item, user_id))`,
   `feedback_events(id, feedback_id, type, result, created)`.
2. **Identity:** use the authenticated user id instead of the anonymous `client` id; keep
   anonymous submissions allowed but rate-limited by IP.
3. **Bots:** add Cloudflare Turnstile (free) to the form and verify the token server-side.
4. **Rate limits:** move from in-memory to the database or the edge (several API instances).
5. **Mail:** set `FEEDBACK_NOTIFY_TO` and `SMTP_*` as platform secrets; prefer a transactional
   mail service with SPF/DKIM on your domain.
6. **Origins:** set `AUDIO_STUDIO_ALLOWED_ORIGINS` to the site's https origin(s).
7. **Privacy:** state in the privacy policy that e-mail is optional and used only to reply;
   delete feedback e-mail addresses after, e.g., 12 months; allow users to delete their feedback.
8. **Admin view:** a protected page (owner role only) to read, tag and reply to feedback and to see
   vote counts.

## Remaining risks

- In-memory rate limits reset on restart and are per process (fine locally; move to DB/edge on the web).
- Anonymous client ids can be changed by a determined user; the per-IP limit and the hourly
  e-mail cap bound the damage. The website should require login or Turnstile.
- Gmail may throttle or block automated sending; use a transactional provider for the website.
