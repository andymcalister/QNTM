# QuantEdge — Setup Guide
# ======================

## Quick Start (Demo Mode — no database required)

1. Install dependencies:
   pip install -r requirements.txt

2. Run the app:
   streamlit run app.py

The app runs in demo mode using in-memory session state when Supabase is
not configured. All features work — data resets on page refresh.

---

## Production Setup with Supabase

1. Create a Supabase project at https://supabase.com

2. Run schema.sql in your Supabase SQL editor

3. Create .streamlit/secrets.toml:

   [default]
   SUPABASE_URL = "https://your-project.supabase.co"
   SUPABASE_ANON_KEY = "your-anon-key"
   SUPABASE_SERVICE_KEY = "your-service-key"
   APP_SECRET_KEY = "your-32-char-random-string"

4. Optional — email notifications (SendGrid):
   SENDGRID_API_KEY = "your-key"
   FROM_EMAIL = "alerts@yourdomain.com"

5. Optional — payments (Stripe):
   STRIPE_SECRET_KEY = "sk_live_..."
   STRIPE_PRICE_ID_PRO = "price_..."

6. Run: streamlit run app.py

---

## File Structure

quantedge/
├── app.py              # Main Streamlit application
├── db.py               # Database & auth layer (Supabase + demo fallback)
├── model_engine.py     # Quantitative scoring engine + hidden gem detection
├── schema.sql          # Supabase PostgreSQL schema
├── requirements.txt    # Python dependencies
├── .env.example        # Environment variable template
└── README.md           # This file

---

## Architecture

### Auth Flow
1. User registers → bcrypt password hash stored in Supabase
2. Login → verify hash → check MFA flag
3. If MFA enabled → TOTP verification (pyotp + Google Authenticator)
4. Session stored in st.session_state

### Model Engine
- run_full_scan(): scores all stocks cross-sectionally
- score_stock(): 5-pillar factor model (30% momentum, 25% quality, 20% volume, 15% value, 10% sentiment)
- detect_hidden_gems(): mid-cap filter + factor + insider + coverage screen
- Entry threshold: composite >= 60
- Exit trigger: composite < 45 OR momentum < 30

### Paywall Structure (Free vs Pro)
Free:
  - Market screener (full universe)
  - Basic BUY/HOLD/SELL signals
  - Portfolio tracking (≤10 holdings)
  - Backtest results (read-only)

Pro ($29/month via Stripe):
  - Hidden Gems detection
  - Email + push notifications on signal changes
  - Unlimited portfolio holdings
  - Real-time live price rescans
  - Backtest API access
  - Priority support

Institutional (custom pricing):
  - Everything in Pro
  - API access for model outputs
  - Custom universe upload
  - White-label option

### Notification Flow
1. Model runs daily scan (cron job or Streamlit Cloud scheduled run)
2. Compare new signals to previous signals stored in signal_log table
3. For any holding with signal change → insert notification record
4. If user has email=true and plan=pro → SendGrid API email
5. In-app notifications shown in Alerts tab

### Security
- Passwords: bcrypt (cost factor 12) — NOT SHA-256
- MFA: TOTP (RFC 6238) via pyotp, QR code via qrcode library
- Sessions: Streamlit session_state + Supabase JWT
- RLS: Row-level security on all user tables
- HTTPS: enforced by Streamlit Cloud / your deployment

---

## Upgrade Path (Free → Paid)

When ready to monetise:
1. Set up Stripe account + create Pro product ($29/month)
2. Add STRIPE_SECRET_KEY and STRIPE_PRICE_ID_PRO to secrets
3. The "Upgrade to Pro" button in Account → Plan will route to Stripe Checkout
4. Stripe webhook updates user.plan in Supabase on successful payment
5. Plan check: is_pro() function in app.py gates Pro features

## Deployment (Streamlit Cloud)

1. Push to GitHub (private repo)
2. Connect at share.streamlit.io
3. Add secrets in Streamlit Cloud dashboard
4. Deploy — free tier supports this app comfortably

---

## Disclaimer

QuantEdge is a quantitative research platform providing factor analysis scores
for informational and educational purposes only. It does not constitute
investment advice under the Investment Advisers Act of 1940 or any other law.
Factor scores are cross-sectional rankings — not buy/sell recommendations.
Past model performance does not guarantee future results. Always consult a
qualified financial adviser before making investment decisions.
