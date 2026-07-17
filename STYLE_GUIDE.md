# FIN AI RM Workstation — Style Guide

Extracted from `public/app.css`, `public/cockpit-v3.css`, `public/insights.css`, `public/technical.css`.

Design character: **institutional finance**. Warm paper-grey canvas (not white), deep navy structure, a single orange accent used sparingly for "active" and "recommended" states. Generous rounding (10–22px), soft borders, minimal shadows. Bilingual Thai/English.

---

## 1. Color tokens

Drop these on `:root`.

```css
:root {
  /* Brand */
  --navy: #18243f;          /* headers, primary buttons, headings */
  --navy-2: #26365b;        /* primary button hover */
  --orange: #ef7622;        /* THE accent — active nav, recommended, eyebrows */
  --orange-soft: #fff1e7;   /* accent tint background */

  /* Text */
  --ink: #172033;           /* body */
  --muted: #687188;         /* labels, captions, secondary */

  /* Surfaces (warm greys, never pure white) */
  --canvas: #e3e5e8;        /* page background — darkest */
  --surface: #f2f1ed;       /* nav bar, panels */
  --surface-raised: #f8f7f4; /* cards — lightest */
  --line: #d1d4d9;          /* all borders */

  /* Semantic pairs (color + soft background) */
  --green: #17745a;  --green-soft: #eaf7f2;   /* normal / on-track */
  --amber: #a86508;  --amber-soft: #fff7e5;   /* review / caution */
  --red:   #b23b3b;  --red-soft:   #fff0f0;   /* confirm / overdue */
  --blue:  #315ea8;  --blue-soft:  #eef4ff;   /* informational, links */

  --shadow: 0 18px 50px rgba(20, 32, 58, 0.14);
}
```

### Extended tokens (cockpit surface)

```css
--care: #b33a46;    --care-soft: #fff0f1;   /* client-care lane */
--growth: #176f5b;  --growth-soft: #eaf7f2; /* growth lane */
--slate: #516078;                            /* tertiary text */
```

**Rule:** every status color comes as a `--x` / `--x-soft` pair — text uses the saturated value, its background uses the tint. Never invent a one-off status color.

### Ambient background

```css
background:
  radial-gradient(circle at 12% 0%, rgba(239,118,34,.08), transparent 26rem),
  var(--canvas);
```

---

## 2. Typography

```css
font-family: Inter, "Noto Sans Thai", "Leelawadee UI", Tahoma, system-ui, sans-serif;
```

System-stacked, no webfont loading. Thai fallback is mandatory.

| Role | Size | Weight | Color |
|---|---|---|---|
| `h1` | `clamp(28px, 3vw, 40px)`, line-height 1.18, letter-spacing -.02em | — | `--navy` |
| `h2` (section) | 20px | — | `--navy` |
| `h3` (card) | 15–17px | — | `--navy` |
| Body | 13px, line-height 1.55–1.7 | — | `#3f495e`–`#515b70` |
| Caption / label | 10–12px | 700–800 | `--muted` |
| Eyebrow | 11px, uppercase, letter-spacing .1em | 800 | `--orange` |
| Metric value | 17–30px | 800–900 | `--navy` |

Weight scale is heavy: 700 / 750 / 800 / 850 / 900. Small text is *always* bold to compensate for size. `750` and `850` are used deliberately — keep them.

Uppercase + wide letter-spacing is reserved for eyebrows and lead labels only.

---

## 3. Radius scale

| Value | Use |
|---|---|
| `6–7px` | kbd, tiny badges |
| `9–10px` | buttons, icon buttons, small tints |
| `12–13px` | inputs, inner cards, tint boxes |
| `14–16px` | cards, list rows |
| `18–22px` | banners, overlay panels |
| `999px` | pills, chips, progress bars |
| `50%` | avatars, status dots |

---

## 4. Layout

```css
.app-shell  { max-width: 1280px; margin: 0 auto; padding: 34px 32px 70px; }
.v3-shell   { max-width: 1440px; padding-top: 28px; }
```

Sticky chrome stack:
- Topbar — 74px, `--navy`, `z-index: 40`
- Nav — 58px, `--surface`, `top: 74px`, `z-index: 35`
- Scrim `z-index: 60` · Overlay `70` · Menus `80` · Toast `120`

CSS Grid throughout, with `minmax(0, Nfr)` fractional columns. Standard gaps: **8–10px** inside cards, **14–18px** between cards, **20–34px** between sections.

Breakpoints: `980px` (multi-col → 2-col/stack) and `680px` (single column, overlay goes full-bleed, horizontal scroll for tab strips).

---

## 5. Components

### Card
```css
background: var(--surface-raised);
border: 1px solid var(--line);
border-radius: 16px;
padding: 20px;
```

### Interactive row
```css
transition: border-color .15s ease, box-shadow .15s ease, transform .15s ease;
&:hover {
  border-color: #bbc4d3;
  box-shadow: 0 8px 22px rgba(24,36,63,.08);
  transform: translateY(-1px);
}
```

### Buttons
```css
.primary-button   { background: var(--navy); color: #fff; box-shadow: 0 4px 10px rgba(24,36,63,.18); }
.primary-button:hover { background: var(--navy-2); }
.primary-button.orange { background: var(--orange); }
.secondary-button { background: var(--surface-raised); color: var(--navy); border: 1px solid #c5c9d0; }
.soft-button      { background: var(--blue-soft); color: var(--blue); }
/* all: border-radius: 10px; padding: 10px 14px; font-weight: 750; font-size: 13px; */
:disabled { opacity: .56; box-shadow: none; cursor: not-allowed; }
```

### Pills
```css
.status-pill { border-radius: 999px; padding: 6px 9px; font-size: 11px; font-weight: 750;
               background: var(--amber-soft); color: var(--amber); }
```
Swap in any semantic pair. `.state-normal` / `.state-review` / `.state-confirm` / `.state-unchecked` map to green / amber / red / muted.

### Selection state
Selected or recommended items get a **2px orange border + soft tint** — never a checkmark alone:
```css
.option-card.is-recommended { border: 2px solid var(--orange); background: #f6eee7; }
.scenario-button.is-active  { border: 2px solid var(--orange); background: var(--orange-soft); }
```

### Active tab
Underline, not fill:
```css
.nav-item.is-active { color: var(--navy); }
.nav-item.is-active::after {
  content: ""; position: absolute; left: 15px; right: 15px; bottom: 0;
  height: 3px; border-radius: 3px 3px 0 0; background: var(--orange);
}
```

### Callout boxes
Tinted, borderless-or-hairline, 12–13px radius:
- Info → `--blue-soft` bg, `#344c79` text
- Guard/warning → `--amber-soft` bg, `#75501a` text
- Missing/error → `--red-soft` bg, `--red` text

### Accent quote block
```css
border-left: 4px solid var(--orange);
border-radius: 0 14px 14px 0;
background: var(--surface-raised);
padding: 18px;
```

### Icon tile
42×42, radius 13, soft-tint bg + matching saturated glyph color, `font-weight: 900`.

### Inverted metric panel
`background: var(--navy)`, white value at 30px/800, `#c6d0e4` supporting text.

### Progress / allocation bar
```css
.bar { height: 9px; background: #edf0f4; border-radius: 999px; overflow: hidden; }
.bar span { height: 100%; border-radius: inherit; background: var(--blue); }  /* actual */
.target .bar span { background: var(--orange); }                              /* target */
```
Blue = actual, orange = target. Consistent everywhere.

---

## 6. Motion

Fast and small. Nothing over 250ms.

```css
transition: .15s–.2s ease;
@keyframes fade-in { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
```

Page enter: `.22s ease-out` rise of 5px. Overlay enter: 18px translate + opacity. Spinner: 4px ring, `--orange` top border, `.75s linear infinite`.

---

## 7. Forms & focus

```css
button, input, select, textarea { font: inherit; }
button { cursor: pointer; }
:focus-visible { outline: 3px solid rgba(239, 118, 34, 0.28); outline-offset: 2px; }
input[type=checkbox], input[type=radio] { accent-color: var(--orange); }
```

On the navy topbar, focus switches to `2px solid #ff9a50` with `outline-offset: 4px`.

Search box: `--surface-raised` fill, `1px --line`, radius 12, `padding: 10px 13px`, borderless inner input.

---

## 8. Porting checklist

1. Copy the token block in §1 to `:root`.
2. Set `background: var(--canvas)` on `html` and `body` — the warm grey is the whole look; a white page loses it.
3. Set the font stack, keeping a Thai fallback if you have Thai text.
4. Add the global `box-sizing`, `font: inherit`, and `:focus-visible` rules from §7.
5. Build with the card + row + pill recipes; reach for semantic pairs rather than new colors.
6. Keep orange rare — active nav, recommended option, eyebrow, focus ring. Everything else is navy, muted, or a semantic pair.
