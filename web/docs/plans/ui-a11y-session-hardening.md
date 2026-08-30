# UI Accessibility and Session Hardening

## Problem

The browser-safe BFF UI already keeps credentials and signing material out of
the browser, but session expiry and CSRF rejection are currently presented as
ordinary operational errors. A stale React session can remain mounted after a
`401 ui_session_required` or `403 csrf_invalid`, and error regions do not
receive keyboard focus. The visual system has a generic focus outline, but it
does not yet define a complete, high-contrast disabled and focus treatment for
desktop and mobile keyboard users.

## Public seams

- Native login, logout, role-selection, audit/dispute, and revocation controls.
- `AvalProvider`, which owns transient role and CSRF material in React memory.
- Stable BFF error presentations returned by `UiBffGateway`.
- The emitted Vite artifact and visible DOM/status regions.

## Approach

1. Add a small session-recovery policy that classifies only the stable BFF
   error codes requiring reauthentication.
2. Centralize protected React-state clearing and apply it to logout, expired
   sessions, and invalid CSRF responses without automatic retries.
3. Give the error rail programmatic focus, explicit accessible relationships,
   and assertive announcement; keep loading and successful command feedback in
   polite status regions.
4. Strengthen explicit labels, keyboard landing points, focus-visible rings,
   disabled styling, and reduced-motion behavior without changing the existing
   AVAL visual language.
5. Verify the public seams test-first, then perform real desktop and mobile
   keyboard QA against the production build.

## Rejected approaches

- Refreshing or replaying a failed mutation automatically: unsafe for CSRF and
  idempotent payment-adjacent commands.
- Persisting session recovery material in browser storage: violates the BFF
  design and creates a second credential store.
- Reloading the whole page on `401`/`403`: hides the stable error guidance and
  is unnecessary once React state is cleared deterministically.
- Adding a fixture fallback for unavailable reads: would misrepresent runtime
  availability.
- Redesigning the interface: the task is accessibility and resilience, so the
  existing evidence-room identity remains intact.

## Verification

- `npm test`
- `npm run build`
- `npm run lint`
- Desktop keyboard-only QA for login, logout, role selection, audit/dispute,
  and operator revocation.
- Mobile viewport QA for focus visibility, labels, status/error regions,
  disabled controls, overflow, DOM, console, and retained input values.
- Production artifact scan for mock modules and credential/proof-shaped data.

## Outcome

All 37 web tests, the TypeScript/Vite production build, and lint pass with no
warnings. Desktop QA at 1440×900 and mobile QA at 390×844 confirmed explicit
labels, visible focus, no horizontal overflow, readable audit/dispute
projections, cleared retained inputs, and zero console warnings or errors.

A rotated CSRF hash produced a real `403 csrf_invalid`: the operator projection
and transient command state were removed, the login view returned, and focus
moved to the safe error alert. Replacing the QA session store produced a real
`401 ui_session_required` with the same fail-closed transition. Stopping the
runtime during an auditor reload preserved the already-authorized projection,
displayed a focused read-only retry error, and never loaded fixture data.

The production artifact regression remains green for mock modules, direct
agent/admin endpoints, browser signing material, persistent browser-storage
APIs, synthetic proof values, and vault-token prefixes. No backend, migration,
BFF contract, or Python E2E file changed. Browser automation verified DOM,
retained inputs, console, and server logs; storage safety is enforced at source
and emitted-artifact seams because the browser control surface intentionally
does not inspect cookie or storage contents.
