# Water-Surface Cast (水面投石演出) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a full-screen WebGL water surface as the app's backdrop (ripples on tap, a 5-second stone-casting choreography, per-screen intensity) with a zero-dependency ping-pong height-field simulation, and degrade gracefully to a static background when WebGL or motion is unavailable.

**Architecture:** A single imperative `WaterLayer` module owns a fixed full-screen `<canvas>` behind the existing React UI (the `#root` app). It exposes `water.drop(x, y, strength)`, `water.calm()`, `water.setIntensity(mode)`, `water.destroy()` and runs its own `requestAnimationFrame` loop entirely outside React's render cycle. The React UI stays as-is except for: (a) mounting/destroying `WaterLayer` on app mount/unmount, (b) calling `water.setIntensity()` when the screen changes, (c) a document-level pointer listener that raises ripples on non-UI taps, and (d) the cast screen passing each stone's splash coordinates to `water.drop()` and drawing the yao "light line" over the pond. Panels become semi-transparent so the water shows through.

**Tech Stack:** Raw WebGL1 (with WebGL2 auto-upgrade), inline GLSL shader strings, `OES_texture_half_float` / `OES_texture_half_float_linear` extensions for the height field, no libraries. Everything lives inside the existing single `index.html` and is inlined into `dist/index.html` by `node build.js`.

## Global Constraints

- **Single-file distribution.** All new code (shaders as JS string literals, the water module, CSS) lives in `index.html`. `node build.js` must still produce a self-contained `dist/index.html`. No new files are shipped, no new `<script src>`.
- **Zero runtime dependencies.** No three.js, no npm, no CDN. Raw WebGL only.
- **`build.js` `$&` gotcha.** `build.js` only inlines the three known `<script src>` tags via a *function* replacement; do not introduce new external scripts. Shader strings live inside the existing inline `<script>` and are never passed through `String.replace` with a `$`-containing replacement, so `$&`/`$1` cannot bite us — but never write shader-injection code that does `html.replace(tag, shaderString)` with a raw string second argument.
- **Palette.** Water tints and highlights use the existing palette: 和紙ベージュ base `#f4f2ec` / page bg `#e6e3dd`, 藍 accent `#2f3a6e`. Exact colors and opacities are tuned on-device; the values in this plan are the documented starting point.
- **Fallback is mandatory and lossless.** When WebGL context creation fails, required extensions are missing, OR `matchMedia('(prefers-reduced-motion: reduce)').matches` is true → no canvas is created and the app behaves exactly as today. The divination flow (cast → 成卦 → result → share) must work identically with water ON or OFF.
- **Performance ceilings.** Simulation grid ≤ 512×512. Device-pixel-ratio for the render canvas capped at 1.5. Loop fully stops on `document.hidden`. After a period of no interaction the sim drops to a low-cost "idle shimmer" power-saving mode.
- **Reduced-motion.** The existing coin-animation `prefers-reduced-motion` handling (CSS at `index.html:73-76`) is preserved unchanged. Water simply does not initialize under reduced-motion.
- **No test harness exists.** There is no npm/package.json/test runner — only `node build.js`. Every task's verification is: (1) `node build.js` exits 0 with the expected size/leftover log line, and (2) a concrete manual browser check with an explicit expected observation. Where a task adds a temporarily-exposed debug hook, remove it in that same task before its commit.
- **Commit trailer.** Every commit message ends with:
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
- **Do not commit this plan file.** The orchestrator commits it after review.

## File Structure

- **Modify only `index.html`.** All work is additive within the single source file:
  - `<style>` block (`index.html:38-77`) — add water canvas positioning, panel translucency, and a `.kz-water-off` opt-out class.
  - The inline app `<script>` (starts `index.html:86`) — add, *above* `const e = React.createElement;` (line 88), a self-contained IIFE that defines and installs `window.__kzWater` (the `WaterLayer` instance or a no-op fallback). Then wire React to it inside the `App` class (mount/destroy, per-screen intensity, document ripple listener, stone splash + yao light line).
- `README.md` gets no change (the build model is unchanged). Do **not** create new files.

Rationale: the codebase is intentionally one large file with `React.createElement` aliased to `e()`. Per writing-plans "follow established patterns," we keep it single-file rather than restructuring. The water module is isolated behind a small imperative API so it can hold in-context on its own.

## The imperative water API (contract shared by all tasks)

All later tasks consume this exact interface. It is created in Task 1 and progressively filled in.

```
window.__kzWater : {
  ok: boolean,                       // true if a live WebGL surface is running; false = fallback no-op
  drop(xCss, yCss, strength),        // xCss,yCss = viewport CSS px (clientX/clientY); strength ~0.2..1.5
  calm(),                            // damp the surface quickly toward flat
  setIntensity(mode),                // mode: 'idle' | 'ask' | 'cast' | 'result'
  poke(),                            // reset the idle/power-save timer (called on any interaction)
  destroy()                          // stop RAF, drop GL resources, remove canvas + listeners
}
```

Fallback build (WebGL/extensions missing or reduced-motion): `ok:false` and every method is a no-op function. React code always calls methods unconditionally — it never has to branch on `ok` except where explicitly noted.

Intensity modes drive two internal scalars (`this.wind`, ambient drop rate) and a damping factor:
- `idle`: very low ambient shimmer, strong damping (power-save).
- `ask` / `history` / `reference` / `detail` / `about`: quiet ambient shimmer.
- `cast`: full liveliness (the star of the show).
- `result`: near-frozen (damping high, ambient ~0) so reading isn't disturbed.

---

### Task 1: WaterLayer skeleton + capability detection + fallback

Creates the canvas, the WebGL context (WebGL2 preferred, WebGL1 + half-float extensions fallback), the module singleton, and the no-op fallback. No simulation yet — just a cleared translucent canvas proving the layer mounts behind the UI and that fallback triggers correctly.

**Files:**
- Modify: `index.html` `<style>` block (`index.html:38-77`) — add water canvas + fallback CSS.
- Modify: `index.html` inline `<script>` — insert the water IIFE immediately before `const e = React.createElement;` (currently line 88).
- Modify: `index.html` `App` class — mount in `componentDidMount` (`index.html:328`), destroy in `componentWillUnmount` (`index.html:375`).

**Interfaces:**
- Consumes: nothing (first task).
- Produces: `window.__kzWater` object with the full method surface listed in "The imperative water API". In this task `drop/calm/setIntensity/poke` are stubs that only log via an internal `_dbg` flag; `destroy` fully works. `ok` is correctly true/false. Also produces the internal class shape later tasks extend: `WaterLayer` with `this.gl`, `this.canvas`, `this.isGL2`, `this.simSize`, `this.dpr`, and lifecycle methods `_resize()`, `_frame(t)`, `_start()`, `_stop()`.

- [ ] **Step 1: Add water + panel-neutral CSS to the `<style>` block**

Insert the following just before the closing `</style>` at `index.html:77`. (Panel translucency is added in Task 6; here we only position the canvas and define the opt-out.)

```css
  /* water surface: fixed full-viewport, behind the app UI */
  #kz-water { position: fixed; inset: 0; width: 100%; height: 100%; z-index: 0; pointer-events: none; display: block; }
  /* when water is active, let the page background show the canvas rather than a flat fill */
  body.kz-water-on { background: #e6e3dd; }
  .kz-wrap { position: relative; z-index: 1; }
  /* fallback / reduced-motion: no canvas, unchanged flat look */
  body.kz-water-off #kz-water { display: none; }
```

- [ ] **Step 2: Insert the WaterLayer IIFE above `const e = React.createElement;`**

Insert this block at `index.html:88`, immediately before `const e = React.createElement;`. This task fills in only detection, canvas creation, resize, an empty clear-only frame loop, visibility handling, and the fallback. Simulation methods are stubs to be replaced in later tasks (each later task says exactly which method body to replace).

```javascript
/* ===================== WATER LAYER (imperative, React-independent) ===================== */
(function installWater() {
  var reduceMotion = false;
  try { reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (_) {}

  // no-op fallback used when WebGL/extensions are unavailable or motion is reduced
  function makeNoop() {
    return { ok: false, drop: function(){}, calm: function(){}, setIntensity: function(){}, poke: function(){}, destroy: function(){} };
  }

  if (reduceMotion) { window.__kzWater = makeNoop(); return; }

  // try to obtain a usable GL context + the extensions the sim needs
  function tryContext() {
    var canvas = document.createElement('canvas');
    var opts = { alpha: true, antialias: false, depth: false, stencil: false, premultipliedAlpha: true, preserveDrawingBuffer: false, powerPreference: 'low-power' };
    var gl2 = canvas.getContext('webgl2', opts);
    if (gl2) {
      // WebGL2 has half-float RTT built in; still need linear filtering of float textures
      var lin2 = gl2.getExtension('OES_texture_float_linear');
      return { gl: gl2, canvas: canvas, isGL2: true, halfType: gl2.HALF_FLOAT, linearOK: !!lin2 };
    }
    var gl = canvas.getContext('webgl', opts) || canvas.getContext('experimental-webgl', opts);
    if (!gl) return null;
    var hf = gl.getExtension('OES_texture_half_float');
    if (!hf) return null; // no half-float RTT → bail to fallback (Canvas 2D path is out of scope per spec)
    var hfl = gl.getExtension('OES_texture_half_float_linear');
    return { gl: gl, canvas: canvas, isGL2: false, halfType: hf.HALF_FLOAT_OES, linearOK: !!hfl };
  }

  var ctx = null;
  try { ctx = tryContext(); } catch (_) { ctx = null; }
  if (!ctx) { window.__kzWater = makeNoop(); return; }

  function WaterLayer(ctx) {
    this.gl = ctx.gl;
    this.canvas = ctx.canvas;
    this.isGL2 = ctx.isGL2;
    this.halfType = ctx.halfType;
    this.linearOK = ctx.linearOK;
    this.ok = true;

    this.canvas.id = 'kz-water';
    document.body.insertBefore(this.canvas, document.body.firstChild);
    document.body.classList.add('kz-water-on');

    this.dpr = Math.min(1.5, window.devicePixelRatio || 1);
    this.simSize = 256;              // ping-pong grid resolution (raised toward 512 cap after profiling)
    this.wind = 0.0;                 // ambient liveliness (set by setIntensity)
    this.damping = 0.996;            // wave persistence (set by setIntensity)
    this.mode = 'idle';
    this._pending = [];              // queued drops: {x,y,strength} in sim-space 0..1
    this._raf = 0;
    this._lastT = 0;
    this._idleSince = (typeof performance !== 'undefined' ? performance.now() : Date.now());
    this._powerSave = false;

    this._buildGL();                 // Task 2 fills this (buffers/programs/textures). Stub here.
    this._resize();
    this._onResize = this._resize.bind(this);
    window.addEventListener('resize', this._onResize);
    this._onVis = this._visibility.bind(this);
    document.addEventListener('visibilitychange', this._onVis);
    this._start();
  }

  // ---- lifecycle ----
  WaterLayer.prototype._start = function () {
    if (this._raf) return;
    var self = this;
    this._lastT = 0;
    var loop = function (t) { self._raf = requestAnimationFrame(loop); self._frame(t); };
    this._raf = requestAnimationFrame(loop);
  };
  WaterLayer.prototype._stop = function () {
    if (this._raf) { cancelAnimationFrame(this._raf); this._raf = 0; }
  };
  WaterLayer.prototype._visibility = function () {
    if (document.hidden) this._stop(); else this._start();
  };

  WaterLayer.prototype._resize = function () {
    var w = Math.round(window.innerWidth * this.dpr);
    var h = Math.round(window.innerHeight * this.dpr);
    if (this.canvas.width === w && this.canvas.height === h) return;
    this.canvas.width = w; this.canvas.height = h;
    this.canvas.style.width = window.innerWidth + 'px';
    this.canvas.style.height = window.innerHeight + 'px';
    this.gl.viewport(0, 0, w, h);
  };

  // ---- stubs replaced in later tasks ----
  WaterLayer.prototype._buildGL = function () { /* Task 2: create quad buffer, sim + render programs, ping-pong FBOs */ };
  WaterLayer.prototype._simStep = function () { /* Task 2: run one ping-pong height-field update */ };
  WaterLayer.prototype._render = function () {
    // Task 3 replaces this with the water render pass. Placeholder: clear to a translucent water tint.
    var gl = this.gl;
    gl.clearColor(0.945, 0.933, 0.902, 1.0); // ~#f1eee6
    gl.clear(gl.COLOR_BUFFER_BIT);
  };
  WaterLayer.prototype._frame = function (t) {
    if (!this._lastT) this._lastT = t;
    this._lastT = t;
    // power-save: after 6s of no interaction, ease into idle shimmer
    var now = (typeof performance !== 'undefined' ? performance.now() : Date.now());
    this._powerSave = (now - this._idleSince) > 6000;
    this._simStep();
    this._render();
  };

  // ---- public API (stubbed here; filled by later tasks) ----
  WaterLayer.prototype.drop = function (/* xCss, yCss, strength */) { /* Task 4 */ this.poke(); };
  WaterLayer.prototype.calm = function () { /* Task 4 */ };
  WaterLayer.prototype.setIntensity = function (/* mode */) { /* Task 4 */ };
  WaterLayer.prototype.poke = function () { this._idleSince = (typeof performance !== 'undefined' ? performance.now() : Date.now()); this._powerSave = false; };
  WaterLayer.prototype.destroy = function () {
    this._stop();
    try { window.removeEventListener('resize', this._onResize); } catch (_) {}
    try { document.removeEventListener('visibilitychange', this._onVis); } catch (_) {}
    try { document.body.classList.remove('kz-water-on'); } catch (_) {}
    try { if (this.canvas && this.canvas.parentNode) this.canvas.parentNode.removeChild(this.canvas); } catch (_) {}
    this.gl = null; this.canvas = null;
  };

  try { window.__kzWater = new WaterLayer(ctx); }
  catch (_) { window.__kzWater = makeNoop(); }
})();
```

- [ ] **Step 3: Mount reference + destroy in the App class**

In `componentDidMount` (`index.html:328`), add as the *first* statement inside the method body:

```javascript
    this.water = window.__kzWater || { ok: false, drop(){}, calm(){}, setIntensity(){}, poke(){}, destroy(){} };
```

In `componentWillUnmount` (`index.html:375`, currently just removes the popstate listener and aborts AI), add at the end of the method:

```javascript
    if (this.water && this.water.destroy) this.water.destroy();
```

- [ ] **Step 4: Build and verify the bundle**

Run: `node build.js`
Expected stdout (size will vary slightly): `wrote dist/index.html (NNN KB), remaining external <script src=: 0`
The `remaining external <script src=: 0` MUST read `0` — if not, the water IIFE accidentally introduced a `<script src>`; fix it.

- [ ] **Step 5: Manual browser verification (water ON)**

Open `dist/index.html` in Chrome (desktop). Expected:
- Page renders the ask screen inside the phone frame exactly as before.
- Behind the frame, on the page margin (the `#e6e3dd` area on wide screens), a full-viewport canvas is present filled with a pale beige water tint (`~#f1eee6`), slightly lighter than the page bg — confirming the canvas mounted behind the UI at `z-index:0` while `.kz-wrap` sits at `z-index:1`.
- In DevTools console: `window.__kzWater.ok` → `true`. `document.querySelector('#kz-water')` → the canvas element, first child of `<body>`.
- Switch tabs away and back: no console errors (the RAF loop stopped on hide, restarted on show).

- [ ] **Step 6: Manual browser verification (fallback)**

In DevTools, emulate reduced motion: open Command Menu → "Rendering" → set "Emulate CSS prefers-reduced-motion" to "reduce", then hard-reload. Expected:
- No `#kz-water` canvas in the DOM (`document.querySelector('#kz-water')` → `null`).
- `window.__kzWater.ok` → `false`.
- App looks and behaves exactly as the current production build (flat `#e6e3dd`/white). The ask → cast flow still works.
Reset the emulation afterward.

- [ ] **Step 7: Commit**

```bash
git add index.html dist/index.html
git commit -m "$(cat <<'EOF'
feat(water): WaterLayer skeleton with WebGL detection and reduced-motion fallback

Fixed full-screen canvas mounts behind the app; clears to a water tint.
Falls back to a no-op (no canvas) when WebGL/half-float or motion is unavailable.
Loop pauses on document.hidden. Simulation to follow.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Height-field wave simulation (ping-pong shaders)

Replaces the `_buildGL` and `_simStep` stubs with a classic two-texture ping-pong height field: each step reads the current + previous height textures and writes the next height into a third target, applying a discrete wave equation with damping. Queued drops (from `drop()`) are injected as gaussian bumps at the start of a step. Nothing is visible yet beyond a debug readout (the render pass is still the flat clear from Task 1), so this task verifies via a temporary debug visualization that is removed before commit.

**Files:**
- Modify: `index.html` water IIFE — replace `_buildGL` and `_simStep` stub bodies; add helper methods `_compile`, `_program`, `_makeHeightTex`, `_makeFBO`, `_injectDrops`, `_pushDrop`; add the sim GLSL strings; wire `drop()` to enqueue.

**Interfaces:**
- Consumes: `this.gl, this.isGL2, this.halfType, this.linearOK, this.simSize, this.damping, this.wind, this._pending, this._powerSave` (Task 1).
- Produces: after each `_simStep()`, `this.heightTex[this.cur]` holds the current height field (R channel = height, G channel = velocity/previous — see encoding below), `this.cur` is the index (0/1/2 ring) of the freshest texture, and `this.simFBO` machinery is ready for Task 3's render pass to sample `this.heightTex[this.cur]`. `_pushDrop(xSim, ySim, strength)` enqueues a drop in sim-space (0..1, y-down). `drop()` still maps CSS→sim in Task 4; here `_pushDrop` is the internal primitive.

Encoding: a single RG (or RGBA, R+G used) half-float texture per ring slot. R = height at step n, G = height at step n-1. The update shader computes height at n+1 from neighbors of R and the stored n-1 in G, then writes new R = n+1, new G = old R (n). This keeps the classic `2*h - hPrev + c^2*laplacian` integration in one pass with one sampled texture.

- [ ] **Step 1: Add GLSL sources and GL helpers to the water IIFE**

Inside the IIFE (top level, after `tryContext` is fine), add these version-agnostic shader sources and helpers. The `HEAD_VS`/`HEAD_FS` prefixes adapt GLSL between WebGL1 and WebGL2 so one source string works for both.

```javascript
  // GLSL preamble: make one source compile on both WebGL1 (GLSL ES 1.00) and WebGL2 (3.00 es).
  function shaderHeads(isGL2) {
    if (isGL2) {
      return {
        vs: '#version 300 es\n#define IN in\n#define OUT out\nprecision highp float;\n',
        fs: '#version 300 es\n#define IN in\n#define TEX texture\nprecision highp float;\nout vec4 fragColor;\n#define FRAG fragColor\n'
      };
    }
    return {
      vs: '#define IN attribute\n#define OUT varying\nprecision highp float;\n',
      fs: '#define IN varying\n#define TEX texture2D\nprecision highp float;\n#define FRAG gl_FragColor\n'
    };
  }

  var VS_QUAD =
    'IN vec2 aPos;\nOUT vec2 vUv;\n' +
    'void main(){ vUv = aPos * 0.5 + 0.5; gl_Position = vec4(aPos, 0.0, 1.0); }\n';

  // simulation update: R=height(n), G=height(n-1). Output R=height(n+1), G=old height(n).
  var FS_SIM =
    'IN vec2 vUv;\n' +
    'uniform sampler2D uState;\n' +
    'uniform vec2 uTexel;\n' +          // 1/simSize
    'uniform float uDamping;\n' +
    'uniform float uWind;\n' +          // ambient shimmer amplitude
    'uniform float uTime;\n' +
    'void main(){\n' +
    '  vec2 s = TEX(uState, vUv).rg;\n' +
    '  float h = s.r; float hPrev = s.g;\n' +
    '  float l = TEX(uState, vUv + vec2(-uTexel.x, 0.0)).r;\n' +
    '  float r = TEX(uState, vUv + vec2( uTexel.x, 0.0)).r;\n' +
    '  float u = TEX(uState, vUv + vec2(0.0, -uTexel.y)).r;\n' +
    '  float d = TEX(uState, vUv + vec2(0.0,  uTexel.y)).r;\n' +
    '  float lap = (l + r + u + d) - 4.0 * h;\n' +
    '  float next = (2.0 * h - hPrev) + 0.28 * lap;\n' +   // c^2 dt^2 = 0.28 (stable < 0.5)
    '  next *= uDamping;\n' +
    // faint ambient shimmer so the surface is never perfectly dead
    '  next += uWind * 0.0009 * sin((vUv.x*18.0 + vUv.y*22.0) + uTime*1.7);\n' +
    '  FRAG = vec4(next, h, 0.0, 1.0);\n' +
    '}\n';

  // drop injection: additive gaussian bump into the height (R) channel
  var FS_DROP =
    'IN vec2 vUv;\n' +
    'uniform sampler2D uState;\n' +
    'uniform vec2 uCenter;\n' +          // sim-space 0..1, y-down already flipped to uv space
    'uniform float uRadius;\n' +
    'uniform float uAmp;\n' +
    'void main(){\n' +
    '  vec4 st = TEX(uState, vUv);\n' +
    '  float dsq = dot(vUv - uCenter, vUv - uCenter);\n' +
    '  float bump = uAmp * exp(-dsq / (uRadius*uRadius));\n' +
    '  st.r += bump;\n' +
    '  FRAG = st;\n' +
    '}\n';

  function compile(gl, type, src) {
    var sh = gl.createShader(type);
    gl.shaderSource(sh, src); gl.compileShader(sh);
    if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
      var info = gl.getShaderInfoLog(sh); gl.deleteShader(sh);
      throw new Error('shader compile: ' + info);
    }
    return sh;
  }
  function program(gl, vsSrc, fsSrc) {
    var p = gl.createProgram();
    gl.attachShader(p, compile(gl, gl.VERTEX_SHADER, vsSrc));
    gl.attachShader(p, compile(gl, gl.FRAGMENT_SHADER, fsSrc));
    gl.bindAttribLocation(p, 0, 'aPos');
    gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) {
      var info = gl.getProgramInfoLog(p); gl.deleteProgram(p);
      throw new Error('program link: ' + info);
    }
    return p;
  }
```

- [ ] **Step 2: Replace the `_buildGL` stub body**

Replace `WaterLayer.prototype._buildGL = function () { /* Task 2: ... */ };` with:

```javascript
  WaterLayer.prototype._buildGL = function () {
    var gl = this.gl;
    var H = shaderHeads(this.isGL2);
    // full-screen triangle-strip quad
    this.quad = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, this.quad);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1, 1,-1, -1,1, 1,1]), gl.STATIC_DRAW);

    this.progSim  = program(gl, H.vs + VS_QUAD, H.fs + FS_SIM);
    this.progDrop = program(gl, H.vs + VS_QUAD, H.fs + FS_DROP);
    // Task 3 adds this.progWater (the visible render pass)

    this.uSim = {
      state: gl.getUniformLocation(this.progSim, 'uState'),
      texel: gl.getUniformLocation(this.progSim, 'uTexel'),
      damping: gl.getUniformLocation(this.progSim, 'uDamping'),
      wind: gl.getUniformLocation(this.progSim, 'uWind'),
      time: gl.getUniformLocation(this.progSim, 'uTime')
    };
    this.uDrop = {
      state: gl.getUniformLocation(this.progDrop, 'uState'),
      center: gl.getUniformLocation(this.progDrop, 'uCenter'),
      radius: gl.getUniformLocation(this.progDrop, 'uRadius'),
      amp: gl.getUniformLocation(this.progDrop, 'uAmp')
    };

    // ping-pong ring of 3 RGBA half-float textures + FBOs
    var N = this.simSize;
    var filter = this.linearOK ? gl.LINEAR : gl.NEAREST;
    this.heightTex = []; this.simFBO = [];
    for (var i = 0; i < 3; i++) {
      var tex = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, tex);
      var internal = this.isGL2 ? gl.RGBA16F : gl.RGBA;
      var fmt = gl.RGBA;
      gl.texImage2D(gl.TEXTURE_2D, 0, internal, N, N, 0, fmt, this.halfType, null);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, filter);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, filter);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      var fbo = gl.createFramebuffer();
      gl.bindFramebuffer(gl.FRAMEBUFFER, fbo);
      gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, tex, 0);
      this.heightTex.push(tex); this.simFBO.push(fbo);
    }
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    this.cur = 0;   // index of freshest state
    this._simReady = true;
    this._texel = 1.0 / N;
  };

  // bind the quad to attrib 0 and draw the full-screen triangle strip
  WaterLayer.prototype._drawQuad = function () {
    var gl = this.gl;
    gl.bindBuffer(gl.ARRAY_BUFFER, this.quad);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
  };
```

- [ ] **Step 3: Add drop-injection + queue primitives**

Add these methods (anywhere after `_buildGL`). `_pushDrop` enqueues sim-space coords; `_injectDrops` renders each queued bump into the current state texture (in place, ping to the next slot).

```javascript
  WaterLayer.prototype._pushDrop = function (xSim, ySim, strength) {
    // clamp + queue; y is already in uv space (0 top .. 1 bottom flipped by caller in Task 4)
    if (this._pending.length > 12) this._pending.shift();
    this._pending.push({ x: Math.max(0, Math.min(1, xSim)), y: Math.max(0, Math.min(1, ySim)), s: Math.max(0.05, Math.min(2.0, strength || 1)) });
  };

  WaterLayer.prototype._injectDrops = function () {
    if (!this._pending.length || !this._simReady) return;
    var gl = this.gl;
    gl.useProgram(this.progDrop);
    gl.viewport(0, 0, this.simSize, this.simSize);
    gl.uniform1f(this.uDrop.radius, 0.03);
    for (var i = 0; i < this._pending.length; i++) {
      var d = this._pending[i];
      var src = this.cur;
      var dst = (this.cur + 1) % 3;
      gl.bindFramebuffer(gl.FRAMEBUFFER, this.simFBO[dst]);
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, this.heightTex[src]);
      gl.uniform1i(this.uDrop.state, 0);
      gl.uniform2f(this.uDrop.center, d.x, d.y);
      gl.uniform1f(this.uDrop.amp, 0.055 * d.s);
      this._drawQuad();
      this.cur = dst;
    }
    this._pending.length = 0;
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
  };
```

- [ ] **Step 4: Replace the `_simStep` stub body**

Replace `WaterLayer.prototype._simStep = function () { /* Task 2: ... */ };` with:

```javascript
  WaterLayer.prototype._simStep = function () {
    if (!this._simReady) return;
    this._injectDrops();
    var gl = this.gl;
    var src = this.cur;
    var dst = (this.cur + 1) % 3;
    gl.useProgram(this.progSim);
    gl.viewport(0, 0, this.simSize, this.simSize);
    gl.bindFramebuffer(gl.FRAMEBUFFER, this.simFBO[dst]);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this.heightTex[src]);
    gl.uniform1i(this.uSim.state, 0);
    gl.uniform2f(this.uSim.texel, this._texel, this._texel);
    // power-save halves the ambient shimmer and raises damping slightly
    gl.uniform1f(this.uSim.damping, this._powerSave ? Math.min(0.999, this.damping + 0.002) : this.damping);
    gl.uniform1f(this.uSim.wind, this._powerSave ? this.wind * 0.4 : this.wind);
    gl.uniform1f(this.uSim.time, (this._lastT || 0) * 0.001);
    this._drawQuad();
    this.cur = dst;
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    gl.viewport(0, 0, this.canvas.width, this.canvas.height);
  };
```

- [ ] **Step 5: Wire `drop()` to enqueue and give sane default intensity**

Replace the `drop` stub `WaterLayer.prototype.drop = function (/* xCss, yCss, strength */) { this.poke(); };` with a temporary CSS→sim mapping (Task 4 refines the mapping and adds proper letterbox correction):

```javascript
  WaterLayer.prototype.drop = function (xCss, yCss, strength) {
    this.poke();
    if (!this._simReady) return;
    var x = xCss / window.innerWidth;
    var y = 1.0 - (yCss / window.innerHeight); // flip: sim uv y-up
    this._pushDrop(x, y, strength == null ? 1 : strength);
  };
```

And set a non-zero default liveliness so drops are visible in this task: in `_buildGL`, after `this._simReady = true;`, add:

```javascript
    this.wind = 1.0; this.damping = 0.996;
```

(Task 4's `setIntensity` overrides these per-screen; this default is only so Task 2/3 have something to see.)

- [ ] **Step 6: Add a TEMPORARY debug height visualization to `_render`**

So we can see the sim before Task 3's real water shader exists, temporarily replace the `_render` body to blit the height texture. **This is removed in Task 3.** Replace the Task-1 `_render` body with:

```javascript
  WaterLayer.prototype._render = function () {
    // TEMP DEBUG (removed in Task 3): visualize height as grayscale so the sim is observable
    var gl = this.gl;
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    gl.viewport(0, 0, this.canvas.width, this.canvas.height);
    if (!this._dbgProg) {
      var H = shaderHeads(this.isGL2);
      this._dbgProg = program(gl, H.vs + VS_QUAD, H.fs +
        'IN vec2 vUv;\nuniform sampler2D uState;\nvoid main(){ float h = TEX(uState, vUv).r; float g = 0.5 + h*6.0; FRAG = vec4(g,g,g,1.0); }\n');
      this._dbgState = gl.getUniformLocation(this._dbgProg, 'uState');
    }
    gl.useProgram(this._dbgProg);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this.heightTex[this.cur]);
    gl.uniform1i(this._dbgState, 0);
    this._drawQuad();
  };
```

Also, temporarily, so drops can be triggered from the console, add at the very end of the IIFE (after `window.__kzWater = ...`), a one-liner you will remove in Task 3:

```javascript
  // TEMP: console harness for Task 2 verification (removed in Task 3)
  if (window.__kzWater && window.__kzWater.ok) window.__kzWaterDrop = function (x, y, s) { window.__kzWater.drop(x, y, s); };
```

- [ ] **Step 7: Build and verify**

Run: `node build.js`
Expected: `wrote dist/index.html (NNN KB), remaining external <script src=: 0`

- [ ] **Step 8: Manual browser verification (sim is alive)**

Open `dist/index.html` in Chrome. Expected:
- The background canvas shows a faint moving grayscale shimmer (the ambient `uWind` term).
- In the console run: `__kzWaterDrop(window.innerWidth/2, window.innerHeight/2, 1.2)`. Expected: a bright ring expands outward from screen center and reflects off the edges, decaying over ~2–3 seconds — a visible circular ripple in the grayscale height view.
- Run it several times rapidly at different coords: multiple rings interfere (bright where crests overlap). No console GL errors.
- Confirm no `GL_INVALID_*` warnings in console (a red error means a framebuffer-incomplete or missing-uniform bug — fix before proceeding).

- [ ] **Step 9: Commit**

```bash
git add index.html dist/index.html
git commit -m "$(cat <<'EOF'
feat(water): ping-pong height-field wave simulation (GLSL)

Two-texture wave equation with damping + gaussian drop injection, one source
compiling on both WebGL1 (half-float ext) and WebGL2. Temporary grayscale
height debug view for verification; real water shading follows.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Water render pass (normals, refraction, specular)

Replaces the temporary grayscale debug `_render` with the real water look: compute the surface normal from the height field, refract a soft vertical background gradient (washi-beige → paler) through it, and add a subtle 藍-tinted specular highlight along wave crests. Removes the Task-2 debug program and console harness.

**Files:**
- Modify: `index.html` water IIFE — add `FS_WATER`, build `this.progWater` in `_buildGL`, replace `_render`, delete the debug program + `window.__kzWaterDrop`.

**Interfaces:**
- Consumes: `this.heightTex[this.cur]` (Task 2), `this.canvas`, `this.dpr`.
- Produces: a fully shaded water surface drawn to the default framebuffer each frame. No new public API.

- [ ] **Step 1: Add the water render shader source**

Add near the other GLSL strings in the IIFE:

```javascript
  var FS_WATER =
    'IN vec2 vUv;\n' +
    'uniform sampler2D uState;\n' +
    'uniform vec2 uTexel;\n' +          // 1/simSize
    'uniform vec2 uAspect;\n' +         // (canvasW/canvasH) correction for the gradient
    'uniform vec3 uDeep;\n' +           // deep water tint
    'uniform vec3 uShallow;\n' +        // shallow / highlight base
    'uniform vec3 uSpec;\n' +           // specular tint (indigo)
    'void main(){\n' +
    '  float hL = TEX(uState, vUv + vec2(-uTexel.x, 0.0)).r;\n' +
    '  float hR = TEX(uState, vUv + vec2( uTexel.x, 0.0)).r;\n' +
    '  float hU = TEX(uState, vUv + vec2(0.0, -uTexel.y)).r;\n' +
    '  float hD = TEX(uState, vUv + vec2(0.0,  uTexel.y)).r;\n' +
    '  vec3 n = normalize(vec3(hL - hR, hU - hD, 0.10));\n' +   // z controls apparent slope scale
    '  float h = TEX(uState, vUv).r;\n' +
    // vertical background gradient, refracted by the surface normal
    '  vec2 ruv = vUv + n.xy * 0.9;\n' +
    '  float grad = clamp(ruv.y, 0.0, 1.0);\n' +
    '  vec3 base = mix(uDeep, uShallow, grad);\n' +
    // specular: light from upper-left, tightened highlight on crests
    '  vec3 L = normalize(vec3(-0.4, 0.75, 0.55));\n' +
    '  float spec = pow(max(dot(n, L), 0.0), 22.0);\n' +
    '  vec3 col = base + uSpec * spec * 0.55;\n' +
    // faint darkening in troughs / brightening on crests for depth cueing
    '  col += vec3(h * 1.4);\n' +
    '  FRAG = vec4(col, 1.0);\n' +
    '}\n';
```

Note: each line of `FS_WATER` is a JS string literal ending in `\n' +`; the `//` fragments after them (e.g. `// specular tint (indigo)`) are JS line comments, not part of the GLSL. Shaders fail loudly (console error at load) if malformed, so Step 7 will catch any paste error.

- [ ] **Step 2: Build `progWater` and its uniforms in `_buildGL`**

In `_buildGL`, immediately after the `this.progDrop = program(...)` line, add:

```javascript
    this.progWater = program(gl, H.vs + VS_QUAD, H.fs + FS_WATER);
    this.uWater = {
      state: gl.getUniformLocation(this.progWater, 'uState'),
      texel: gl.getUniformLocation(this.progWater, 'uTexel'),
      aspect: gl.getUniformLocation(this.progWater, 'uAspect'),
      deep: gl.getUniformLocation(this.progWater, 'uDeep'),
      shallow: gl.getUniformLocation(this.progWater, 'uShallow'),
      spec: gl.getUniformLocation(this.progWater, 'uSpec')
    };
```

- [ ] **Step 3: Replace `_render` with the real water pass**

Replace the entire Task-2 debug `_render` body with:

```javascript
  WaterLayer.prototype._render = function () {
    if (!this._simReady) return;
    var gl = this.gl;
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    gl.viewport(0, 0, this.canvas.width, this.canvas.height);
    gl.useProgram(this.progWater);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this.heightTex[this.cur]);
    gl.uniform1i(this.uWater.state, 0);
    gl.uniform2f(this.uWater.texel, this._texel, this._texel);
    gl.uniform2f(this.uWater.aspect, this.canvas.width / this.canvas.height, 1.0);
    // palette: washi-beige base graded from a slightly deeper tone up to a paler top
    gl.uniform3f(this.uWater.deep, 0.886, 0.878, 0.851);    // ~#e2e0d9 (trough / bottom)
    gl.uniform3f(this.uWater.shallow, 0.957, 0.949, 0.925); // ~#f4f2ec (crest / top)
    gl.uniform3f(this.uWater.spec, 0.184, 0.227, 0.431);    // ~#2f3a6e indigo highlight
    this._drawQuad();
  };
```

- [ ] **Step 4: Delete the Task-2 debug program creation**

Remove the `if (!this._dbgProg) { ... }` block and the two `this._dbgProg`/`this._dbgState` references — they no longer exist in the new `_render`, so this is satisfied by the Step-3 replacement. Confirm no other reference to `_dbgProg`/`_dbgState` remains (search the file).

- [ ] **Step 5: Delete the temporary console harness**

Remove the lines added in Task 2 Step 6:

```javascript
  // TEMP: console harness for Task 2 verification (removed in Task 3)
  if (window.__kzWater && window.__kzWater.ok) window.__kzWaterDrop = function (x, y, s) { window.__kzWater.drop(x, y, s); };
```

Because Task 4 has not yet wired document taps, add a *temporary* re-expose for this task's verification only, to be removed in Task 4:

```javascript
  // TEMP (removed in Task 4): allow manual drops while tap wiring is not yet in place
  if (window.__kzWater && window.__kzWater.ok) window.__kzWaterDrop = function (x, y, s) { window.__kzWater.drop(x, y, s); };
```

- [ ] **Step 6: Build and verify**

Run: `node build.js`
Expected: `wrote dist/index.html (NNN KB), remaining external <script src=: 0`

- [ ] **Step 7: Manual browser verification (water looks like water)**

Open `dist/index.html` in Chrome. Expected:
- The backdrop now reads as a calm pale washi-toned water surface with a soft vertical gradient (slightly paler toward the top), not grayscale.
- Console: `__kzWaterDrop(window.innerWidth/2, window.innerHeight/2, 1.3)`. Expected: a ripple spreads with visible indigo-tinted glints riding the crests and gentle refraction distorting the gradient — reads as light on water, not a gray ring.
- No shader compile/link errors in console (a compile failure surfaces as `program link:` / `shader compile:` thrown at load — if the page is blank-behind-frame and console shows such an error, fix the `FS_WATER` source, most likely the `uSpec` line).

- [ ] **Step 8: Commit**

```bash
git add index.html dist/index.html
git commit -m "$(cat <<'EOF'
feat(water): shaded water render pass (normals, refraction, indigo specular)

Replaces the grayscale debug view with washi-toned refracted gradient plus
crest highlights. Removes the temporary debug program.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Tap ripples + per-screen intensity control

Wires real interaction: a document-level pointer listener raises a ripple wherever the user taps *outside* interactive UI, and `setIntensity(mode)` sets liveliness per screen. Fixes the CSS→sim mapping so drops land under the finger regardless of canvas aspect. Removes the temporary console harness.

**Files:**
- Modify: `index.html` water IIFE — implement `setIntensity`, `calm`; refine `drop` mapping; delete the temporary console harness.
- Modify: `index.html` `App` class — add `_waterPointer` document listener (attach in `componentDidMount`, detach in `componentWillUnmount`); call `this.water.setIntensity(...)` from a new `_syncWaterIntensity()` invoked in `componentDidMount` and `componentDidUpdate`.

**Interfaces:**
- Consumes: `this._pushDrop` (Task 2), `this.wind`, `this.damping`, `this.mode`.
- Produces: `setIntensity(mode)` with modes `'idle' | 'ask' | 'cast' | 'result'` (any screen not `cast`/`result` maps to the quiet `'ask'` profile by the caller); `calm()` quickly damps. `App._screenToWaterMode(screen)` returns the mode string for a screen; `App._syncWaterIntensity()` calls `this.water.setIntensity(...)` when the screen changes.

- [ ] **Step 1: Implement `setIntensity` and `calm`**

Replace the `setIntensity`/`calm` stubs in the IIFE:

```javascript
  WaterLayer.prototype.setIntensity = function (mode) {
    this.mode = mode || 'ask';
    // wind = ambient shimmer amplitude; damping = wave persistence
    if (mode === 'cast')        { this.wind = 1.0; this.damping = 0.997; }
    else if (mode === 'result') { this.wind = 0.05; this.damping = 0.985; }  // near-frozen for reading
    else if (mode === 'idle')   { this.wind = 0.25; this.damping = 0.992; }
    else                        { this.wind = 0.45; this.damping = 0.995; }  // ask/history/reference/detail/about
    this.poke();
  };
  WaterLayer.prototype.calm = function () {
    // temporarily crush the surface toward flat; sim's damping does the rest over ~1s
    this._calmUntil = (typeof performance !== 'undefined' ? performance.now() : Date.now()) + 900;
  };
```

And in `_simStep`, apply the transient `calm()` boost: replace the damping uniform line

```javascript
    gl.uniform1f(this.uSim.damping, this._powerSave ? Math.min(0.999, this.damping + 0.002) : this.damping);
```

with:

```javascript
    var nowMs = (typeof performance !== 'undefined' ? performance.now() : Date.now());
    var calming = this._calmUntil && nowMs < this._calmUntil;
    var damp = calming ? 0.90 : (this._powerSave ? Math.min(0.999, this.damping + 0.002) : this.damping);
    gl.uniform1f(this.uSim.damping, damp);
```

- [ ] **Step 2: Fix the CSS→sim mapping in `drop`**

The canvas covers the full viewport and the sim is a square; map CSS coords to the square uv, correcting for the longer axis so ripples stay round and land under the finger. Replace the Task-2 `drop` body:

```javascript
  WaterLayer.prototype.drop = function (xCss, yCss, strength) {
    this.poke();
    if (!this._simReady) return;
    var W = window.innerWidth, Hh = window.innerHeight;
    // normalize to 0..1 across the larger axis so the ripple is circular; center the shorter axis
    var m = Math.max(W, Hh);
    var offX = (m - W) * 0.5, offY = (m - Hh) * 0.5;
    var x = (xCss + offX) / m;
    var y = 1.0 - ((yCss + offY) / m);       // flip to uv y-up
    this._pushDrop(x, y, strength == null ? 1 : strength);
  };
```

- [ ] **Step 3: Delete the temporary console harness**

Remove the Task-3 block:

```javascript
  // TEMP (removed in Task 4): allow manual drops while tap wiring is not yet in place
  if (window.__kzWater && window.__kzWater.ok) window.__kzWaterDrop = function (x, y, s) { window.__kzWater.drop(x, y, s); };
```

- [ ] **Step 4: Add the document-level ripple listener to `App`**

Add these methods to the `App` class (place them near `componentDidMount`, e.g. after `componentWillUnmount` at `index.html:378`):

```javascript
  // raise a ripple on taps that are NOT on interactive UI (buttons/inputs/links/role=button)
  _waterPointer = (ev) => {
    if (!this.water || !this.water.ok) return;
    if (ev.pointerType === 'mouse' && ev.button !== 0) return;
    var t = ev.target;
    if (t && t.closest && t.closest('button, a, input, textarea, select, [role="button"], [tabindex], .kz-coin')) {
      this.water.poke();
      return; // let the control handle it; no ripple over UI chrome
    }
    this.water.drop(ev.clientX, ev.clientY, 0.7);
  };

  _screenToWaterMode(screen) {
    if (screen === 'cast') return 'cast';
    if (screen === 'result') return 'result';
    return 'ask'; // ask/about/history/reference/detail → quiet shimmer
  }
  _syncWaterIntensity() {
    if (!this.water) return;
    var mode = this._screenToWaterMode(this.state.screen);
    if (this._waterMode !== mode) { this._waterMode = mode; this.water.setIntensity(mode); }
  }
```

- [ ] **Step 5: Attach/detach the listener and sync intensity on mount/update**

In `componentDidMount`, after the `this.water = ...` line added in Task 1 Step 3, add:

```javascript
    document.addEventListener('pointerdown', this._waterPointer, { passive: true });
    this._syncWaterIntensity();
```

In `componentDidUpdate` (`index.html:359`), add as the first line of the method body:

```javascript
    this._syncWaterIntensity();
```

In `componentWillUnmount`, before the `this.water.destroy()` line, add:

```javascript
    document.removeEventListener('pointerdown', this._waterPointer);
```

- [ ] **Step 6: Build and verify**

Run: `node build.js`
Expected: `wrote dist/index.html (NNN KB), remaining external <script src=: 0`

- [ ] **Step 7: Manual browser verification (tap ripples + intensity)**

Open `dist/index.html` in Chrome. Expected:
- Tapping/clicking on empty background (the page margin, or empty area inside the card that isn't a control) raises a ripple exactly under the pointer, circular, that spreads and fades.
- Tapping a button (e.g. "卦を立てる") does NOT raise a ripple over it and still activates the button normally.
- On the ask screen the water is a quiet shimmer. Navigate ask → cast ("卦を立てる"): the surface becomes noticeably livelier. Complete a cast and go to result: the surface settles to near-still within ~1 second (reading mode).
- No console errors; tapping many times does not degrade to a crawl (drops queue-capped at 12).

- [ ] **Step 8: Commit**

```bash
git add index.html dist/index.html
git commit -m "$(cat <<'EOF'
feat(water): tap ripples on non-UI taps + per-screen intensity

Document pointerdown raises a ripple under the finger, skipping interactive
chrome. setIntensity drives ambient liveliness/damping per screen; cast is the
star, result is near-frozen. Aspect-corrected CSS->sim mapping.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Stone splash integration + yao "light line" choreography

Connects the existing DOM stone toss to the water: when the three stones land, three splashes hit the surface (at their DOM positions, interfering), and each completed line surfaces as a light line on the water that drifts down into the stacked hexagram. On the sixth line, `calm()` stills the pond. The stones keep falling as DOM (unchanged); only the splash coordinates and a light-line overlay are added.

**Files:**
- Modify: `index.html` `App` class — in `toss()` (`index.html:398-430`), after the stones "land" (inside the `setTimeout` at line 420, where `casts` is appended), compute the three coin DOM centers and call `this.water.drop(...)` per stone; trigger a light-line flourish; call `this.water.calm()` on the sixth.
- Modify: `index.html` `renderCast` (`index.html:1265-1289`) — add a `ref` on the coin button so we can read the coins' screen position; add a light-line overlay element driven by transient state.
- Modify: `index.html` `App.state` (`index.html:100-134`) — add `waterFlash` transient state for the light-line animation.
- Modify: `<style>` block — add `@keyframes kz-yao-rise` for the light line.

**Interfaces:**
- Consumes: `this.water.drop`, `this.water.calm` (Tasks 2/4); the existing `s.casts`, `s.tossing`, `s.lastThrow` toss state.
- Produces: `this._coinBtnRef` (DOM node of the coin button), `App` method `_splashStones(faces)` that drops three ripples at the coins' screen centers, and `waterFlash` state `{ seq, value }` consumed by `renderCast` to render the rising light line. No water-module API change.

- [ ] **Step 1: Add the light-line keyframes to `<style>`**

Insert before `</style>` (`index.html:77`):

```css
  @keyframes kz-yao-rise {
    0%   { opacity: 0; transform: translate(-50%, 0) scaleX(.4); filter: blur(1px); }
    30%  { opacity: .95; transform: translate(-50%, -8px) scaleX(1); filter: blur(0); }
    100% { opacity: 0; transform: translate(-50%, -120px) scaleX(.9); filter: blur(.5px); }
  }
```

- [ ] **Step 2: Add `waterFlash` to initial state**

In the `state = { ... }` initializer (`index.html:100`), add after `lastThrow: null,` (line ~126):

```javascript
    waterFlash: null,
```

- [ ] **Step 3: Add a ref to the coin button in `renderCast`**

In `renderCast` (`index.html:1274`), the coin `button` currently has no ref. Add `ref: (n) => { this._coinBtnRef = n; },` to its props object (alongside `type: 'button'`). Then, inside that same button (as an additional child after `out.ripple`), add the light-line overlay:

```javascript
        out.waterFlash ? e('div', {
          key: 'yf-' + out.waterFlash.seq,
          'aria-hidden': 'true',
          style: {
            position: 'absolute', left: '50%', top: '46%', pointerEvents: 'none',
            width: out.waterFlash.value === 1 ? '120px' : '120px',
            height: out.waterFlash.value === 1 ? '3px' : '3px',
            borderRadius: '3px',
            background: out.waterFlash.value === 1
              ? 'linear-gradient(90deg, rgba(47,58,110,0) 0%, rgba(47,58,110,.9) 50%, rgba(47,58,110,0) 100%)'
              : 'linear-gradient(90deg, rgba(47,58,110,0) 0%, rgba(47,58,110,.9) 35%, rgba(47,58,110,0) 50%, rgba(47,58,110,.9) 65%, rgba(47,58,110,0) 100%)',
            animation: 'kz-yao-rise 1s cubic-bezier(.2,.7,.2,1) both',
          }
        }) : null
```

And expose `waterFlash` through `renderVals`'s `out` object: in `renderVals` (`index.html:1156`, the `out = { ... }` literal), add:

```javascript
      waterFlash: s.waterFlash,
```

- [ ] **Step 4: Splash the stones + raise the light line in `toss()`**

In `toss()`'s landing `setTimeout` (`index.html:420-429`), the current code appends the cast and schedules the next auto-toss. Replace the setState callback body so it also splashes and flashes. Specifically, replace:

```javascript
    setTimeout(() => {
      this.setState((s) => ({ casts: s.casts.concat([{ value, changing }]), tossing: false, lastThrow: { faces, value, changing, y } }), () => {
        // press-and-hold: while held, keep tossing until 6; else stop
        if (this._held && this.state.casts.length < 6) {
          this._autoT = setTimeout(() => this.pumpToss(), 90);
        } else if (this.state.autoCasting && (!this._held || this.state.casts.length >= 6)) {
          this.setState({ autoCasting: false });
        }
      });
    }, dur + 160);
```

with:

```javascript
    setTimeout(() => {
      this.setState((s) => ({
        casts: s.casts.concat([{ value, changing }]),
        tossing: false,
        lastThrow: { faces, value, changing, y },
        waterFlash: { seq: s.tossSeq, value: value },
      }), () => {
        this._splashStones(faces);
        var count = this.state.casts.length;
        if (count >= 6 && this.water) this.water.calm();      // sixth line: still the pond
        // press-and-hold: while held, keep tossing until 6; else stop
        if (this._held && this.state.casts.length < 6) {
          this._autoT = setTimeout(() => this.pumpToss(), 90);
        } else if (this.state.autoCasting && (!this._held || this.state.casts.length >= 6)) {
          this.setState({ autoCasting: false });
        }
      });
    }, dur + 160);
```

- [ ] **Step 5: Implement `_splashStones`**

Add to the `App` class (near `pumpToss`, `index.html:433`):

```javascript
  // drop three interfering ripples at the three coins' on-screen centers
  _splashStones(faces) {
    if (!this.water || !this.water.ok) return;
    var btn = this._coinBtnRef;
    if (!btn) return;
    var coins = btn.querySelectorAll('.kz-coin');
    for (var i = 0; i < coins.length; i++) {
      var r = coins[i].getBoundingClientRect();
      var cx = r.left + r.width / 2;
      var cy = r.top + r.height / 2;
      // a head (表/陽) hits a touch harder than a tail for a little variation
      var strength = (faces && faces[i]) ? 1.1 : 0.85;
      // stagger the three splashes slightly so the interference reads
      (function (self, x, y, s, delay) {
        setTimeout(function () { self.water.drop(x, y, s); }, delay);
      })(this, cx, cy, strength, i * 70);
    }
  }
```

- [ ] **Step 6: Build and verify**

Run: `node build.js`
Expected: `wrote dist/index.html (NNN KB), remaining external <script src=: 0`

- [ ] **Step 7: Manual browser verification (cast choreography)**

Open `dist/index.html` in Chrome. Go to the cast screen ("卦を立てる"). Expected:
- Tap the stones: as the three coins land, three ripples appear at the three coin positions and visibly interfere (crossing crests brighten).
- A short indigo light line rises from the coins area and fades upward each time a line completes (single solid bar for 陽, split bar for 陰).
- Long-press to auto-throw all six: ripples fire on each line; after the sixth line the surface calms noticeably within ~1s, and "結果を見る" appears.
- The existing 表/裏 readout and the building hexagram still update correctly (no regression to the DOM stone flow).

- [ ] **Step 8: Commit**

```bash
git add index.html dist/index.html
git commit -m "$(cat <<'EOF'
feat(water): stone splashes + yao light-line choreography on cast

Landing stones drop three interfering ripples at their on-screen positions; a
rising indigo light line marks each completed line; the pond calms on the sixth.
DOM stone toss is unchanged.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Panel translucency + contrast tuning

Makes the paper panels semi-transparent so the water shows through ("washi floating on water"), while preserving text contrast. Applied only when water is on (`body.kz-water-on`) so the fallback keeps its solid look. Uses `backdrop-filter` where available for a frosted-washi feel, with a solid-ish fallback tint.

**Files:**
- Modify: `index.html` `<style>` block — add `.kz-water-on`-scoped translucency for `.kz-wrap` background (desktop margin), `.kz-card`, the scroll surface, and bottom sheets.
- Modify: `index.html` — the card and screens use inline `background: '#ffffff'` in JS. Add a translucency override via a CSS class rather than editing every inline style: introduce class `kz-surface` on the card body and let CSS lower its opacity under water. The card element is `.kz-card` (`index.html` render at line 1637). The scroll is `.kz-scroll`.

**Interfaces:**
- Consumes: `body.kz-water-on` (Task 1), `.kz-card`/`.kz-scroll`/sheet DOM (existing).
- Produces: CSS only. No JS API change. (Panels remain fully opaque in the fallback build.)

- [ ] **Step 1: Add translucency CSS scoped to `body.kz-water-on`**

Insert before `</style>` (`index.html:77`). These rules only bite when water is active, so the fallback is untouched. Values are the on-device starting point.

```css
  /* --- translucent "washi on water" panels (only when the water layer is live) --- */
  body.kz-water-on .kz-card {
    background: rgba(255, 255, 255, 0.82);
    backdrop-filter: blur(9px) saturate(1.03);
    -webkit-backdrop-filter: blur(9px) saturate(1.03);
  }
  @media (min-width: 480px) {
    /* desktop: the phone frame floats on the pond; keep the outer margin transparent to the canvas */
    body.kz-water-on .kz-wrap { background: transparent; }
  }
  /* bottom sheets: keep them readable but let a hint of water through */
  body.kz-water-on [role="dialog"] {
    background: rgba(244, 242, 236, 0.92) !important;
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
  }
  /* when backdrop-filter is unsupported, fall back to a more opaque tint so text stays legible */
  @supports not ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {
    body.kz-water-on .kz-card { background: rgba(255, 255, 255, 0.93); }
    body.kz-water-on [role="dialog"] { background: rgba(244, 242, 236, 0.97) !important; }
  }
```

- [ ] **Step 2: Ensure the card's own inline white doesn't fully hide the water**

The `.kz-card` element also has an inline `background: '#ffffff'` from its CSS rule at `index.html:51`, plus the `.kz-wrap`/`.kz-card` base rules. The `body.kz-water-on .kz-card` selector (higher specificity: element+class vs class) overrides the base `.kz-card { background: #ffffff }`. Verify by checking that no inline `style={{background:'#fff'}}` is set on the card element in `render()` (`index.html:1637`) — it is not (the card uses only `className: 'kz-card'`), so the CSS override wins. No JS change needed. If a later reviewer finds the water invisible through the card, the cause is `backdrop-filter` stacking context — confirm `.kz-wrap { position: relative; z-index: 1 }` (Task 1) is present so the card composites above the `z-index:0` canvas.

- [ ] **Step 3: Build and verify**

Run: `node build.js`
Expected: `wrote dist/index.html (NNN KB), remaining external <script src=: 0`

- [ ] **Step 4: Manual browser verification (translucency + contrast)**

Open `dist/index.html` in Chrome (desktop and a mobile emulation e.g. iPhone via DevTools device toolbar). Expected:
- The card panel is subtly translucent: ripples in the background are faintly visible through it, especially on the cast screen when the surface is lively, without text becoming hard to read.
- On desktop, the margin around the phone frame shows the full water canvas; the frame reads as floating on the pond.
- Body text (`#4a4640`, `#2b2823`) over the translucent card remains clearly legible against the pale water — spot-check the ask paragraph and a result paragraph. If any text is marginal, note it for the on-device tuning pass (raise the card alpha toward 0.90).
- Open the menu sheet (☰): the sheet is frosted/translucent but its text is fully readable.

- [ ] **Step 5: Manual browser verification (fallback unchanged)**

Emulate `prefers-reduced-motion: reduce`, hard-reload. Expected: `body` has NO `kz-water-on` class, so panels are fully opaque exactly as production today. Reset emulation.

- [ ] **Step 6: Commit**

```bash
git add index.html dist/index.html
git commit -m "$(cat <<'EOF'
feat(water): translucent washi panels over the water (water-on only)

Card and sheets gain a frosted translucency scoped to body.kz-water-on so the
pond shows through while text stays legible; solid fallback where backdrop-filter
is unsupported and in the reduced-motion build.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Performance hardening (visibility, power-save, DPR, sim resolution)

Locks in the performance ceilings from the spec: confirm/raise the sim grid toward the 512 cap based on a quick device check, cap DPR at 1.5 (already set — verify), ensure the loop truly stops when hidden, and confirm the idle power-save transition. Adds a lightweight frame-time guard that drops the sim resolution one notch if frames are consistently slow.

**Files:**
- Modify: `index.html` water IIFE — add adaptive sim-size selection in the constructor, a frame-time watchdog in `_frame`, and a helper `_rebuildSim(newSize)` to resize the ping-pong textures without recreating programs.

**Interfaces:**
- Consumes: `this.simSize`, `this.heightTex`, `this.simFBO`, `this._buildGL` internals (Task 2).
- Produces: `_rebuildSim(size)` (re-allocates the 3 height textures/FBOs at a new resolution, preserving programs); adaptive `simSize` chosen at construction; a rolling `_slowFrames` counter that triggers one downgrade step.

- [ ] **Step 1: Choose initial sim size by device class (respect the 512 cap)**

In the `WaterLayer` constructor (Task 1), replace `this.simSize = 256;` with an adaptive choice:

```javascript
    // sim grid: cap 512 (spec). Phones (coarse pointer / small screen) start at 256; roomy screens 384.
    var coarse = false;
    try { coarse = window.matchMedia && window.matchMedia('(pointer: coarse)').matches; } catch (_) {}
    var big = Math.min(window.innerWidth, window.innerHeight) >= 900;
    this.simSize = coarse ? 256 : (big ? 384 : 320);
    if (this.simSize > 512) this.simSize = 512;
```

- [ ] **Step 2: Add `_rebuildSim` to resize the ping-pong buffers**

Add to `WaterLayer.prototype` (after `_buildGL`):

```javascript
  WaterLayer.prototype._rebuildSim = function (size) {
    if (!this._simReady || size === this.simSize || size < 64) return;
    var gl = this.gl;
    // delete old textures + FBOs
    for (var i = 0; i < this.heightTex.length; i++) {
      try { gl.deleteFramebuffer(this.simFBO[i]); } catch (_) {}
      try { gl.deleteTexture(this.heightTex[i]); } catch (_) {}
    }
    this.simSize = size; this._texel = 1.0 / size;
    var filter = this.linearOK ? gl.LINEAR : gl.NEAREST;
    this.heightTex = []; this.simFBO = [];
    for (var j = 0; j < 3; j++) {
      var tex = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, tex);
      var internal = this.isGL2 ? gl.RGBA16F : gl.RGBA;
      gl.texImage2D(gl.TEXTURE_2D, 0, internal, size, size, 0, gl.RGBA, this.halfType, null);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, filter);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, filter);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      var fbo = gl.createFramebuffer();
      gl.bindFramebuffer(gl.FRAMEBUFFER, fbo);
      gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, tex, 0);
      this.heightTex.push(tex); this.simFBO.push(fbo);
    }
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    this.cur = 0;
  };
```

- [ ] **Step 3: Add a frame-time watchdog to `_frame`**

Replace the Task-1/2 `_frame` body with a version that measures frame delta and downgrades once if sustained-slow:

```javascript
  WaterLayer.prototype._frame = function (t) {
    if (!this._lastT) { this._lastT = t; this._simStep(); this._render(); return; }
    var dt = t - this._lastT;
    this._lastT = t;
    // power-save: after 6s of no interaction, ease into idle shimmer
    var now = (typeof performance !== 'undefined' ? performance.now() : Date.now());
    this._powerSave = (now - this._idleSince) > 6000;
    // watchdog: if frames run long for a sustained stretch, drop sim resolution one notch (once)
    if (!this._downgraded) {
      if (dt > 34) { this._slowFrames = (this._slowFrames || 0) + 1; } else { this._slowFrames = 0; }
      if (this._slowFrames > 90) {           // ~1.5s of >34ms frames
        var next = this.simSize >= 384 ? 256 : (this.simSize >= 320 ? 256 : 192);
        if (next < this.simSize) { this._rebuildSim(next); this._downgraded = true; }
        this._slowFrames = 0;
      }
    }
    this._simStep();
    this._render();
  };
```

- [ ] **Step 4: Build and verify**

Run: `node build.js`
Expected: `wrote dist/index.html (NNN KB), remaining external <script src=: 0`

- [ ] **Step 5: Manual browser verification (perf behaviors)**

Open `dist/index.html` in Chrome. Expected:
- `window.__kzWater.dpr` ≤ 1.5 in the console.
- `window.__kzWater.simSize` is ≤ 512 and matches the device class (256 on a mobile-emulated coarse pointer; 320–384 on desktop).
- Open DevTools Performance / FPS meter (Rendering → "Frame Rendering Stats"): idle sits comfortably (mostly RAF-bound), and after ~6s of no interaction the shimmer visibly quiets (power-save). Interacting (a tap) revives full liveliness.
- Switch to another tab for a few seconds and back: on return the loop resumes; the FPS meter shows it had stopped while hidden (no runaway timers). Confirm via `window.__kzWater._raf` being `0` while hidden is not directly observable, but the CPU flatlining in the Performance panel while the tab is hidden is.
- (Optional stress) In the console, force a downgrade check by temporarily setting `__kzWater._slowFrames = 100` and, if on a slow machine, confirm `simSize` drops one notch without visual breakage. This is a spot check, not required to pass.

- [ ] **Step 6: Commit**

```bash
git add index.html dist/index.html
git commit -m "$(cat <<'EOF'
perf(water): adaptive sim resolution, DPR cap, power-save, slow-frame downgrade

Sim grid chosen by device class (<=512 cap), DPR capped at 1.5, idle shimmer
power-save after 6s, and a one-shot resolution downgrade if frames run long.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: Full build verification + regression sweep

No new feature code. A final pass confirming the single-file build is intact, the shaders inline correctly, and the whole divination flow works identically with water ON and OFF (WebGL disabled and reduced-motion). This is the spec's "テスト・検証方針" acceptance gate.

**Files:**
- None modified (verification only). If a regression is found, fix it in the relevant task's file (`index.html`) and note it in the commit.

**Interfaces:**
- Consumes: everything from Tasks 1–7.
- Produces: a verified `dist/index.html`.

- [ ] **Step 1: Clean build**

Run: `node build.js`
Expected: `wrote dist/index.html (NNN KB), remaining external <script src=: 0`
Confirm the KB size is only modestly larger than the pre-water build (the water code is a few KB of source; no assets added).

- [ ] **Step 2: Confirm shaders inlined intact**

Search the built file for shader markers:
Run: `grep -c "FS_SIM\|FS_WATER\|FS_DROP" dist/index.html`
Expected: a non-zero count (the shader source strings are present verbatim in `dist/index.html`). Then confirm no `$&`/`$1` corruption by searching for a shader fragment:
Run: `grep -c "float lap = (l + r + u + d)" dist/index.html`
Expected: `1` — the wave-equation line survived inlining unaltered.

- [ ] **Step 3: Regression — full flow, water ON**

Open `dist/index.html` in Chrome (both desktop and iPhone emulation). Walk the entire flow and confirm no regressions vs. current production:
- Ask: type a question, char counter works, "卦を立てる" navigates to cast.
- Cast: tap and long-press both build six lines; 表/裏 readout, building hexagram, "結果を見る" all work; stone splashes + light lines appear.
- Result: carousel swipes (past/present/future) work; 動いた爻 section renders; share and 画像を保存 open the sheet and produce the PNG (the share canvas is Canvas 2D, unaffected by water); "別の問いを立てる" resets.
- History: a reading was recorded; viewing a past reading works; delete + undo toast works.
- Reference/detail: 64卦 grid, search, and a detail page render; glossary ruby taps open the sheet.
- Menu (☰), about, AI consent + AI read (if backend reachable) — sheets open/close, focus trap works, Escape closes.
- Browser back/forward across screens behaves as before; the cast-in-progress confirm dialog still fires.

- [ ] **Step 4: Regression — WebGL disabled**

In Chrome, disable WebGL (chrome://flags → "Override software rendering list" off + relaunch, OR use a Firefox profile with `webgl.disabled=true`, OR temporarily stub in console before load: not reliable — prefer a real WebGL-off browser). With WebGL unavailable:
- `window.__kzWater.ok` → `false`, no `#kz-water` canvas, `body` has no `kz-water-on`.
- The entire flow in Step 3 still works identically (panels opaque, no ripples). Confirm no console errors referencing water.

- [ ] **Step 5: Regression — reduced motion**

Emulate `prefers-reduced-motion: reduce`, hard-reload:
- No water canvas; `window.__kzWater.ok` → `false`.
- Existing coin animation reduced-motion behavior is intact (coins settle without long spins per the CSS at `index.html:73-76`).
- Full flow works. Reset emulation.

- [ ] **Step 6: Final commit**

Only if Steps 1–5 surfaced fixes; otherwise there is nothing to commit (verification-only). If fixes were made:

```bash
git add index.html dist/index.html
git commit -m "$(cat <<'EOF'
fix(water): regression fixes from full build/flow verification

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

If no fixes were needed, record completion in the executing session's notes (no empty commit).

---

## Self-Review

**1. Spec coverage** — every spec section maps to a task:
- Full-screen WebGL canvas, ping-pong height field, zero deps, inline shaders → Tasks 1–3.
- Imperative API `drop/calm/setIntensity` independent of React → Tasks 1 (surface), 4 (behavior); consumed by React in Tasks 4–5.
- Non-UI tap ripples via document pointer listener with UI filter → Task 4 Step 4.
- Stones stay DOM, splash coords to `water.drop()` → Task 5.
- 5-second choreography (静→投→着水 interference→爻 as light line→sixth calms→結果を見る) → Task 5 (splashes/light line/calm) building on existing DOM toss.
- Per-screen intensity (ask/辞典/履歴 quiet, cast star, result near-still) → Task 4 `setIntensity` + `_screenToWaterMode`.
- Translucent washi panels, existing palette → Task 6.
- Fallback: WebGL-unavailable or reduced-motion → no canvas, static background, flow unaffected → Task 1 (detection/fallback), verified in Tasks 1/6/8.
- Performance: sim ≤512, DPR ≤1.5, stop on document.hidden, idle power-save → Task 1 (DPR/visibility) + Task 7 (sim size/power-save/watchdog).
- iOS Safari half-float: `OES_texture_half_float` / `OES_texture_half_float_linear` + WebGL2 auto-detect → Task 1 `tryContext`, used in Task 2 texture allocation.
- build.js `$&` gotcha respected: no new `<script src>`, shaders live in the existing inline script, never passed as a `String.replace` replacement → Global Constraints + Task 8 Step 2 verification.
- Out of scope (sound, in-app recording) → correctly excluded; nothing added for them.
- Test/verification approach (no harness; `node build.js` + concrete browser checks; WebGL-on/off + reduced-motion) → every task's verification steps + Task 8.

**2. Placeholder scan** — the only "TEMP/placeholder" code is the intentional, explicitly-scoped debug scaffolding (Task 2's grayscale `_render` + `__kzWaterDrop` console hook), and each is removed by name in a later task's numbered step (Task 3 Steps 4–5, Task 4 Step 3). All GLSL and JS bodies are complete and copy-runnable. No "TODO/TBD/add error handling/similar to Task N" left.

**3. Type/name consistency** — verified the shared names across tasks: `window.__kzWater`, `WaterLayer`, `this.heightTex`/`this.simFBO`/`this.cur`/`this.simSize`/`this._texel`/`this._simReady`, methods `_buildGL`/`_simStep`/`_render`/`_frame`/`_drawQuad`/`_injectDrops`/`_pushDrop`/`_rebuildSim`, public `drop`/`calm`/`setIntensity`/`poke`/`destroy`, App members `this.water`/`_waterPointer`/`_screenToWaterMode`/`_syncWaterIntensity`/`_splashStones`/`_coinBtnRef`, state key `waterFlash` and its `{seq,value}` shape (produced in `toss`, read in `renderVals`→`renderCast`). `_frame` is defined in Task 1, extended in Task 2 (power-save), and finalized in Task 7 (watchdog) — each replacement is a full-body replace, not additive drift. `drop` mapping is introduced simply in Task 2 Step 5 and refined in Task 4 Step 2 (explicit full-body replace). Intensity modes are the same four strings everywhere (`idle`/`ask`/`cast`/`result`).
