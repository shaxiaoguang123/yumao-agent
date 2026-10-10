# Frontend UI design system

The six existing pages use a clean sports operations workspace. The UI is implemented in Vue 3 JavaScript and keeps the existing HTTP, Session and CSRF contracts.

## Tokens and layout

- `frontend/src/styles/design-system.css`: shared colors, type, spacing, borders, focus, forms and responsive shell.
- Brand #12644b, dark green #123e31, accent #d6ed87, canvas #f5f7f5; semantic warning/error colors are independent.
- Local system/PingFang fonts. Source-controlled outline SVG icons and abstract court lines; no external fonts, images or runtime icon service.
- Desktop: 224px navigation and flexible main content. Below 1024px: top navigation; mobile administrator links use two columns. Every label stays whole and controls target 44px.
- Reduced motion is respected; transitions only provide lightweight feedback.

## Components and data ownership

- App: application shell and real, role-dependent routes. No future feature links.
- PageHeader: title, description and action slot; optional heading ID.
- AppIcon: consistent decorative SVG, hidden from assistive technology.
- AuthFrame: shared brand/form layout, with the original route form as its slot.
- CredentialCard: status, dates and verification-record disclosure; props down and explicit action events up. The route owns all mutation, version and Token state.
- Home metrics and Credential search/filter derive only from existing API records. Unknown/loading/error metrics show a dash; enabled does not imply query/booking/payment permission. No-match is distinct from successful API-empty.

No BookingPlan, ReservationIntent, Worker, Agent, booking or payment functionality is implemented by this UI change. Invitation uncertainty confirmation, Session invalidation fencing, password mutual exclusion and sensitive input cleanup remain intact.

## Verification

Run Vitest, production build and `npm run test:e2e` from frontend. Browser evidence must be saved outside the repository. Geometric and interaction checks remain required; pixel equality is not a gate. Real screenshot inspection is necessary for UI acceptance.
