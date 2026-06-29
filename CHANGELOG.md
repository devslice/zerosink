# Changelog

All notable changes to the ZeroSink project will be documented in this file.

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
