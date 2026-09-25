# UI Architecture and State Management

## The Problem Pattern

UI code that mixes concerns becomes brittle and untestable:

```python
# BAD: Monolithic UI handler
async def on_task_change(e):
    # Fetching data
    overview = await service.get_overview()
    # Business logic
    if overview.tasks:
        selected_task = overview.tasks[0]
    # State management
    state.selected_task = selected_task
    # More fetching
    histograms = await service.get_histograms(...)
    # UI updates
    chart.refresh(histograms)
```

Problems:
- Cannot unit test business logic without mocking UI widgets
- Cannot test data fetching without running UI
- Silent failures when guards block execution
- Bugs repeat because architecture makes them easy

## The Solution: Three Layers

Extract three layers:

1. **Data Layer** - Pure async functions, no UI dependencies
2. **Business Logic Layer** - State machines, validation, coordination
3. **UI Layer** - Thin handlers that delegate to business logic

```python
# GOOD: Separated concerns

# 1. Data Layer (fully testable, no UI)
class DataFetcher:
    async def fetch_task_data(self, task: str, time_range: str) -> TaskData:
        """Pure data fetching. Returns Pydantic models."""
        overview = await self.service.get_overview()
        histograms = await self.service.get_histograms(task, time_range)
        return TaskData(overview=overview, histograms=histograms)

# 2. Business Logic Layer (fully testable, no UI)
class PageController:
    def __init__(self, fetcher: DataFetcher):
        self.fetcher = fetcher
        self.state = PageState()

    async def handle_task_change(self, new_task: str) -> PageUpdate:
        """Coordinate data fetching and state updates."""
        if self.state.is_loading:
            return PageUpdate.defer()

        self.state.is_loading = True
        try:
            data = await self.fetcher.fetch_task_data(new_task, self.state.time_range)
            self.state.update_task(new_task, data)
            return PageUpdate.refresh_all(data)
        finally:
            self.state.is_loading = False

# 3. UI Layer (thin, delegates to controller)
async def on_task_change(e):
    logger.info(f"User selected task: {e.value}")
    update = await controller.handle_task_change(e.value)
    apply_ui_update(update)
```

## Simplicity Principles

**Before reaching for complex patterns, ask: Can this be simpler?**

### User Actions Cancel Background Updates, Not Queue Behind

```python
# SIMPLE: Cancel auto-refresh on user action
ui.timer(10.0, auto_refresh)

async def on_task_change(e):
    auto_refresh_timer.deactivate()  # Pause background
    await load_task(e.value)
    auto_refresh_timer.activate()    # Resume

# COMPLEX: Command queue for simple coordination - overkill!
class PageController:
    def __init__(self):
        self.pending_commands: list[Command] = []
```

**When queueing is justified:**
- Multiple user actions that must execute in order (undo/redo)
- Offline mode where actions must be replayed later

**When queueing is overkill:**
- Preventing auto-refresh from interfering (just cancel the timer!)
- "Loading" states (just disable buttons or show spinner)

### Progressive Complexity

Start simple, add complexity only when needed:

1. **Level 0: Simple flag** - `user_active = True`, skip auto-refresh
2. **Level 1: Debounce** - Don't auto-refresh if user acted in last 10 seconds
3. **Level 2: Cancel/restart** - Cancel ongoing operation, start new one
4. **Level 3: State machine** - Only when you have 4+ states or complex transitions
5. **Level 4: Command pattern** - When you need to preserve/replay user intent

**Most UI problems are Level 0 or 1.**

## Extract Business Logic to Controllers

**ALWAYS create a controller class for complex UI pages.**

The controller:
- Manages state
- Coordinates data fetching
- Enforces business rules
- Returns "what to update" without knowing how to update UI
- Is fully unit testable

## Make Data Fetching Pure

**Data fetching functions should return Pydantic models, not update UI directly.**

```python
# GOOD: Pure data fetching
async def fetch_data(task: str) -> TaskData:
    return TaskData(
        overview=await service.get_overview(),
        histograms=await service.get_histograms(task)
    )

# BAD: Data fetching updates UI
async def load_data():
    overview = await service.get_overview()
    overview_card.refresh(overview)  # UI dependency!
```

## Log All User Actions

**ALWAYS log user actions at the start of event handlers.**

```python
# GOOD: Logged and visible
async def on_task_change(e):
    logger.info(f"User selected task: {e.value}, is_loading={state.is_loading}")
    if state.is_loading:
        logger.warning("Load in progress, deferring task change")
        ui.notify("Loading... your selection will apply shortly")
        return
```

## Provide UI Feedback for Deferred Actions

**ALWAYS show feedback when user actions are deferred or blocked.**

```python
# GOOD: User sees feedback
if state.is_loading:
    ui.notify("Loading in progress, selection will apply after refresh", type="info")
    state.needs_reload = True
    return

# BAD: Silent failure
if state.is_loading:
    return  # User has no idea their click was ignored
```

## Use Explicit State Machines

**Use explicit state enums for complex UI state.**

```python
# GOOD: Explicit states
class PageState(Enum):
    INITIAL = "initial"
    LOADING = "loading"
    LOADED = "loaded"
    ERROR = "error"

@dataclass
class PageStateData:
    state: PageState = PageState.INITIAL

    def begin_load(self):
        if self.state == PageState.LOADING:
            raise StateError("Already loading")
        self.state = PageState.LOADING

# BAD: Implicit state
is_loading = False
has_error = False
is_initialized = False
# What state are we in? Nobody knows!
```

## Write Integration Tests for Controllers

**Test full user workflows without running actual UI.**

```python
@pytest.mark.asyncio
async def test_task_switching_during_load(fake_data_fetcher):
    controller = PageController(fake_data_fetcher)

    # Start loading task1
    load_task = asyncio.create_task(controller.handle_task_change("task1"))
    await asyncio.sleep(0.01)

    # User switches to task2 while task1 is loading
    update = await controller.handle_task_change("task2")
    assert update.deferred, "Should defer second action during loading"

    await load_task
    await controller.process_pending_commands()
    assert controller.state.selected_task == "task2"
```

## No Threads for UI - Only Asyncio

**NEVER use threads for UI concurrency.**

- NiceGUI runs on asyncio event loop (single-threaded)
- All "concurrency" is cooperative multitasking
- Threads break NiceGUI's event loop and cause race conditions

## Warning Signs

Watch for patterns indicating architectural problems:

1. **Event handler > 30 lines** - Extract controller
2. **Cannot unit test without mocking UI** - Extract business logic
3. **User action silently ignored** - Add logging and feedback
4. **Same bug recurring** - Architecture makes it easy, needs refactor
5. **Hard to reason about state** - Use explicit state machine

## The Meta-Pattern

When bugs keep recurring in the same area:
1. Don't just fix the bug - fix the architecture that made it easy
2. Extract testable components - separate concerns
3. Write integration tests - verify workflows work
4. Add observability - log everything, provide feedback

The time invested in proper architecture pays back 10x in reduced debugging.