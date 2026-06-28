# Changelog

All notable changes to the ZeroSink project will be documented in this file.

## [1.0.1] - 2026-06-28

### Added
- **Brand Identity & ZS Logo:** Custom "ZS" branding badge served dynamically as a vector icon from `/logo.svg`.
- **System Status Pill:** Live tracking of ad blocking protection using a dynamic indicator badge: `SYSTEM STATUS ACTIVE PROTECTED`.
- **Sparklines & Circular Progress Metrics:** Integrated visual SVG graphics for metrics: a line sparkline for Total Queries, and a dashboard-compatible SVG circular progress ring for Percent Blocked.

### Changed
- **Sleek Desktop Sidebar:** Collapsed navigation layout to a modern narrow sidebar featuring centered active outline glows and custom tooltips, maximizing horizontal content area.
- **Vibrant Neon Lime Theme:** Shifted dark mode to a premium high-contrast neon green theme (`#8deb00`) and custom deep navy-slate palette, while maintaining a complementary light mode green (`#2d6c00`) for WCAG AA compliance.
- **Dynamic Chart.js Gradients:** Styled the query trends line chart with canvas linear gradients, slate-colored background lines, and high-contrast labels.

## [1.0.0] - 2026-06-28

### Added
- **Initial PWA & Local Release**: Zero-infrastructure local deployment model using HTTP default on port 80.
- **Embedded mDNS Responder**: Seamless resolution of `http://zerosink.local` using the `zeroconf` responder.
- **PWA Manifest & Service Worker**: Full Progressive Web App support with `/manifest.json` and client-side shell caching for mobile and desktop standalone mode.
- **Ad-Blocking & DNS Engine**: Secure, lightweight DNS ad-blocker designed for Raspberry Pi Zero 2 W with 512MB RAM.
- **Group Management & Rules**: Relational groups to group clients by IP address or CIDR ranges.
- **2FA Security**: Two-Factor Authentication (TOTP) support.
