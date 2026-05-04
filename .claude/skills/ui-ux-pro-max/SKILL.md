---
name: ui-ux-pro-max
description: "UI/UX design intelligence for web and mobile. Includes 50+ styles, 161 color palettes, 57 font pairings, 161 product types, 99 UX guidelines, and 25 chart types across 10 stacks (React, Next.js, Vue, Svelte, SwiftUI, React Native, Flutter, Tailwind, shadcn/ui, and HTML/CSS). Actions: plan, build, create, design, implement, review, fix, improve, optimize, enhance, refactor, and check UI/UX code. Projects: website, landing page, dashboard, admin panel, e-commerce, SaaS, portfolio, blog, and mobile app. Elements: button, modal, navbar, sidebar, card, table, form, and chart. Styles: glassmorphism, claymorphism, minimalism, brutalism, neumorphism, bento grid, dark mode, responsive, skeuomorphism, and flat design. Topics: color systems, accessibility, animation, layout, typography, font pairing, spacing, interaction states, shadow, and gradient. Integrations: shadcn/ui MCP for component search and examples."
---

# UI/UX Pro Max - Design Intelligence

Comprehensive design guide for web and mobile applications. Contains 50+ styles, 161 color palettes, 57 font pairings, 161 product types with reasoning rules, 99 UX guidelines, and 25 chart types across 10 technology stacks. Searchable database with priority-based recommendations.

## When to Apply

This Skill should be used when the task involves **UI structure, visual design decisions, interaction patterns, or user experience quality control**.

### Must Use

- Designing new pages (Landing Page, Dashboard, Admin, SaaS, Mobile App)
- Creating or refactoring UI components (buttons, modals, forms, tables, charts, etc.)
- Choosing color schemes, typography systems, spacing standards, or layout systems
- Reviewing UI code for user experience, accessibility, or visual consistency
- Implementing navigation structures, animations, or responsive behavior
- Making product-level design decisions (style, information hierarchy, brand expression)
- Improving perceived quality, clarity, or usability of interfaces

### Recommended

- UI looks "not professional enough" but the reason is unclear
- Receiving feedback on usability or experience
- Pre-launch UI quality optimization
- Aligning cross-platform design (Web / iOS / Android)
- Building design systems or reusable component libraries

### Skip

- Pure backend logic development
- Only involving API or database design
- Performance optimization unrelated to the interface
- Infrastructure or DevOps work
- Non-visual scripts or automation tasks

**Decision criteria**: If the task will change how a feature **looks, feels, moves, or is interacted with**, this Skill should be used.

## How to Use

### Step 1: Analyze User Requirements

Extract key information from user request:
- **Product type**: SaaS, e-commerce, portfolio, healthcare, beauty, fintech, service, entertainment, etc.
- **Target audience**: B2B / B2C, age group, usage context
- **Style keywords**: minimal, vibrant, dark mode, content-first, glassmorphism, etc.
- **Stack**: React, Next.js, Vue, Svelte, SwiftUI, React Native, Flutter, HTML/Tailwind, etc.

### Step 2: Generate Design System (REQUIRED)

Always start with `--design-system` for comprehensive recommendations:

```bash
python3 .claude/skills/ui-ux-pro-max/scripts/search.py "<product_type> <industry> <keywords>" --design-system [-p "Project Name"]
```

### Step 2b: Persist Design System (optional)

```bash
python3 .claude/skills/ui-ux-pro-max/scripts/search.py "<query>" --design-system --persist -p "Project Name"
```

### Step 3: Supplement with Detailed Searches

```bash
python3 .claude/skills/ui-ux-pro-max/scripts/search.py "<keyword>" --domain <domain> [-n <max_results>]
```

| Need | Domain | Example |
|------|--------|---------|
| Product type patterns | `product` | `--domain product "entertainment social"` |
| More style options | `style` | `--domain style "glassmorphism dark"` |
| Color palettes | `color` | `--domain color "entertainment vibrant"` |
| Font pairings | `typography` | `--domain typography "playful modern"` |
| Chart recommendations | `chart` | `--domain chart "real-time dashboard"` |
| UX best practices | `ux` | `--domain ux "animation accessibility"` |
| Landing structure | `landing` | `--domain landing "hero social-proof"` |
| AI prompt / CSS keywords | `prompt` | `--domain prompt "minimalism"` |

### Step 4: Stack Guidelines

```bash
python3 .claude/skills/ui-ux-pro-max/scripts/search.py "<keyword>" --stack <stack>
```

Available stacks: `html-tailwind`, `react`, `nextjs`, `vue`, `nuxtjs`, `svelte`, `swiftui`, `react-native`, `flutter`, `shadcn`, `jetpack-compose`

## Available Domains

| Domain | Use For |
|--------|---------|
| `product` | Product type recommendations |
| `style` | UI styles, colors, effects |
| `typography` | Font pairings, Google Fonts |
| `color` | Color palettes by product type |
| `landing` | Page structure, CTA strategies |
| `chart` | Chart types, library recommendations |
| `ux` | Best practices, anti-patterns |
| `google-fonts` | Individual Google Fonts lookup |
| `react` | React/Next.js performance |
| `web` | App interface guidelines |
| `prompt` | AI prompts, CSS keywords |

## Output Formats

```bash
# ASCII box (default)
python3 .claude/skills/ui-ux-pro-max/scripts/search.py "fintech crypto" --design-system

# Markdown
python3 .claude/skills/ui-ux-pro-max/scripts/search.py "fintech crypto" --design-system -f markdown
```

## Quick Reference - Priority Rules

| Priority | Category | Impact | Key Checks |
|----------|----------|--------|------------|
| 1 | Accessibility | CRITICAL | Contrast 4.5:1, Alt text, Keyboard nav, Aria-labels |
| 2 | Touch & Interaction | CRITICAL | Min size 44x44px, 8px+ spacing, Loading feedback |
| 3 | Performance | HIGH | WebP/AVIF, Lazy loading, Reserve space (CLS < 0.1) |
| 4 | Style Selection | HIGH | Match product type, Consistency, SVG icons (no emoji) |
| 5 | Layout & Responsive | HIGH | Mobile-first breakpoints, Viewport meta, No horizontal scroll |
| 6 | Typography & Color | MEDIUM | Base 16px, Line-height 1.5, Semantic color tokens |
| 7 | Animation | MEDIUM | Duration 150-300ms, transform/opacity only, Reduced-motion |
| 8 | Forms & Feedback | MEDIUM | Visible labels, Error near field, Submit feedback |
| 9 | Navigation Patterns | HIGH | Back predictable, Bottom nav <=5, Deep linking |
| 10 | Charts & Data | LOW | Legends, Tooltips, Accessible colors |

## Pre-Delivery Checklist

- [ ] No emojis used as icons (use SVG instead)
- [ ] Primary text contrast >=4.5:1 in both light and dark mode
- [ ] Touch targets >=44x44pt
- [ ] Safe areas respected for headers, tab bars, bottom CTA bars
- [ ] Micro-interaction timing 150-300ms
- [ ] Verified on small phone (375px) and tablet
- [ ] Reduced motion and dynamic text size supported
- [ ] All interactive elements have visible focus states
- [ ] Form fields have labels, hints, and clear error messages
- [ ] Color is not the only indicator (add icon/text)
