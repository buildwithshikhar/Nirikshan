# Accessibility pass (target: WCAG 2.1 AA)

Automated and code-level checks only. **No manual screen-reader test has been done**; see the last
section. Nothing here is a conformance claim.

## What was done

* Skip link (first tab stop) to `<main id="main">`; landmarks: `nav` (Primary), `header`, `main`, `aside`.
* After a client-side navigation the document title is set from the page `<h1>` and focus moves to
  `<main>` unless the user is already inside a field.
* Visible focus: a 3px orange outline with offset on every focusable element (`:focus-visible` plus
  form controls); the earlier `outline-none` on inputs was removed. Orange on navy is 5.8:1 to 6.5:1.
* Form controls have labels (`aria-label` or a wrapping label); icon-only dots are `aria-hidden`.
* Tables: `<caption class="sr-only">`, `scope="col"` on every column header, the empty actions
  header has hidden text. The SVG timeline is a `group` whose bars are focusable buttons (Enter/Space) and is
  followed by a text table with the same data (screen-reader alternative).
* Live regions: the API status pill, job stage text (announced on stage change, not per percent),
  job progress is a `progressbar` with `aria-valuetext`, analysis result notes, custody chain result,
  time-assumption save message; errors use `role="alert"`.
* Empty states with guidance, error states, and loading skeletons (`role="status"` "Loading ...").
* Persistent, sticky banners (`StatusBanners`, mounted in `Layout`): **SYNTHETIC** (evidence flagged
  from the image banner, or a `DEMO-SYNTHETIC...` case; list pages note that the workspace contains
  demo cases) and **TIMEZONE UNKNOWN** (any acquired evidence without a P5 time assumption, with a
  link to set it).
* `prefers-reduced-motion` honoured.

## Contrast (computed, `python scripts/contrast.py`)

| Pair | Ratio | Result |
|---|---|---|
| slate-100 on navy-900 / navy-800 | 16.55 / 14.73 | pass |
| slate-300 on navy-800 | 10.87 | pass |
| slate-400 on navy-800 / navy-900 (hints, placeholders) | 6.30 / 7.07 | pass |
| accent (orange) text on navy-900 / navy-800 | 6.47 / 5.76 | pass |
| emerald-400, amber-300, red-400 on navy-800 | 8.40, 11.19, 5.84 | pass |
| chips: emerald-200/emerald-900, amber-200/amber-900, slate-300/slate-700 | 7.58, 7.28, 6.97 | pass |
| navy-900 on amber-400 (SYNTHETIC banner), red-200 on red-900 (timezone banner) | 10.86, 6.93 | pass |
| **old** slate-500 on navy-800 (hint text, 15 uses) | 3.39 | failed, now slate-400 |
| **old** white on orange (buttons, active nav) | 2.80 | failed, now navy-900 text (6.47) |
| **old** red-500 on navy-800 | 4.29 | failed (only used as a status dot, not text) |

Button hover is now a lighter orange (`#fb923c`) so dark text keeps its contrast.

## Automated results

`frontend/e2e/a11y.spec.ts` runs axe-core (`@axe-core/playwright`, tags wcag2a, wcag2aa, wcag21a,
wcag21aa) on the dashboard, cases, case detail, analysis (Hikvision with parser panel and clips,
Dahua, raw), custody log, timeline and analytics pages with the SYNTHETIC demo case, and **fails on any
serious or critical violation**. A self-test proves the gate can fail (it flags a known low-contrast,
unlabelled input). Result on the final code: 0 serious/critical on all 9 pages.
Minor/moderate findings: none were reported under those tags (the test prints any it sees). Axe
rules outside those tags (best-practice) are not gated. The contrast table above was found by
calculation before the first axe run; no "before" axe numbers exist.

## Known gaps and plan

* Colour is not the only signal for status in most places (text status is always shown), but the
  timeline bars rely on colour and position for gap/overlap shading; the text tables list the same
  gaps and overlaps.
* The video preview uses native controls without captions (no audio content exists).
* Touch-target size (2.5.5, AAA) was not assessed.
* 200% zoom/reflow was checked only by layout inspection of the Tailwind classes, not tested.
* Plan: add axe to CI on the preview build; run a manual pass (below) before any external demo.

## What a manual screen-reader test still needs

NVDA + Firefox/Chrome (Windows), VoiceOver + Safari (macOS), TalkBack/VoiceOver iOS at phone width:
whether the sticky banners are announced at the right moment and not repeated on every navigation;
whether the job-stage live region is announced politely without chatter; reading order and table
navigation of the long hash/offset cells; the SVG timeline's button labels; focus after the route
change and after cancel/failure; browser zoom to 200% and 400%; Windows high-contrast mode; and a
keyboard-only run of the full case workflow (acquire, analyze, assume timezone, export).
