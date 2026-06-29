# Changelog

All notable changes to the ZeroSink project will be documented in this file.

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
