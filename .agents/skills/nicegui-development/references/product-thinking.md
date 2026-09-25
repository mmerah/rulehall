# Product Thinking for UI Development

## Product Understanding Before Code

**ALWAYS ask these questions before building UI features:**

1. What is the user trying to accomplish?
2. What is the user's workflow?
3. Where else in the UI does similar data/functionality exist?
4. Should this be a reusable component?

```
BAD: "I need to show an item here, let me build a card"
   -> Results in 5 different item cards across the codebase

GOOD: "Where else do we show items? Library tab, editor,
   version history, compare dialog. I should build ONE component."
```

## Component-First Thinking

**When building UI that displays data:**

1. Search for existing similar displays in the codebase
2. If >1 place shows the same data type, CREATE A COMPONENT
3. Design components with modes (e.g., "LIBRARY" vs "REFERENCE")
4. Never copy-paste UI code - extract and reuse

**Warning Signs You're Violating This:**
- Copy-pasting a `ui.card()` structure from another file
- Writing the same tabs (Preview/Raw) in multiple places
- Different button layouts for same actions in different locations

## The "Same Data, Same Face" Rule

**If the same data type appears in multiple places, it MUST:**

1. **Look the same** - Same icon, typography, color coding
2. **Behave predictably** - Expand works the same, copy works the same
3. **Be navigable** - References should link to source
4. **Use ONE component** - With modes for context-specific behavior

## Ask Before Assuming

**When requirements are unclear, ASK:**

- "What actions should be available in this context?"
- "Is this the same as [existing feature] or different?"
- "Should this work the same way as [similar feature]?"
- "Who is the user and what are they trying to accomplish?"

## Data Display Component Checklist

**Use this EVERY TIME building UI to display data:**

```markdown
## Data Type: [e.g., Prompt, Item, Campaign]

### All Display Locations
- [ ] List every place this data appears
- [ ] Include: library views, editors, version history, previews, dropdowns

### User Flow
- [ ] Can user navigate FROM reference TO source?
- [ ] Can user navigate FROM source TO usages?

### Actions by Context
| Location | View | Copy | Edit | Delete | Navigate |
|----------|------|------|------|--------|----------|
| Library  |  Y   |  Y   |  Y   |   Y    |    -     |
| Editor   |  Y   |  Y   |  -   |   -    |    Y     |
| Preview  |  Y   |  -   |  -   |   -    |    -     |

### Component Design
- Name: `[DataType]Reference` or `[DataType]Card`
- Modes: LIBRARY, REFERENCE, PREVIEW, etc.
- Shared visual elements: icon, name style, preview text
- Mode-specific elements: action buttons, navigation
```

## Modal/Dialog Button Docking

**Primary action buttons in modals MUST be always visible:**

1. **Dock to top** - For dialogs where user needs to see content while deciding
2. **Dock to bottom** - For form dialogs where user fills in then submits

**Why:** Users should NEVER scroll to find Save/Cancel buttons.

```python
with ui.dialog() as dialog, ui.card().style(
    "height: 85vh; display: flex; flex-direction: column;"
):
    # Scrollable content
    with ui.scroll_area().style("flex: 1; overflow-y: auto;"):
        # ... form content ...

    # Sticky bottom action bar
    with ui.element("div").style(
        "position: sticky; bottom: 0; padding: 1rem; "
        "border-top: 1px solid var(--border-color);"
    ):
        with ui.row().classes("justify-end"):
            ui.button("Cancel", on_click=dialog.close)
            ui.button("Save", on_click=save_handler)
```

## Recognize Reactive Mode

**If you find yourself fixing something you just built, STOP and ask:**

1. "Did I understand the requirements correctly?"
2. "Did I miss other places this affects?"
3. "Should I step back and redesign?"

**Quick Fix Red Flags - STOP immediately if doing:**
- Adding a "fix" commit for a feature you just added
- Copy-pasting UI code "just to make it work"
- Adding a TODO for "refactor later"
- Implementing something you don't fully understand