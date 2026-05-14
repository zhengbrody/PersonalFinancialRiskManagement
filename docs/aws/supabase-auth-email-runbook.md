# Supabase Auth Email — Beta Runbook

_Last updated: 2026-05-13_

## TL;DR

Two states you can be in. Pick one:

| Mode | When | Setting | Email needed? |
|------|------|---------|--------------|
| **A. Open signup** (beta default) | Right now, while only friends test | Supabase Auth → "Confirm email" **OFF** | No |
| **B. Verified signup** (pre-launch) | Before opening to strangers | "Confirm email" **ON** + Resend SMTP | Yes |

**Today, after the latest deploy:** the Login page now detects which mode
you're in and shows the right success message. If you're in Mode A, new
accounts auto-sign-in immediately. If you're in Mode B, the user sees a
"check your inbox" message **and** a self-serve "Resend confirmation"
button — so a missing email no longer means "create a new account."

---

## Why this matters

Right now you can sign up with `a13105129007@gmail.com` and log in
without seeing a confirmation email. That's not a bug — it means
Supabase's "Confirm email" toggle is OFF for the project (or its built-in
SMTP is rate-limited; both look identical to the user). For beta this is
fine. **Before letting strangers in, this MUST be ON**, otherwise any
spammer can register `nobody-i-dont-own@gmail.com` and burn your LLM
budget.

---

## Mode A — Keep "Confirm email" OFF for beta (default today)

Steps to verify the current project setting:

1. Open https://supabase.com/dashboard/project/byfpmmfduteajblqpuuw/auth/providers
2. Click **Email** provider
3. Scroll to **"Confirm email"** — should be OFF
4. **Save** (even if unchanged) to clear any stuck state

Pros: zero friction for beta testers. Cons: anyone can register with any
address; you eat the LLM cost.

The deployed Login page handles this case: signup → instant signed-in
state → redirect to dashboard. No "check your inbox" message shown.

---

## Mode B — Turn "Confirm email" ON + use Resend SMTP (pre-launch)

Supabase's built-in SMTP has two hard problems:

1. **Rate limit: 3 emails / hour**. One round of testing breaks it.
2. **Sender `noreply@mail.app.supabase.io`** is on most spam blocklists.
   QQ Mail, NetEase, 163, Outlook routinely silently drop it.

The fix is to swap in a real transactional provider. Resend is the
simplest free tier (3000 emails/month free, no credit card).

### Step 1 — Resend account + API key
1. Sign up at https://resend.com (use the same Gmail you own).
2. Dashboard → **API Keys** → **Create API Key**, name it `mindmarket-supabase`.
3. Copy the key. You'll paste it into Supabase next; you can't re-display it.

### Step 2 — Add `mindmarket.app` as a verified domain in Resend
1. Dashboard → **Domains** → **Add Domain** → enter `mindmarket.app`.
2. Resend gives you 3 DNS records (1 SPF TXT, 1 DKIM TXT, 1 DMARC TXT).
3. Add them at Porkbun:
   - https://porkbun.com/account/domain/mindmarket.app → DNS Records → Add
   - Type, Host, Answer fields exactly as Resend displays them.
4. Back in Resend, click **Verify**. Propagation: 5–15 min usually.

### Step 3 — Wire Supabase to Resend
1. https://supabase.com/dashboard/project/byfpmmfduteajblqpuuw/auth/templates
2. Click **SMTP Settings** in the side nav.
3. Toggle **Enable Custom SMTP** = ON. Fill in:

   | Field | Value |
   |---|---|
   | Sender email | `noreply@mindmarket.app` |
   | Sender name | `MindMarket AI` |
   | Host | `smtp.resend.com` |
   | Port | `465` |
   | Username | `resend` |
   | Password | _your Resend API key from step 1_ |
   | Minimum interval | `60s` (still useful for abuse rate limiting) |

4. **Save**.

### Step 4 — Turn Confirm email ON
1. Auth → Providers → Email → **Confirm email = ON**.
2. Auth → URL Configuration:
   - **Site URL**: `https://mindmarket.app`
   - **Redirect URLs** (add all three):
     - `https://mindmarket.app`
     - `https://mindmarket.app/`
     - `https://www.mindmarket.app`
3. **Save**.

### Step 5 — Test from a fresh incognito window
1. https://mindmarket.app → Sign Up tab → register with a fresh email.
2. Expect: "Account created. Check your inbox…" message.
3. Inbox should receive a `MindMarket AI <noreply@mindmarket.app>` email
   within ~30 seconds.
4. Click the link → redirected to `https://mindmarket.app` (signed in).
5. Try to sign in BEFORE clicking the link with a second fresh address:
   should see "Your email isn't confirmed yet" + a Resend button.

---

## When users say "I didn't get the email"

After the latest deploy the user can self-serve:
- Sign in attempt with unconfirmed email → resend button appears.
- Sign up success message → "Didn't receive?" expander with a resend button.

If they still don't get it, in order of likelihood:
1. **Spam folder** — most common (especially for `.qq.com`, `.163.com`)
2. **Resend dashboard → Logs** — search by `to:` address; check `bounced` or `complained`
3. **DNS not propagated** — verify SPF/DKIM at https://mxtoolbox.com/SuperTool.aspx
4. **Resend free tier exhausted** — 3000/month, you'd have to be doing a lot

---

## Cost

- Resend free tier: 3000 emails/month → enough for ~100 signups + ~30 password resets/day
- Resend Pro: $20/mo for 50k emails — switch when free tier breaks
- DNS records at Porkbun: free
- Mode A: $0

---

## Rollback

If Resend goes down or you want to retry from scratch:
1. Supabase Auth → SMTP Settings → **Enable Custom SMTP = OFF**
2. You're back on Supabase's built-in SMTP (3/hour limit returns).
3. Re-enable Custom SMTP and re-paste API key to recover.

There is no data loss path — Auth users live in Supabase regardless of
which SMTP they were created under.
