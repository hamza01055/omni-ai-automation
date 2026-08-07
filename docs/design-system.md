# Design system

The console is an operations surface. Someone watches four inboxes and decides
what a machine may do unsupervised. Every choice below serves that job, and the
system exists so nobody has to re-decide these things per screen.

Tokens live in `frontend/tailwind.config.js`. Components live in
`frontend/src/components/ui/`. If a value is hardcoded in a component, that is a
bug — it belongs in a token.

---

## Design tokens

### Colour

Four families, each with one job. Nothing else gets to be colourful.

| Family | Range | Purpose |
|--------|-------|---------|
| `ink` | 50–950 | Ground, surfaces, borders, text. Cool graphite, low chroma. |
| `signal` | `DEFAULT`, `soft`, `dim` | **Reserved for "a person is needed."** Primary buttons, the approval badge, the review confidence band. |
| Outcome | `ok`, `warn`, `risk` | State only — healthy/degraded, sent/failed, high/low score. |
| `channel` | `whatsapp`, `instagram`, `facebook`, `x` | Data encoding. Each platform's own colour, because operators already recognise them. |

The restraint on `signal` is the point. If amber were also used for emphasis,
hover states, and headings, it would stop meaning anything, and the one thing
the interface most needs to communicate — *this needs you* — would be lost in
decoration. Amber appears on roughly 2% of pixels by design.

Semantic surface variables (`--surface`, `--surface-raised`, `--line`, `--text`,
`--text-muted`) are defined in `styles.css` and swap under `.dark`. Components
reference these rather than `ink-800` directly, so light mode is one definition,
not a second set of classes on every element.

### Typography

Three faces, three roles, and the role carries meaning:

| Token | Face | Used for |
|-------|------|----------|
| `font-display` | Space Grotesk | Headings, metric values |
| `font-sans` | Inter | Everything a person reads as prose |
| `font-mono` | JetBrains Mono | **Machine-produced values only** |

The mono rule is load-bearing. Confidence scores, lead scores, message ids,
latencies, token counts, and timestamps are set in mono; a human's typed note is
not. An operator scanning a screen can tell at a glance what a model produced
versus what a colleague wrote, without reading a label.

Sizes beyond Tailwind's defaults:

| Token | Size | Used for |
|-------|------|----------|
| `text-micro` | 11px, `0.06em` tracking | Eyebrows, badges, table headers |
| `text-meta` | 12px | Secondary text, timestamps, hints |
| `text-metric` | 28px, tight | Dashboard figures |

### Spacing, radius, elevation

Spacing uses Tailwind's default 4px scale unmodified — inventing a second scale
buys nothing. Radius is two values: `rounded-card` (10px) for containers,
`rounded-control` (7px) for anything interactive. Two shadows only: `shadow-raise`
for lifted surfaces, `shadow-glow` for signal-coloured focus.

### Motion

`160ms` default transition. Two named animations: `slide-up` for content
entering, `pulse-dot` for a live/pending indicator. Reduced-motion is honoured
globally in `styles.css` — every animation collapses to 0.01ms rather than being
individually guarded.

---

## Components

### ConfidenceGauge — the signature element

The one thing this console is remembered by. Everywhere the AI made a decision,
the same three-part reading appears: five segments filled to the score, the raw
number in mono, and which policy band it landed in.

| Variant | Use when |
|---------|----------|
| `bar` | In lists and table rows — gauge plus number, band conveyed by colour |
| `full` | In detail panes — adds the band label and a sentence explaining the decision |

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `confidence` | `number \| null` | — | 0–1 score. `null` renders as `—` and reads as "needs a person". |
| `intent` | `Intent \| null` | — | Lets the gauge apply always-escalate intents, so a 0.99 refund still reads red. |
| `variant` | `'bar' \| 'full'` | `'bar'` | |

Bands mirror `backend/app/ai/router.py` exactly:

| Band | Range | Colour | Meaning |
|------|-------|--------|---------|
| `auto` | ≥ 0.90 | `ok` | Answered automatically |
| `review` | 0.70–0.89 | `signal` | Sent, but worth a look |
| `human` | < 0.70, or an always-escalate intent | `risk` | Needs a person |

**Accessibility.** The whole gauge is one `role="img"` with an `aria-label`
reading the score and the band in words. Colour never carries the meaning alone —
the fill count and the number both encode it, and `full` adds text.

**Do / don't:**

| ✅ Do | ❌ Don't |
|------|---------|
| Show it anywhere AI acted | Show it for human-written messages |
| Let `intent` drive the band for sensitive topics | Compute the band inline in a component |
| Use `full` where the operator is deciding | Use `full` in a dense list |

### Button

| Variant | Use when |
|---------|----------|
| `primary` | The one action that moves the task forward. Signal-coloured — one per view. |
| `secondary` | Supporting actions of equal weight to each other |
| `ghost` | Low emphasis inside dense surfaces (icon buttons, toolbars) |
| `danger` | Destructive or irreversible |

Sizes `sm` / `md` / `lg`. `loading` keeps the label and the width, so the layout
never jumps and the person can still read what they triggered; `aria-busy` is set.

### Field

Label is always a real `<label>`, never a placeholder standing in for one.
`hint` explains the constraint *before* the person hits it; `error` replaces the
hint, gets `role="alert"`, and sets `aria-invalid`. `aria-describedby` wires up
whichever is showing.

### ChannelBadge

Coloured dot plus platform name. The `live` prop dims the dot and appends
"· sandbox" when the channel is running on its mock adapter — so nobody
mistakes sandbox traffic for real traffic. An `sr-only` platform name is always
present, so colour is never the only signal.

### StatusPill

Five tones (`neutral`, `ok`, `warn`, `risk`, `info`) at micro size, uppercase,
with an inset ring. For enum-shaped state: conversation status, lead status,
content status, channel mode.

### EmptyState

An empty screen is an invitation to act. It names the next step rather than
apologising for having nothing. `Placeholder` builds on it for routes not yet
implemented, naming the step that delivers each — honest scaffolding beats fake
screens.

---

## Patterns

**Navigation** groups by what the operator is doing, not by data model:
Conversations (the live surface) → Pipeline (what it feeds) → System (the
machinery). The approvals count is the only badge in the sidebar, because it is
the only number that means "act now".

**Density.** Lists are compact; detail panes breathe. An operator scans the
inbox and dwells on one conversation, so those two contexts get different
spacing rather than a single compromise.

**Errors and empties** speak in the interface's voice. They explain what
happened and how to fix it. They do not apologise and are never vague. Error
copy from the backend arrives in the same register — `"WhatsApp is not
configured. Set WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID."` is a
sentence a person can act on.

**Vocabulary.** An action keeps its name through the whole flow: the button that
says *Approve* produces a state that says *Approved*. Things are named by what
the person controls, not by how the system is built — "Channels", not "webhook
subscriptions".

---

## Quality floor

Not announced in the UI, just always true: responsive to mobile, visible
keyboard focus on every interactive element (`:focus-visible` with a signal
ring), reduced motion respected, colour never the sole carrier of meaning, and
every form control labelled.

---

## Open questions

- The inbox three-pane layout needs a mobile story. Current thinking is a
  stack with back navigation rather than a drawer.
- Lead score (0–100) and confidence (0–1) are both mono numerics but mean very
  different things. They may need visually distinct treatments to avoid being
  read as the same measure.
- Dark is the default because this console is watched for long stretches. Light
  mode is implemented but has had less design attention.
