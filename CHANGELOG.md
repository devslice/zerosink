# Changelog

All notable changes to the ZeroSink project will be documented in this file.

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
