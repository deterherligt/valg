# Om-modal: Design Spec

**Date:** 2026-03-22
**Status:** Approved

## Overview

Add an "Om" button to the valg dashboard header that opens a centered overlay modal titled "Om Valg Dashboard". The modal explains what the dashboard does, how seat calculations work, where data comes from, and includes license and GitHub link — all in Danish. SVG arrows escape the modal edges and point to the corresponding dashboard elements behind the dimmed backdrop.

## Trigger

- A small `Om` button in the header, right side, next to the `.meta` sync status span.
- Styled identically to demo bar buttons: monospace, ghost style (`background: #21262d`, `border: 1px solid #30363d`, `border-radius: 4px`).
- Sets Alpine state `showAbout = true` on click.

## Modal

- Centered overlay, `max-width: 560px`, `max-height: 80vh`, scrollable body.
- Backdrop: full-viewport `position: fixed` div, `background: #000000bb`, `z-index: 100`.
- Modal panel: `position: fixed`, centered via `top: 50%; left: 50%; transform: translate(-50%, -50%)`, `z-index: 101`.
- Background `#161b22`, border `1px solid #30363d`, `border-radius: 6px`.
- Headline: `Om Valg Dashboard` in `#58a6ff`.
- Close: clicking backdrop sets `showAbout = false`; `@keydown.escape.window` also closes.

## Content Sections (Danish)

All text in Danish.

1. **Hvad er dette?**
   Live valgresultater hentet og beregnet i realtid. Dashboardet viser partistemmer, mandatfordeling og kandidatresultater efterhånden som de indrapporteres valgnatten.

2. **Datakilder**
   Data stammer fra valg.dk's offentlige SFTP-server (`data.valg.dk`). Serveren synkroniseres ca. hvert 5. minut via GitHub.

3. **Mandatberegning**
   Kredsmandater (135) beregnes med D'Hondt-metoden per storkreds — præcis. Tillægsmandater (40) beregnes approksimativt via modificeret Saint-Laguë nationalt minus kredsmandater. Den eksakte beregning kræver alle 8 storkredse og implementeres i v2.

4. **Disclaimer**
   Mandattal under valgnatten er estimater baseret på løbende optælling. Officielle resultater offentliggøres på [valg.dk](https://valg.dk).

5. **Kildekode**
   Kildekoden er tilgængelig på GitHub: [deterherligt/valg](https://github.com/deterherligt/valg).

6. **Licens**
   Udgivet under Beerware-licensen (Revision 42). Du må gøre hvad du vil med koden. Finder du den nyttig, er du velkommen til at købe mig en øl.

## SVG Arrows

An SVG layer is positioned `fixed`, full-viewport, `z-index: 102`, `pointer-events: none`. Only visible when `showAbout = true`.

Arrows are dashed, `stroke="#58a6ff"`, low opacity (`0.45`), with an arrowhead marker. They originate from the right or bottom edge of the modal panel and curve to the corresponding dashboard element behind the backdrop.

| Sektion | Target |
|---|---|
| Partistemmer & mandatberegning | Parties-kolonnen (venstre) |
| Kandidatoversigt | Candidates-kolonnen (midten) |
| Detaljer / D'Hondt | Detail-kolonnen (højre) |
| Datakilder | Header sync-status |

Arrow coordinates are expressed as viewport percentages so they work across screen sizes. Only the 4 sections above get arrows; Disclaimer, Kildekode, and Licens do not.

## Implementation Scope

- `valg/templates/index.html` — add `Om` button to header; add modal `<div>`; add SVG arrow layer
- `valg/static/app.js` — add `showAbout: false` to `dashboard()` state
- `valg/static/app.css` — modal overlay styles, backdrop, close button, section styles (~30 lines)

No new dependencies. No server changes. No routes.

## Out of Scope

- Animations/transitions on modal open/close
- Mobile layout (existing dashboard is desktop-only)
- Dynamic arrow positioning based on actual element coordinates (arrows use fixed viewport-% coordinates)
