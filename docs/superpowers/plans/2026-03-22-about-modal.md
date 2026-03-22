# About Modal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an "Om" button to the dashboard header that opens a Danish-language about modal with SVG arrows pointing to dashboard sections.

**Architecture:** Pure frontend — Alpine.js state toggle, modal HTML in `index.html`, styles in `app.css`, SVG arrow layer overlaid on the full viewport. No server changes. Arrow coordinates are fixed viewport-percentage values.

**Tech Stack:** Alpine.js (already loaded), vanilla CSS, inline SVG

---

### Task 1: Add `showAbout` state and Om button

**Files:**
- Modify: `valg/static/app.js` (line 27 area — state declarations)
- Modify: `valg/templates/index.html` (line 14–23 — header)

No tests for this task (pure DOM state wiring, verified visually in Task 3).

- [ ] **Step 1: Add `showAbout` to Alpine state**

In `valg/static/app.js`, add `showAbout: false` to the state object alongside the other state properties (after `demo: { ... }` on line 27):

```js
showAbout: false,
```

- [ ] **Step 2: Add Om button to header**

In `valg/templates/index.html`, replace the `<header>` block (lines 14–23) with:

```html
<header class="header">
  <h1>valg</h1>
  <span class="meta" :class="{'pulsing': syncing}">
    <span x-text="lastSynced ? 'Synced ' + lastSynced : 'Waiting for sync…'"></span>
    <span x-show="districtsTotal > 0">
      &bull;
      <span x-text="(districtsReported || 0) + '/' + (districtsTotal || 0) + ' districts'"></span>
    </span>
  </span>
  <button class="about-btn" @click="showAbout = true">Om</button>
</header>
```

- [ ] **Step 3: Add Om button styles to app.css**

Append to `valg/static/app.css`:

```css
/* ── About button ─────────────────────────────────────────────── */
.about-btn {
  background: #21262d;
  border: 1px solid #30363d;
  border-radius: 4px;
  color: #c9d1d9;
  font-family: monospace;
  font-size: 0.85em;
  padding: 2px 10px;
  cursor: pointer;
  flex-shrink: 0;
}
.about-btn:hover { background: #30363d; }
```

- [ ] **Step 4: Verify button appears**

Run `python -m valg serve` (or however the dev server starts), open the dashboard, confirm the `Om` button appears on the right of the header and clicking it doesn't error (nothing visible yet — modal comes in Task 2).

- [ ] **Step 5: Commit**

```bash
git add valg/static/app.js valg/templates/index.html valg/static/app.css
git commit -m "feat: add Om button and showAbout state"
```

---

### Task 2: Add modal HTML and backdrop

**Files:**
- Modify: `valg/templates/index.html` — add modal + backdrop before `</body>`
- Modify: `valg/static/app.css` — add modal styles

- [ ] **Step 1: Add backdrop and modal to index.html**

Insert the following before `</body>` in `valg/templates/index.html`:

```html
<!-- About modal -->
<div class="about-backdrop" x-show="showAbout" @click="showAbout = false"
     @keydown.escape.window="showAbout = false"></div>

<div class="about-modal" x-show="showAbout">
  <div class="about-modal-header">
    <span class="about-modal-title">Om Valg Dashboard</span>
    <button class="about-close" @click="showAbout = false">✕</button>
  </div>
  <div class="about-modal-body">

    <div class="about-section">
      <div class="about-section-heading">Hvad er dette?</div>
      <p>Live valgresultater hentet og beregnet i realtid. Dashboardet viser partistemmer, mandatfordeling og kandidatresultater efterhånden som de indrapporteres valgnatten.</p>
    </div>

    <div class="about-section">
      <div class="about-section-heading">Datakilder</div>
      <p>Data stammer fra valg.dk's offentlige SFTP-server (<code>data.valg.dk</code>). Dashboardet synkroniserer ca. hvert 5. minut via GitHub.</p>
    </div>

    <div class="about-section">
      <div class="about-section-heading">Mandatberegning</div>
      <p>Kredsmandater (135) beregnes med D'Hondt-metoden per storkreds — præcis. Tillægsmandater (40) beregnes approksimativt via modificeret Saint-Laguë nationalt minus kredsmandater. Den eksakte beregning kræver data fra alle 8 storkredse og implementeres i v2.</p>
    </div>

    <div class="about-section">
      <div class="about-section-heading">Disclaimer</div>
      <p>Mandattal under valgnatten er estimater baseret på løbende optælling. Officielle resultater offentliggøres på <a href="https://valg.dk" target="_blank" rel="noopener">valg.dk</a>.</p>
    </div>

    <div class="about-section">
      <div class="about-section-heading">Kildekode</div>
      <p>Kildekoden er tilgængelig på GitHub: <a href="https://github.com/deterherligt/valg" target="_blank" rel="noopener">deterherligt/valg</a>.</p>
    </div>

    <div class="about-section">
      <div class="about-section-heading">Licens</div>
      <p>Udgivet under Beerware-licensen (Revision 42). Du må gøre hvad du vil med koden. Finder du den nyttig, er du velkommen til at købe mig en øl.</p>
    </div>

  </div>
</div>
```

- [ ] **Step 2: Add modal styles to app.css**

Append to `valg/static/app.css`:

```css
/* ── About modal ──────────────────────────────────────────────── */
.about-backdrop {
  position: fixed;
  inset: 0;
  background: #000000bb;
  z-index: 100;
}
.about-modal {
  position: fixed;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  z-index: 101;
  background: #161b22;
  border: 1px solid #30363d;
  border-radius: 6px;
  width: min(560px, 92vw);
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.about-modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid #30363d;
  flex-shrink: 0;
}
.about-modal-title {
  color: #58a6ff;
  font-size: 1.05em;
  font-weight: bold;
}
.about-close {
  background: none;
  border: none;
  color: #8b949e;
  cursor: pointer;
  font-size: 1em;
  padding: 2px 6px;
  border-radius: 3px;
}
.about-close:hover { background: #21262d; color: #c9d1d9; }
.about-modal-body {
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.about-section-heading {
  color: #c9d1d9;
  font-weight: bold;
  margin-bottom: 4px;
  font-size: 0.9em;
}
.about-section p {
  color: #8b949e;
  line-height: 1.6;
  margin: 0;
}
.about-section a { color: #58a6ff; }
.about-section a:hover { text-decoration: underline; }
.about-section code {
  background: #21262d;
  border-radius: 3px;
  padding: 1px 5px;
  font-size: 0.9em;
  color: #c9d1d9;
}
```

- [ ] **Step 3: Verify modal opens and closes**

Open the dashboard. Click `Om` — modal should appear with backdrop. Click backdrop or press `Esc` — should close. Click ✕ — should close. Scroll inside the modal if content overflows.

- [ ] **Step 4: Commit**

```bash
git add valg/templates/index.html valg/static/app.css
git commit -m "feat: add Om modal with content"
```

---

### Task 3: Add SVG arrow layer

**Files:**
- Modify: `valg/templates/index.html` — add SVG overlay before `</body>`
- Modify: `valg/static/app.css` — add SVG layer styles

The SVG is full-viewport, `pointer-events: none`, only visible when `showAbout = true`. Arrow coordinates use fixed `%` values calibrated to the typical desktop layout (parties col ~0–220px, candidates ~220–440px, detail ~440px+, header ~0–40px top).

- [ ] **Step 1: Add SVG arrow layer to index.html**

Insert immediately after the `</div><!-- /about-modal -->` closing tag, before `</body>`:

```html
<!-- SVG annotation arrows (shown with about modal) -->
<svg class="about-arrows" x-show="showAbout"
     viewBox="0 0 100 100" preserveAspectRatio="none"
     xmlns="http://www.w3.org/2000/svg">
  <defs>
    <marker id="arrowhead" markerWidth="6" markerHeight="6"
            refX="3" refY="3" orient="auto">
      <path d="M0,0 L0,6 L6,3 Z" fill="#58a6ff" opacity="0.55"/>
    </marker>
  </defs>
  <!-- Datakilder → header sync status (top-right area) -->
  <path d="M 35,28 C 35,15 70,8 82,5"
        stroke="#58a6ff" stroke-width="0.5" stroke-dasharray="1.5,1"
        fill="none" marker-end="url(#arrowhead)" opacity="0.45"/>
  <!-- Mandatberegning → parties col (left side) -->
  <path d="M 22,42 C 10,42 6,52 5,62"
        stroke="#58a6ff" stroke-width="0.5" stroke-dasharray="1.5,1"
        fill="none" marker-end="url(#arrowhead)" opacity="0.45"/>
  <!-- Kandidatoversigt → candidates col (centre) -->
  <path d="M 40,50 C 30,58 30,68 32,72"
        stroke="#58a6ff" stroke-width="0.5" stroke-dasharray="1.5,1"
        fill="none" marker-end="url(#arrowhead)" opacity="0.45"/>
  <!-- D'Hondt / detaljer → detail col (right) -->
  <path d="M 62,42 C 72,42 78,52 80,62"
        stroke="#58a6ff" stroke-width="0.5" stroke-dasharray="1.5,1"
        fill="none" marker-end="url(#arrowhead)" opacity="0.45"/>
</svg>
```

- [ ] **Step 2: Add SVG layer styles to app.css**

Append to `valg/static/app.css`:

```css
/* ── About arrows SVG ─────────────────────────────────────────── */
.about-arrows {
  position: fixed;
  inset: 0;
  width: 100vw;
  height: 100vh;
  z-index: 102;
  pointer-events: none;
  overflow: visible;
}
```

- [ ] **Step 3: Verify arrows render**

Open the modal. Four dashed blue arrows should appear curving from the modal area toward:
- Top-right (header sync)
- Left side (parties col)
- Centre (candidates col)
- Right side (detail col)

If any arrow looks obviously wrong (pointing off-screen, overlapping modal entirely), tweak the `d=` path coordinates in `index.html`. The `viewBox="0 0 100 100"` means coordinates are in viewport-percentage terms.

- [ ] **Step 4: Commit**

```bash
git add valg/templates/index.html valg/static/app.css
git commit -m "feat: add SVG annotation arrows to about modal"
```
