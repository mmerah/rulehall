# NiceGUI Styling Patterns

## Gap Spacing - ALWAYS Use Inline Styles

**NEVER use Tailwind `gap-*` utility classes in NiceGUI UI code.**

**Why:**
- NiceGUI bug #2171 causes excessive vertical spacing with `gap-*` on Ubuntu servers
- Inconsistent rendering between Windows/Mac dev and Ubuntu production
- Inline styles bypass NiceGUI's CSS cascade issues

### Conversion Table

| Tailwind Class | Inline Style | Use Case |
|----------------|--------------|----------|
| `gap-0` | `style("gap: 0")` | No spacing |
| `gap-1` | `style("gap: 0.25rem")` | Minimal |
| `gap-2` | `style("gap: 0.5rem")` | Small |
| `gap-3` | `style("gap: 0.75rem")` | Medium |
| `gap-4` | `style("gap: 1rem")` | Large |
| `gap-6` | `style("gap: 1.5rem")` | Extra large |

### Directional Gap

```python
# Vertical spacing only
with ui.column().style("row-gap: 0.5rem"):
    ui.label("Item 1")
    ui.label("Item 2")

# Horizontal spacing only
with ui.row().style("column-gap: 0.75rem"):
    ui.button("Button 1")
    ui.button("Button 2")
```

## Height Percentage Issues

**NEVER use `height: 100%` inside a container with only `max-height`.**

**Why:**
- CSS `height: 100%` requires parent to have explicit `height`, not just `max-height`
- Child elements collapse to 0 height
- Causes dialogs/modals to appear empty

```python
# WRONG - causes collapse
with ui.card().style("max-height: 80vh"):
    with ui.scroll_area().style("height: 100%"):  # Collapses!
        ui.label("Content")

# CORRECT - use explicit height
with ui.card().style("height: 80vh"):
    with ui.scroll_area().style("height: 100%"):
        ui.label("Content")

# CORRECT - use min-height
with ui.card().style("min-height: 300px"):
    with ui.column().classes("w-full"):
        ui.label("Content")
```

**Warning Signs:**
- Dialog appears as thin line or empty
- Content exists in code but doesn't render
- Works sometimes, breaks other times

## Injected HTML Tables

**NEVER use `table-layout: fixed` with percentage widths in `ui.html()`.**

**Why:**
- Width context from parent NiceGUI containers doesn't propagate
- Percentage widths become tiny pixel values
- Columns collapse, text displays vertically

```python
# WRONG - causes vertical text
DIFF_CSS = """
.diff-container table.diff {
    width: 100%;
    table-layout: fixed;  /* BREAKS! */
}
.diff-container table.diff col:nth-child(2) {
    width: 44%;  /* Becomes ~4 pixels */
}
"""

# CORRECT - let browser auto-layout
DIFF_CSS = """
.diff-container table.diff {
    width: 100%;
    /* No table-layout: fixed */
}
"""
```

## Side-by-Side Layouts with Charts

**Use `ui.element("div")` with explicit flexbox and `min-width: 0` on children.**

**Why:**
- Flex children have `min-width: auto` by default
- Charts have large intrinsic widths that prevent shrinking
- `min-width: 0` allows flex items to shrink properly

```python
# WRONG - panels stack vertically
with ui.row().classes("w-full"):
    with ui.column().classes("flex-1"):
        ui.highchart(options)  # Forces expansion
    with ui.column().classes("flex-1"):
        ui.highchart(options)  # Wraps to next line

# CORRECT - explicit flexbox with min-width: 0
with ui.element("div").style("display: flex; flex-direction: row; width: 100%; gap: 24px"):
    with ui.element("div").style("flex: 1; min-width: 0; display: flex; flex-direction: column"):
        ui.highchart(options)  # Shrinks to fit
    with ui.element("div").style("flex: 1; min-width: 0; display: flex; flex-direction: column"):
        ui.highchart(options)  # Side by side
```

**Warning Signs:**
- Two-column layout renders as stacked
- Charts push content to wrap
- Works without charts, breaks with charts

## Safe Quasar/Tailwind Classes

These work correctly - no inline style needed:

**Safe to use:**
- Padding: `q-pa-md`, `q-pa-lg`, `q-pa-sm`, `q-pa-xs`
- Margin: `q-mb-md`, `q-mt-md`, `q-ml-md`, `q-mr-md`
- Width: `w-full`, `w-1/2`, `w-auto`
- Flexbox: `items-center`, `justify-between`, `flex-row`, `flex-col`
- Colors: `bg-grey-9`, `text-positive`, `text-negative`
- Typography: `text-h5`, `text-body1`, `font-bold`

**Requires inline style:**
- Gap spacing: `gap-*` -> `style("gap: Xrem")`

## References

- NiceGUI Gap Issue: https://github.com/zauberzeug/nicegui/issues/2171
- Quasar Spacing Docs: https://quasar.dev/style/spacing/
- NiceGUI Styling Docs: https://nicegui.io/documentation/section_styling_appearance