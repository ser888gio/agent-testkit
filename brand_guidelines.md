# okjul — design guidelines

Design system reference for anyone or anything building or updating the okjul
platform. Values are normative. Where a rule and a preference conflict, the rule
wins.

---

## 1. Colour

### Brand

| Token | Hex | Pantone | Use |
|---|---|---|---|
| `ink` | `#101820` | Black 6 C | Primary text, dark surfaces, primary buttons, the mark |
| `depth` | `#002B5C` | 289 C | Emphasis surfaces, datastores in diagrams, report covers |
| `signal` | `#0057B8` | 2935 C | Links, focus, selection, active state, data emphasis, the seam |
| `slate` | `#53565A` | Cool Gray 11 C | Secondary text on light |
| `graphite` | `#A7A8AA` | Cool Gray 6 C | Secondary text on dark |
| `stock` | `#D9D9D6` | Cool Gray 1 C | Dividers, diagram structure lines |
| `paper` | `#FFFFFF` | — | Base light surface |

Pantone is the print spec. Hex is the screen spec. Do not derive new hex values
from Pantone conversions.

### Derived

| Token | Hex | Use |
|---|---|---|
| `signal-hover` | `#00459B` | Link and control hover |
| `signal-active` | `#003576` | Pressed state |
| `signal-light` | `#7FB3E8` | Signal-coloured **text on dark** — required, see §1.1 |
| `signal-subtle` | `#EEF3F9` | Selected row, info panel fill |
| `signal-border` | `#C6DAF2` | Border on `signal-subtle` |
| `panel` | `#F4F5F6` | Card and section fill on light |
| `border` | `#E3E5E7` | Default border and divider on light |
| `surface-dark` | `#18243A` | Card fill on `ink` |
| `border-dark` | `#26364F` | Border and divider on dark |
| `text-dark-muted` | `#A7A8AA` | Same as `graphite` |

### 1.1 Contrast — hard constraints

| Pair | Ratio | |
|---|---|---|
| `ink` on `paper` | 17.9:1 | ✅ |
| `paper` on `depth` | 14.0:1 | ✅ |
| `slate` on `paper` | 7.4:1 | ✅ |
| `signal` on `paper` | 6.9:1 | ✅ |
| `graphite` on `ink` | 8.4:1 | ✅ |
| `signal-light` on `ink` | 8.9:1 | ✅ |
| **`signal` on `ink`** | **2.6:1** | ❌ **never set text in it** |
| `stock` on `paper` | 1.3:1 | ❌ decorative only |

On dark surfaces, Signal is permitted for **lines, arrows, rules and numerals
≥32px only**. For any text, use `signal-light`.

### 1.2 The Signal rule

Signal is a mark, not a fill. Permitted: links, focus rings, selection, active
indicators, chart series, diagram flow lines, the logo seam, large numerals.
Prohibited: page backgrounds, section backgrounds, primary button fills, hero
panels. Target under 3% coverage of any screen.

**Primary buttons are `ink`, not `signal`.**

### 1.3 Severity — functional, outside the brand palette

Report and finding severity is a separate system. Do not substitute brand
colours.

| Level | Text/icon | 10% tint fill |
|---|---|---|
| Critical | `#B3261E` | `#F8EBEA` |
| High | `#B84200` | `#F9EFE9` |
| Medium | `#7A5C00` | `#F6F2E5` |
| Low | `#53565A` | `#F1F1F2` |
| Pass | `#17614A` | `#E8F1EE` |

Never encode severity by colour alone — always pair with a text label.

---

## 2. Typography

| Family | Weights | Role |
|---|---|---|
| **Archivo** | 400, 600, 700 | All UI and prose |
| **IBM Plex Mono** | 400, 600 | Run output, finding IDs, endpoints, code, diagram annotations |

Both OFL. `@fontsource/archivo`, `@fontsource/ibm-plex-mono`.

```css
--font-sans: Archivo, "Helvetica Neue", Arial, sans-serif;
--font-mono: "IBM Plex Mono", "SF Mono", Consolas, monospace;
```

**Rule:** Archivo for anything a person wrote. Plex Mono for anything a machine
produced. Never mix.

### Scale

| Token | Size / line-height | Weight |
|---|---|---|
| `display` | 40 / 44 | 700 |
| `h1` | 32 / 38 | 600 |
| `h2` | 24 / 30 | 600 |
| `h3` | 19 / 26 | 600 |
| `body` | 16 / 24 | 400 |
| `small` | 14 / 20 | 400 |
| `caption` | 13 / 18 | 400 |
| `mono` | 14 / 22 | 400 |
| `mono-sm` | 13 / 20 | 400 |

Headline tracking `-0.02em`. Mono tracking `0.02em`. Body tracking `0`.
Sentence case everywhere. No ALL-CAPS except section kickers at `caption` with
`0.12em` tracking. Minimum rendered text size 13px.

---

## 3. Layout and primitives

| Property | Value |
|---|---|
| Spacing scale | 4, 8, 12, 16, 24, 32, 48, 64, 96 |
| Border radius | **0 everywhere.** No exceptions, including avatars and pills |
| Border width | 1px, `border` / `border-dark` |
| Shadows | **None.** Separate surfaces by fill, never elevation |
| Gradients | **None** |
| Content max width | 1200px, 24px gutters |
| Alignment | Left. No centred body text anywhere |
| Motion | 120ms ease-out for hover/focus, 200ms for panels. Nothing else |

---

## 4. Components

| Component | Spec |
|---|---|
| **Button, primary** | `ink` fill, `paper` text, 40px height, 16px padding-x, 0 radius. Hover `#1D2836` |
| **Button, secondary** | Transparent, 1px `ink` border, `ink` text. Hover `panel` fill |
| **Button, tertiary** | `signal` text, no fill, no border. Underline on hover |
| **Button, destructive** | `#B3261E` fill, `paper` text |
| **Link** | `signal`, underline on hover. On dark: `signal-light` |
| **Focus** | 2px `signal` ring, 2px offset. Never remove |
| **Input** | `paper` fill, 1px `#C8CBCE` border, 40px height, 0 radius. Focus: border `signal` + ring |
| **Card** | `panel` fill, no border, no radius, no shadow. On dark: `surface-dark` |
| **Panel, emphasis** | `depth` fill, `paper` text |
| **Divider** | 1px `border`, full content width |
| **Table** | Header `caption` in `slate`; 1px `border` row dividers; no zebra striping; numerals in mono, right-aligned |
| **Code / run output** | `ink` fill, `graphite` text, `signal-light` for IDs, mono, 16px padding |
| **Finding ID** | Mono 600, `signal`, format `OKJ-2026-0142` |
| **Badge** | Severity tint fill, severity text colour, 0 radius, `caption` size, 4px/8px padding |
| **Chart** | Single `signal` series; gridlines `#EDEEEF`; no legend when one series; no 3D, no donut |
| **Skeleton / empty** | `panel` blocks. No spinners longer than 400ms without a status line |

---

## 5. Diagrams

- Main flow: solid `signal`, 3px, arrowheads.
- Feedback loops: dashed `signal`, 2.5px, `9 7` dash array. Dashes mean feedback and nothing else.
- Supporting connectors: `stock`, 2px, no arrowheads.
- Primary nodes: `ink` fill, `paper` title, `graphite` caption.
- Datastores: `depth` cylinders.
- Not executed / optional: dashed `stock` outline on `paper`.
- Flow left to right. Loops route above or below, never through. Sharp corners.

Reference implementation: `okjul-brand/diagrams/okjul-architecture.svg`.

---

## 6. Logo in product

| Context | File |
|---|---|
| App nav, light | `logo/vector/lockup-horizontal/okjul-lockup-seam.svg` |
| App nav, dark | `logo/vector/lockup-horizontal/okjul-lockup-seam-reverse.svg` |
| Favicon, app icon | `logo/vector/mark/okjul-mark-seam.svg` |
| Inline, CSS-coloured | `logo/vector/*/okjul-*-currentcolor.svg` |

Clear space: 25% of mark height on all sides. Minimum: mark 16px, horizontal
lockup 90px wide. Never recolour the halves separately, add effects, round
corners, rotate, stretch, or retype the wordmark in a live font. Signal appears
in the mark only as the seam.

---

## 7. Never

- Rounded corners
- Box shadows or gradients
- Signal as a background or primary button fill
- Signal text on a dark surface
- Brand colours used for severity, or severity colours used for brand
- Colour as the only carrier of meaning
- Centred body text
- A fourth typeface, or a fifth grey
- Text below 13px

---

## 8. Tokens

```css
:root {
  --ink:#101820; --depth:#002B5C; --signal:#0057B8;
  --slate:#53565A; --graphite:#A7A8AA; --stock:#D9D9D6; --paper:#FFFFFF;

  --signal-hover:#00459B; --signal-active:#003576; --signal-light:#7FB3E8;
  --signal-subtle:#EEF3F9; --signal-border:#C6DAF2;
  --panel:#F4F5F6; --border:#E3E5E7;
  --surface-dark:#18243A; --border-dark:#26364F;

  --sev-critical:#B3261E; --sev-high:#B84200; --sev-medium:#7A5C00;
  --sev-low:#53565A; --sev-pass:#17614A;

  --font-sans:Archivo,"Helvetica Neue",Arial,sans-serif;
  --font-mono:"IBM Plex Mono","SF Mono",Consolas,monospace;

  --radius:0; --border-w:1px;
  --space-1:4px; --space-2:8px; --space-3:12px; --space-4:16px;
  --space-5:24px; --space-6:32px; --space-7:48px; --space-8:64px; --space-9:96px;
  --ease:cubic-bezier(0,0,.2,1); --dur-fast:120ms; --dur:200ms;
}
```

```js
// tailwind.config.js
theme: {
  extend: {
    colors: {
      ink:'#101820', depth:'#002B5C', paper:'#FFFFFF',
      signal:{DEFAULT:'#0057B8',hover:'#00459B',active:'#003576',
              light:'#7FB3E8',subtle:'#EEF3F9',border:'#C6DAF2'},
      slate:'#53565A', graphite:'#A7A8AA', stock:'#D9D9D6',
      panel:'#F4F5F6', border:'#E3E5E7',
      surfacedark:'#18243A', borderdark:'#26364F',
      sev:{critical:'#B3261E',high:'#B84200',medium:'#7A5C00',
           low:'#53565A',pass:'#17614A'},
    },
    fontFamily:{
      sans:['Archivo','Helvetica Neue','Arial','sans-serif'],
      mono:['IBM Plex Mono','SF Mono','Consolas','monospace'],
    },
    borderRadius:{none:'0',DEFAULT:'0',sm:'0',md:'0',lg:'0',xl:'0',full:'0'},
    boxShadow:{none:'none',DEFAULT:'none',sm:'none',md:'none',lg:'none'},
  }
}
```
