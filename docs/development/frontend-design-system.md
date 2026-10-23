# Frontend UI design system

The Vue 3 JavaScript workspace uses Apple-inspired typography, quiet surfaces and compact task layouts. The existing HTTP, Session, CSRF and domain contracts are unchanged.

## Tokens and layout

- `frontend/src/styles/apple-theme.css`: reusable `--apple-*` colors, type, borders, focus, easing and semantic token aliases. `design-system.css` imports it and supplies shared controls and layout.
- White cards on #f5f5f7, text #1d1d1f, blue #0071e3. Body secondary text uses #6e6e73 for readability; #86868b remains the secondary design token. Warning/error colors and the official venue-state palette are independent.
- Local system/PingFang fonts. Source-controlled outline SVG icons and abstract court lines; no external fonts, images or runtime icon service.
- Centered content has a 1120px maximum width and a glass top navigation. Below 800px the header uses two rows. Core tasks remain visible; administration and settings use native disclosure menus with active states and Escape handling.
- Cards use 24px corners (20px on phones), controls use 14px corners, and primary actions use pill buttons. Form cards do not scale on hover. Reduced motion is respected.
- References: [Apple](https://www.apple.com/) for typography, surfaces and navigation; [Linear](https://linear.app/features) for compact utility controls and progressive disclosure. This is a task workspace, so it does not reproduce promotional hero sections.

## Components and data ownership

- App: application shell and real, role-dependent routes. Native navigation menus close after navigation and return focus to their summary on Escape.
- PageHeader: title, description and action slot; optional heading ID.
- AppIcon: consistent decorative SVG, hidden from assistive technology.
- AuthFrame: shared brand/form layout, with the original route form as its slot.
- CredentialCard: status, dates and verification-record disclosure; props down and explicit action events up. The route owns all mutation, version and Token state.
- Home metrics and Credential search/filter derive only from existing API records. Unknown/loading/error metrics show a dash; enabled does not imply query/booking/payment permission. No-match is distinct from successful API-empty.
- Existing credentials and users precede creation forms and diagnostic charts. Main log filters remain visible; advanced filters and healthy collector details expand on demand. Warnings remain visible.
- Plans retain query, manual selection, Agent, saved queues and order querying. Queues precede execution settings. Mobile grids scroll horizontally without widening the page; complete times remain in accessible labels and titles.
- The Agent keeps its conversation controls and independent one-hour/two-hour preview groups. Empty previews say pending, readiness warnings remain explicit, and examples are available on demand.
- Model editing focuses the existing editor without replacing its state or handlers. Provider presets and explanations expand on demand. Model-test usage warnings stay visible.

The refresh does not add upstream, Agent or executor capabilities. Invitation uncertainty confirmation, Session invalidation fencing, password mutual exclusion, queue authorization and sensitive input cleanup remain intact.

## Verification

Run `npm test -- --run && npm run build`, `npm run test:e2e`, and `npm run test:e2e:planning` from `frontend/`. Browser evidence must be saved outside the repository. Geometric and interaction checks remain required; pixel equality is not a gate. Manually inspect screenshots at desktop and phone sizes. Synthetic browser fixtures and the isolated SQLite/fake-provider integration do not establish real upstream or model availability.
