# Changelog

All notable changes to the ZeroSink project will be documented in this file.

## [1.2.0] - 2026-06-30

### Changed

- **Upstream DNS Provider padlock badges**: Replaced the "Encrypted"/"Unencrypted" text labels in each provider card with a coloured padlock icon — green (`#32cd32`) closed lock for encrypted (DoH) providers, red open lock for unencrypted (Custom IPs). Added an inline legend in the section description to clarify the icon meanings.

## [1.1.0] - 2026-06-30

### Added

- **DNS-over-HTTPS (DoH) Upstream Forwarding**: ZeroSink now forwards all allowed DNS queries to the upstream resolver over **encrypted HTTPS (port 443)** rather than plain UDP/TCP port 53. This means your ISP can no longer inspect or log your DNS queries. Implemented using `httpx` with HTTP/2 support and the RFC 8484 `application/dns-message` wire format via HTTPS POST.

- **Upstream DNS Provider Picker**: Replaced the raw IP textarea in Settings with a visual provider card picker offering 5 pre-configured DoH providers:
  - **Cloudflare (1.1.1.1)** — Fast, privacy-first, GDPR compliant, no logging.
  - **Google (8.8.8.8)** — Highly reliable with global infrastructure.
  - **Quad9 (9.9.9.9)** — Privacy-focused with malware/threat blocking. Non-profit operated.
  - **NextDNS** — Configurable cloud DNS with analytics.
  - **AdGuard DNS** — Ad and tracker blocking at the DNS level.
  - **Custom IPs** — Falls back to plain UDP/TCP for manually-specified IP addresses; clearly labelled as unencrypted.
  - Each card displays an encrypted 🔒 / unencrypted ⚠️ badge so users understand the privacy tradeoff at a glance.

- **Transparent UDP Fallback**: If a DoH request fails (e.g. temporary network issue), ZeroSink silently retries using the provider's known IP over plain UDP to ensure DNS resolution never breaks.

- **New API endpoint** `GET /api/settings/dns-providers` — returns the full provider catalogue as JSON so the frontend is fully data-driven and new providers can be added without UI changes.

- **`upstream_dns_provider` settings key**: Persisted to the database alongside the existing `upstream_dns` custom IP field. Hot-reloaded into the DNS engine without a restart when changed via Settings.

## [1.0.9] - 2026-06-30


### Fixed

- **In-App Auto-Update Version Display Bug**: The `FRONTEND_VERSION` constant in `static/index.html` was stuck at `1.0.8` while `backend/config.py` had already been incremented to `1.0.9`. After an in-app update completed and the backend restarted, the `checkForUpdates()` logic detected this mismatch, cleared browser caches, and reloaded — but since the deployed HTML still had the old constant baked in, users continued to see the stale version number after refreshing. Fixed by syncing `FRONTEND_VERSION` to `1.0.9`.

### Added

- **In-App PWA Installation Modal**: Replaced reliance on the default mobile browser install banner with a custom lime-green themed modal built directly into the dashboard UI. The native `beforeinstallprompt` event is intercepted, its default behaviour prevented, and the event instance saved to Alpine.js state. A polished slide-down modal with an "Install ZeroSink App" button then presents itself after a short load delay. Clicking it triggers the native `.prompt()` handler; pressing "Not now" suppresses future prompts for the session via `localStorage`. The modal automatically hides once the PWA is successfully installed via the `appinstalled` event.

- **Context-Specific Web Block Pages**: Replaced blank browser "Cannot Reach" errors with informative, themed block pages served directly by ZeroSink's web server. The DNS engine now resolves blocked A/AAAA queries to the Pi's own LAN IP (`BLOCK_REDIRECT_IP`) instead of `0.0.0.0`, causing blocked HTTP/HTTPS traffic to land on the ZeroSink web server. The `/` route inspects the `Host` header: if the host is not a recognised dashboard hostname (e.g. `zerosink.local` or a bare IP), a dedicated dark-mode, lime-green branded `_build_blockpage()` HTML page is returned. The blockpage displays context-specific messaging:
  - Custom block rules: *"Access Denied: This Domain is Blocked"* with a red badge.
  - Downtime schedules: *"Browsing Paused: ZeroSink Downtime Schedule is Active"* with an amber badge.
  - Non-web infrastructure queries (MX, TXT, SRV, AAAA-only) continue to receive standard `0.0.0.0` sinkhole responses, preventing browser spinners from hanging.
  - Block-redirect responses use a 10-second TTL so that unblocking rules take effect immediately on the next DNS lookup.

- **Immediate DNS Cache Flush on CRUD**: Added a `flush_dns_cache()` function to `backend/dns_engine.py` that atomically clears the entire in-memory TTL DNS cache. This function is now called immediately after every CRUD operation on custom block rules, downtime schedules, and app-block toggles, ensuring the next incoming DNS packet evaluates the live database state with zero delay.

- **Deep App Bypass Hardening — Expanded Wildcard CDN Coverage**: Upgraded all entries in `APP_CATEGORIES` from plain-domain string matching to a full wildcard-aware pattern system (patterns prefixed with `*.` match any subdomain). Specific additions:
  - **WhatsApp** (new `social` sub-category): `*.whatsapp.net`, `*.whatsapp.com`, `*.fbcdn.net` — closes all Meta CDN fallback paths.
  - **Discord**: Added `*.discord.gg`, `*.discord.media`, `*.discordapp.net` to the existing gaming block.
  - **Netflix**: Added `*.nflximg.net` alongside existing `*.nflxvideo.net`, `*.nflxext.com`, `*.nflxso.net`.
  - **Disney+**: Added `*.disney-plus.net` and `*.media.dssott.com` to the existing Disney block.
  - **Epic Games / Fortnite**: Added `*.akamaized.net` to close Akamai CDN fallback for Fortnite content delivery.
  - All social, streaming, and gaming categories now include wildcard variants of their base domains, preventing cached-IP or direct-CDN bypass.
  - Added `ENGINE_NATIVE_DENY` list stub for future engine-level unconditional deny rules (currently documents WhatsApp/Meta infrastructure intent).
  - Added deployment note recommending a `conntrack` flush script on the system firewall when a device group transitions from Allowed to Blocked to break active TCP/UDP states.

### Changed

- **`ZEROSINK_WEB_PORT`** remains defaulted to port `80` with no external proxy or cloud routing reintroduced.
- `is_domain_in_category()` refactored to use a new `_domain_matches_pattern()` helper that correctly handles both bare-domain and `*.`-wildcard pattern entries in a single code path.
- `start_dns_servers()` now refreshes `BLOCK_REDIRECT_IP` at startup by re-running the local IP detection routine, ensuring the correct LAN interface IP is captured even if the network interface came up after Python module import.

### Fixed

- **Dashboard Content Clipping**: Fixed the main dashboard layout wrapper using `min-h-screen` which allowed the page to grow taller than the viewport, cutting off the bottom of the content. Changed the wrapper to `h-screen overflow-hidden` so the sidebar and main content area are always constrained to the viewport height. The main scroll area (`overflow-y-auto`) now handles all scrolling within the bounded flex container, ensuring all dashboard content is always reachable. Also removed the redundant `max-h-screen` from the `<main>` element since the parent now enforces the boundary correctly.

- **Session Lost After Updates/Restarts — JWT Secret Persistence**: Previously `JWT_SECRET` was generated with `secrets.token_hex(32)` on every process start, which meant all active JWT sessions were invalidated every time the service restarted (e.g. after an automatic update). Added `_load_or_create_jwt_secret()` in `backend/config.py` which saves a randomly generated secret to `data/.jwt_secret` on first boot and loads the same key on every subsequent start. Users will now stay logged in across updates and service restarts. The `ZEROSINK_JWT_SECRET` environment variable still takes priority for containerised deployments.

## [1.0.8] - 2026-06-29

### Changed
- **Subscribe Now reverted to Payment Link**: Reverted the Subscribe Now button back to a simple Stripe Payment Link. Since the Payment Link is already configured in the Stripe Dashboard to redirect to `http://zerosink.local/?session_id={CHECKOUT_SESSION_ID}`, no dynamic session creation or Stripe secret key on the Pi is required. The dynamic `/api/premium/create-checkout-session` endpoint remains available as an alternative.

## [1.0.7] - 2026-06-29

### Fixed
- **Python Scoping Bug**: Fixed `UnboundLocalError: cannot access local variable 'urllib'` in `verify_stripe_subscription` caused by importing `urllib.error` after the variable was already referenced. All imports moved to the top of the function using aliased names.
- **Stripe Redirect to Login Fix**: Replaced the static Stripe Payment Link with a dynamic Checkout Session created via the Stripe API. The backend now generates a real session with `success_url=http://zerosink.local/?session_id={CHECKOUT_SESSION_ID}`, ensuring Stripe redirects users back to the dashboard (not to login) with the session ID embedded for automatic activation.

## [1.0.6] - 2026-06-29

### Fixed
- **Cloudflare WAF Block Fix**: Added a standard browser User-Agent header and unverified SSL context to the Stripe subscription verification requests in the backend, resolving `403 Forbidden` errors triggered by Cloudflare's bot-detection (Error 1010) on default `urllib` signatures.

## [1.0.5] - 2026-06-29

### Added
- **Manual Update Check Button**: Added a "Check for Updates" button to the Software Update settings card, allowing users to manually force a GitHub update verification request at any time and get real-time toast feedback.

## [1.0.4] - 2026-06-29

### Added
- **Automatic License Activation**: Implemented automatic resolution and activation of premium licenses via Stripe Checkout Session IDs (`cs_...`). When redirected back to the dashboard, the app automatically verifies the checkout session, extracts the subscription ID, saves the license, and unlocks premium features instantly without manual copy-pasting.

## [1.0.3] - 2026-06-29

### Added
- **Fully Automatic Updates**: Added a background daemon thread that queries GitHub for new releases every 24 hours and automatically installs updates (pulling files, running pip dependencies, and running DB migrations) before restarting.
- **PWA Auto-Cache Buster**: Integrated version checking in the frontend UI. If the browser holds a cached PWA version of `index.html` that mismatches the running backend version, it automatically unregisters service workers, purges caches, and reloads the page to keep the client interface synchronized with the backend.

## [1.0.2] - 2026-06-29

### Changed
- **Stripe Checkout Link & JS Bug Fix**: Resolved a frontend runtime ReferenceError by correctly declaring `premiumCheckoutUrl` in the AlpineJS state variables, updating status loaders, and adding a static HTML fallback `href` for the Subscribe button to guarantee reliable checkout transitions.

## [1.0.1] - 2026-06-28

### Changed
- **Premium Card Layout Adjustment**: Increased the maximum width and adjusted the column proportions (60/40 split) of the Premium Add-on promotion card to prevent the Stripe Subscription ID text input field from being squashed.

## [1.0.0] - 2026-06-28

### Added
- Initial launch of ZeroSink, featuring:
  - Local DNS blocking and query logging.
  - Multi-user authentication with Two-Factor Authentication (2FA) support.
  - Premium Parental Controls (downtime schedules and app category blocking).
  - Secure Stripe-based subscription verification proxy via Cloudflare Workers.
