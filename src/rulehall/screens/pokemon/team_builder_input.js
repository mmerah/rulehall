// The team builder's page-wide input: shortcuts, focus kept across redraws, and a swipe between slots.
const SHORTCUTS = { s: "save", v: "import", c: "export" };
const SWIPE_MIN = 60;

export default {
  template: `<span hidden></span>`,
  props: { active: Boolean },
  emits: ["shortcut", "swipe"],
  mounted() {
    this.root = this.$el.closest(".game-builder");
    this.onKey = (event) => {
      if (!this.active || !(event.ctrlKey || event.metaKey) || event.altKey) return;
      const name = SHORTCUTS[event.key.toLowerCase()];
      // Ctrl+S saves; Ctrl+Shift+V and C import and export, so plain copy and paste still work.
      if (!name || (name === "save") === event.shiftKey) return;
      if (document.querySelector(".q-dialog")) return;
      event.preventDefault();
      this.$emit("shortcut", { name });
    };
    this.onFocus = (event) => {
      const marked = event.target.closest?.("[data-focus]");
      if (marked && this.root.contains(marked)) this.focused = marked.dataset.focus;
    };
    this.onTouchStart = (event) => {
      const touch = event.touches[0];
      const inEditor = event.target.closest(".game-builder-editor");
      const onSlider = event.target.closest(".q-slider, .game-builder-pinned, .game-points-quick");
      this.touch = event.touches.length === 1 && inEditor && !onSlider ? [touch.clientX, touch.clientY] : null;
    };
    this.onTouchEnd = (event) => {
      if (!this.touch) return;
      const touch = event.changedTouches[0];
      const [dx, dy] = [touch.clientX - this.touch[0], touch.clientY - this.touch[1]];
      this.touch = null;
      if (Math.abs(dx) >= SWIPE_MIN && Math.abs(dx) > 2 * Math.abs(dy)) this.$emit("swipe", { by: dx < 0 ? 1 : -1 });
    };
    document.addEventListener("keydown", this.onKey);
    document.addEventListener("focusin", this.onFocus);
    this.root.addEventListener("touchstart", this.onTouchStart, { passive: true });
    this.root.addEventListener("touchend", this.onTouchEnd, { passive: true });
  },
  unmounted() {
    document.removeEventListener("keydown", this.onKey);
    document.removeEventListener("focusin", this.onFocus);
    this.root.removeEventListener("touchstart", this.onTouchStart);
    this.root.removeEventListener("touchend", this.onTouchEnd);
  },
  methods: {
    refocus() {
      requestAnimationFrame(() => {
        const lost = !document.activeElement || document.activeElement === document.body;
        if (!this.active || !lost || !this.focused) return;
        this.root.querySelector(`[data-focus="${this.focused}"]`)?.focus({ preventScroll: true });
      });
    },
    focusFirst(selector) {
      requestAnimationFrame(() => {
        const target = this.root.querySelector(selector);
        target?.scrollIntoView({ block: "center", behavior: "smooth" });
        target?.focus({ preventScroll: true });
      });
    },
  },
};
