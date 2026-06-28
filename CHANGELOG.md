# Changelog

All notable changes to the ZeroSink project will be documented in this file.

## [1.0.3] - 2026-06-28

### Added
- **Shield Shield Logo:** Updated all branding references (PWA manifest, favicon, Login Gate, Setup Gate, and vertical navigation sidebars) to feature the new vector shield badge logo enclosing the "ZS" characters.

### Changed
- **Dark Mode Contrast Improvements:** Fixed text/background contrast rules by applying neon lime green accents (`#8deb00` via `dark:bg-lime-400` / `dark:text-lime-400`) on dark text backgrounds (`text-neutral-950`), and correct blue/white combinations in light mode. Resolved typo `dark:text-lime-450` references to prevent default color dropbacks.

## [1.0.2] - 2026-06-28

### Added
- **Light Mode Blue Aesthetic:** Custom blue theme styling mapping in light mode (`#1d4ed8`) replacing all green highlight visual assets.
- **Login & Setup Theme Support:** Updated both Login Gate and Initial Security Setup Gate cards to dynamically support light and dark modes, integrating the "ZS" vector logo badge.

### Changed
- **Spacious Sidebar:** Expanded desktop sidebar width from `md:w-24` (96px) to `md:w-28` (112px) to prevent layout tightness, adjusting hover tooltips.
- **Blue Light Mode Chart:** Configured blocked queries chart border and area fill linear gradients to render in brand blue during light mode.

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
