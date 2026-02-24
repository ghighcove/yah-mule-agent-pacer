# Yah Mule — Web UI Spec
**Created**: 2026-02-23
**Status**: Spec only — implementation in a separate session (TD-37)
**Decision needed**: Streamlit vs HTML+JS — see Recommendation at bottom

---

## What Gets Displayed (both options identical)

Same three KPI dimensions as CLI, plus extras a web UI can do that the terminal can't:

| Section | CLI today | Web adds |
|---------|-----------|----------|
| Quota utilization (all-models + sonnet) | Text + ASCII bar | Gauge dial or filled progress arc |
| Spend efficiency (ratio today + 7-day) | Text + status label | Sparkline for ratio over 7 days |
| Spend pattern (week spend vs baseline) | Text + bar | Color-coded week heatmap |
| 7-day trend | ASCII bar chart | Actual bar chart with hover values |
| Hourly breakdown | ASCII bars | Area chart with hour labels |
| Mule branding | — | Photo header (see below) |
| Reset countdown | Text label | Live countdown timer |
| Model split (Sonnet vs Haiku) | Text % | Donut/pie |

**Full-screen target**: Use 100% viewport width, no sidebar wastage. Two-column layout above fold:
- Left: Quota + Efficiency gauges (top priority)
- Right: 7-day trend chart
- Below fold: Hourly breakdown + spend pattern + model split

---

## Mule Photos

Promo photos in `assets/promo/`: `yah-mule-38.jpg` through `yah-mule-43.jpg`

**Plan**: Rotate one photo per load as the page header/hero image. Narrow strip (~120px tall), full-width, positioned above the KPI grid. The mule provides personality and makes the tab recognizable.

```
┌──────────────────────────────────────────────────────────┐
│  [═══════════ mule photo, full-width strip ═══════════]   │
│  YAH MULE  •  Claude Efficiency Monitor  •  [timestamp]   │
├────────────────────────┬─────────────────────────────────┤
│  QUOTA UTILIZATION     │  7-DAY TREND                    │
│  [gauge] all-models    │  [bar chart]                    │
│  [gauge] sonnet        │                                 │
├────────────────────────┴─────────────────────────────────┤
│  SPEND EFFICIENCY   ratio today / 7d / baseline          │
│  [sparkline]                                             │
├──────────────────────────────────────────────────────────┤
│  TODAY BY HOUR  [area chart]                             │
└──────────────────────────────────────────────────────────┘
```

---

## Option A: Streamlit

### How it works
- Single Python file (`web_monitor.py`)
- `streamlit run web_monitor.py` launches local server (default `localhost:8501`)
- Browser auto-opens; can pin as a tab
- Auto-refresh via `st.rerun()` in a loop with `time.sleep(60)`

### Layout sketch
```python
st.set_page_config(layout="wide", page_title="Yah Mule", page_icon="🫏")

# Mule photo header
st.image(random.choice(mule_photos), use_container_width=True)
st.caption("YAH MULE — Claude Efficiency Monitor")

col1, col2 = st.columns([1, 2])
with col1:
    st.metric("All-Models", f"{quota_pct:.1f}%", ...)
    st.metric("Sonnet", f"{sonnet_pct:.1f}%", ...)
    st.progress(quota_pct / 100)
with col2:
    st.bar_chart(trend_df)  # 7-day trend

st.plotly_chart(hourly_fig, use_container_width=True)

# Auto-refresh
time.sleep(60)
st.rerun()
```

### Pros
- Pure Python — all data logic already in `kpi_display.py`, just import and reuse
- `st.metric()` + `st.progress()` give clean gauges out of the box
- Plotly charts via `st.plotly_chart()` — interactive hover
- One file, ~150 lines
- Dark mode built-in (`theme = dark` in `.streamlit/config.toml`)
- No JS required

### Cons
- Extra install: `pip install streamlit plotly` (~50MB)
- Needs a terminal window running `streamlit run ...` (or a background process/bat)
- Can't open as a local file:// — needs the server running
- `st.rerun()` approach causes slight flash/flicker on refresh
- Less control over exact layout than raw HTML

### Update options in UI
- Manual refresh button: `if st.button("Refresh now"): st.rerun()`
- Recalibrate button: trigger `kpi_display.py --calibrate N` via `subprocess`
- Auto-refresh toggle: `st.checkbox("Auto-refresh 60s")`

### Deps
```
streamlit>=1.32
plotly>=5.0
pandas>=2.0  (for chart dataframes)
```

### Entry point
```
web_monitor_streamlit.py
```
Launch bat:
```bat
streamlit run web_monitor_streamlit.py
```

---

## Option B: HTML + JavaScript

### How it works
- Python backend: tiny Flask server (`web_server.py`) exposes `/api/kpi` endpoint returning JSON
- Frontend: single `index.html` with vanilla JS that polls `/api/kpi` every 60 seconds
- Open `http://localhost:5050` in browser — pin as tab
- No build step, no npm, no framework

### Layout sketch (index.html)
```html
<div class="header">
  <img id="mule-photo" src="/static/promo/yah-mule-38.jpg" />
  <h1>YAH MULE — Claude Efficiency Monitor</h1>
  <span id="timestamp"></span>
</div>
<div class="grid-2col">
  <div id="quota-panel">
    <!-- SVG arc gauges, filled via JS -->
  </div>
  <div id="trend-panel">
    <!-- CSS bar chart or Chart.js bars -->
  </div>
</div>
<div id="hourly-panel"><!-- area chart via Chart.js --></div>
```

Backend (`web_server.py`):
```python
from flask import Flask, jsonify
from kpi_display import compute_kpis  # extract pure-data function

app = Flask(__name__)

@app.route('/api/kpi')
def kpi():
    return jsonify(compute_kpis())

if __name__ == '__main__':
    app.run(port=5050, debug=False)
```

JS polling:
```javascript
async function refresh() {
  const data = await fetch('/api/kpi').then(r => r.json());
  updateGauges(data);
  updateCharts(data);
  document.getElementById('timestamp').textContent = new Date().toLocaleTimeString();
}
setInterval(refresh, 60000);
refresh();  // immediate on load
```

### Pros
- Zero Python deps beyond Flask (already commonly installed)
- Full control over every pixel — custom SVG gauges, CSS animations
- Can open as a local tab, works offline once server is running
- No flicker on refresh — JS updates DOM in place
- Easy to add WebSocket for true push updates (skip polling entirely)
- Chart.js is a single `<script>` CDN tag — no install

### Cons
- Two files to maintain (Python backend + HTML frontend)
- Need Flask installed: `pip install flask`
- JS required for anything interactive
- More code: ~200 lines Python + ~200 lines HTML/JS
- Requires `kpi_display.py` to be refactored slightly — extract `compute_kpis()` as a pure data function (currently all mixed with print statements)

### Update options in UI
- Button: `<button onclick="refresh()">Refresh now</button>`
- Recalibrate: form input → POST to `/api/calibrate?pct=N`
- Auto-refresh toggle: JS checkbox sets/clears `setInterval`

### Deps
```
flask>=3.0
```
JS (CDN, no install):
```html
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
```

### Entry point
```
web_server.py
templates/index.html
```
Launch bat:
```bat
python web_server.py
```

---

## Recommendation

**Start with Streamlit.** Here's why:

1. **Zero refactoring required** — can import `kpi_display.py` data functions directly
2. **One file, one command** — faster to build and iterate
3. **Built-in gauges and charts** — `st.metric()`, `st.progress()`, Plotly work out of the box
4. **Mule photos work** — `st.image()` handles it cleanly
5. **Dark mode** — Streamlit ships with a dark theme that matches the CLI aesthetic

HTML+JS is the better long-term choice if:
- You want true real-time push (WebSocket) without page flash
- You want pixel-perfect SVG gauges
- You're willing to refactor `kpi_display.py` to extract a `compute_kpis()` data function (which is a good idea anyway)

**Suggested path**: Build Streamlit first (TD-37 implementation). If it feels clunky after daily use, migrate to HTML+JS using the same backend data model. The HTML version is a straight upgrade, not a rewrite.

---

## Implementation Notes (for the build session)

1. Extract pure-data functions from `kpi_display.py` into `kpi_data.py` — no print statements, just returns dicts. Both CLI and web imports from this.
2. `kpi_display.py` becomes a thin formatting layer on top of `kpi_data.py`
3. `web_monitor_streamlit.py` imports from `kpi_data.py`
4. Mule photo pool: `list(Path('assets/promo').glob('*.jpg'))` — pick randomly or by weekday
5. Color scheme (consistent with TD-36 CLI): quota >80% = red, 60-80% = orange, <60% = green; ratio >15.5x = green, 12-15.5x = orange, <12x = red

---

*Spec complete. Decide: Streamlit or HTML+JS? Then pull into a /idletime build session.*
