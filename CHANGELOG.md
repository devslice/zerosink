# Changelog

All notable changes to the ZeroSink project will be documented in this file.

## [1.0.8] - 2026-06-28

### Changed
- **Modern Line Sidebar Icons:** Revamped dashboard navigation icons — Dashboard, Query Log, and How to Setup now use `fa-regular` (outline) style. Group Manager uses a modern `fa-sitemap` icon, while Parental Controls and Settings remain as solid for reliable rendering in FA6 Free.
- **Theme Toggle on Login & Setup Gates:** Added a sun/moon theme toggle button to both the Login Gate and Initial Security Setup Gate, allowing users to switch between light and dark mode before authenticating. Both gates now respect the active theme with light-mode-aware backgrounds, cards, and form inputs.

## [1.0.7] - 2026-06-28

### Changed
- **Shield-Halved Icon Migration:** Replaced the custom "ZS" vector logo SVG with a Font Awesome `fa-shield-halved` icon across the Login Gate, Setup Gate, and both desktop/mobile sidebar layouts.
- **Backend Logo Endpoint Update:** Updated the `/logo.svg` inline SVG path to a simplified solid shield geometry rendered in brand lime `#32cd32`.

## [1.0.6] - 2026-06-28

### Changed
- **Pure Shield Logo:** Removed the "ZS" lettering from the vector shield logo across both the ad blocker application and the main website, making it just the clean shield icon.
- **Theme Color Definitions:** Re-defined dark theme background, card, border, and input colors (`darkbg`, `darkcard`, `darkborder`, `darkinput`) to use neutral values (`#0a0a0a`, `#141414`, `#262626`, `#1a1a1a`) to purge any navy-slate blue tint. Added custom neutral levels (`750`, `850`, `855`) to Tailwind configuration.
- **Dark Mode Color Audit:** Purged remaining blue highlight styles, badges, active indicators, and chart components in Dark Mode, replacing them with brand lime `#32cd32` accents.
- **Enforced Dark Mode Default:** Added default theme initialization in localStorage to ensure Dark Mode is active on first visit.

## [1.0.5] - 2026-06-28

### Added
- **Explicit Brand Accent Configuration:** Configured the primary brand color `#32CD32` (Lime Green) under the `brand-lime` namespace in the Tailwind config.

### Changed
- **Dark Mode Color Purge:** Purged all blue colors from the dark layout (including DNS cache metrics, whitelist status badges, privacy discover category badges, and social media icons), replacing them with variations of `#32CD32`.
- **Accessible Multi-Theme Button Colors:** Overhauled 18 primary action buttons to dynamically adapt to light and dark modes. In light mode, they render as professional corporate blue with high-contrast white text (`text-white`); in dark mode, they transition to brand lime `#32CD32` with bold dark text (`text-neutral-950 font-bold`) for WCAG accessibility compliance.
- **Improved Interactive States:** Adjusted active indicators, focus rings, checkboxes, and switch toggles to render with brand accent `#32CD32` when dark mode is enabled.
- **Chart.js Brand Alignment:** Updated the blocked queries line chart and linear area fills to render in `#32CD32` during dark mode.
- **Toast Notifications:** Styled success toast indicators with high contrast (`bg-blue-600` on light mode, and `#32CD32` on dark mode with dark bold text) for optimal readability.
- **Vector Brand Logo & PWA Manifest:** Updated the hardcoded logo SVG path/text fill and the PWA manifest theme color in the backend to `#32cd32`.

## [1.0.4] - 2026-06-28


### Changed
- **Forced Dark-Themed Login & Setup:** Standardized the Login Gate and Initial Security Setup Gate to be permanently dark-themed (`bg-neutral-950` with `bg-neutral-900` card and borders). This ensures that the bright lime green brand color `#8deb00` always renders with high-contrast text (`text-neutral-950` on buttons) and maximum readability.

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
