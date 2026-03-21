# Demo Control Bar Design

**Date:** 2026-03-21

## Overview

Add a demo control bar to the valg dashboard. The bar sits between the header and the three-column layout, is only visible when demo mode is active (`enabled: true` from `/demo/state`), and lets an operator control the running scenario without using `curl`.

## Layout

```
┌─────────────────────────────────────────────────────┐
│ valg                              Synced 20:13       │  ← existing header
├─────────────────────────────────────────────────────┤
│ [running]  [kv2025 ▾]  [⏸ Pause]  [↺ Restart]  [1×▾]│  ← demo bar (new)
├─────────────────────────────────────────────────────┤
│  Parties  │  Candidates  │  Details                 │  ← existing columns
├─────────────────────────────────────────────────────┤
│ Feed strip                                           │  ← existing feed
└─────────────────────────────────────────────────────┘
```

The bar is hidden (`x-show`) when `demo.enabled` is false. No layout shift — it is not rendered at all on a live election.

## Data Flow

- `app.js` polls `GET /demo/state` every 5 seconds (independent of the existing 10s data poll).
- Response shape: `{enabled, scenario, scenarios, speed, state, step_index, step_name, steps_total}`
- `demo.enabled === false` → bar hidden
- `demo.state` drives the state badge colour and the pause/resume button label

## Controls

| Control | Element | Action |
|---------|---------|--------|
| State badge | `<span>` | Display only — blue=running, amber=paused, grey=done/idle |
| Scenario selector | `<select>` | `POST /demo/control {action:"set_scenario", scenario:"..."}` then `{action:"restart"}` |
| Pause / Resume | `<button>` | `POST /demo/control {action:"pause"}` or `{action:"resume"}` based on `demo.state` |
| Restart | `<button>` | `POST /demo/control {action:"restart"}` |
| Speed selector | `<select>` | Options: 1×, 2×, 5×, 10×, 60× — `POST /demo/control {action:"set_speed", speed:N}` |

All control requests use `fetch` with `method: 'POST'`, `Content-Type: application/json`. Errors are silently ignored (fire-and-forget) — the next poll will reflect the actual state.

## Code Changes

### `valg/static/app.js`

Add to Alpine data object:
```js
demo: { enabled: false, state: 'idle', scenario: '', scenarios: [], speed: 1 },
```

Add to `init()`: call `this._fetchDemoState()` and `setInterval(() => this._fetchDemoState(), 5000)`.

Add methods:
- `_fetchDemoState()` — fetch `/demo/state`, update `this.demo`
- `demoControl(action, extra)` — POST `/demo/control {action, ...extra}`
- `demoSetScenario(name)` — calls `demoControl('set_scenario', {scenario:name})` then `demoControl('restart')`
- `demoSetSpeed(speed)` — calls `demoControl('set_speed', {speed: parseFloat(speed)})`

### `valg/templates/index.html`

Add demo bar between `</header>` and `<div class="columns">`:

```html
<div class="demo-bar" x-show="demo.enabled">
  <span class="demo-badge" :class="'demo-badge--' + demo.state" x-text="demo.state"></span>
  <select x-model="demo.scenario" @change="demoSetScenario($event.target.value)">
    <template x-for="s in demo.scenarios" :key="s">
      <option :value="s" x-text="s"></option>
    </template>
  </select>
  <button @click="demoControl(demo.state === 'running' ? 'pause' : 'resume')"
          x-text="demo.state === 'running' ? '⏸ Pause' : '▶ Resume'"></button>
  <button @click="demoControl('restart')">↺ Restart</button>
  <select @change="demoSetSpeed($event.target.value)">
    <template x-for="s in [1,2,5,10,60]" :key="s">
      <option :value="s" :selected="demo.speed === s" x-text="s + '×'"></option>
    </template>
  </select>
</div>
```

### `valg/static/app.css`

Add styles for `.demo-bar`, `.demo-badge`, `.demo-badge--running`, `.demo-badge--paused`, `.demo-badge--done`. Match the existing dark theme (`#1c2128` background, `#30363d` borders, `#c9d1d9` text).

## What Does Not Change

- The existing 10s data poll (`_poll`)
- All `/api/*` routes
- The three-column layout, header, feed strip
- Backend demo engine, `/demo/state`, `/demo/control`

## Out of Scope

- Step progress indicator (step N / total)
- Stop button (pause is sufficient)
- Mobile/responsive layout adjustments
