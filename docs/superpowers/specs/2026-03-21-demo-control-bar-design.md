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

Add to `init()`:
```js
await this._fetchDemoState()
setInterval(() => this._fetchDemoState(), 5000)
```

Add methods:
```js
async _fetchDemoState() {
  const resp = await fetch('/demo/state').catch(() => null)
  if (!resp || !resp.ok) return
  this.demo = await resp.json()
},

async demoControl(action, extra = {}) {
  await fetch('/demo/control', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({action, ...extra}),
  }).catch(() => null)
  await this._fetchDemoState()
},

async demoSetScenario(name) {
  await this.demoControl('set_scenario', {scenario: name})
  await this.demoControl('restart')
},

async demoSetSpeed(speed) {
  await this.demoControl('set_speed', {speed: parseFloat(speed)})
},
```

### `valg/templates/index.html`

Add demo bar between `</header>` and `<div class="columns">`:

```html
<div class="demo-bar" x-show="demo.enabled">
  <span class="demo-badge" :class="'demo-badge--' + demo.state" x-text="demo.state"></span>
  <select @change="demoSetScenario($event.target.value)">
    <template x-for="s in demo.scenarios" :key="s">
      <option :value="s" :selected="s === demo.scenario" x-text="s"></option>
    </template>
  </select>
  <button
    x-show="demo.state === 'running' || demo.state === 'paused'"
    @click="demoControl(demo.state === 'running' ? 'pause' : 'resume')"
    x-text="demo.state === 'running' ? '⏸ Pause' : '▶ Resume'">
  </button>
  <button @click="demoControl('restart')">↺ Restart</button>
  <select @change="demoSetSpeed($event.target.value)">
    <template x-for="s in [1,2,5,10,60]" :key="s">
      <option :value="s" :selected="parseFloat(demo.speed) === s" x-text="s + '×'"></option>
    </template>
  </select>
</div>
```

Notes:
- No `x-model` on scenario select — `@change` drives the action directly, avoiding double-fire
- Pause/Resume button hidden when `demo.state === 'idle'` or `'done'` (only valid in running/paused states)
- Speed `:selected` uses `parseFloat(demo.speed) === s` to handle float/int comparison

### `valg/static/app.css`

Add styles for `.demo-bar`, `.demo-badge` and state variants:

| Class | Colour |
|-------|--------|
| `.demo-badge--running` | Blue (`#1f6feb`) |
| `.demo-badge--paused` | Amber (`#9e6a03` bg, `#e3b341` text) |
| `.demo-badge--done` | Grey (`#30363d` bg, `#8b949e` text) |
| `.demo-badge--idle` | Grey (same as done) |

Bar background: `#1c2128`, border-bottom: `1px solid #30363d`, padding: `6px 14px`.

## What Does Not Change

- The existing 10s data poll (`_poll`)
- All `/api/*` routes
- The three-column layout, header, feed strip
- Backend demo engine, `/demo/state`, `/demo/control`

## Out of Scope

- Step progress indicator (step N / total)
- Stop button (pause is sufficient)
- Mobile/responsive layout adjustments
