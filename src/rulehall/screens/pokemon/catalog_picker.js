// A searchable catalog: a combobox over a listbox, filtered and sorted in the browser.
const LIGHT_TAG_LUMINANCE = 0.4;
// A facet shows this many chips before "more"; past the second number it is a searchable list.
const CHIPS_SHOWN = 8;
const CHIPS_MOST = 24;

export default {
  template: `
    <div class="game-picker" tabindex="-1" :autofocus="touch" @keydown="onKey">
      <div class="game-picker-head">
        <span class="game-picker-title game-title" :id="uid + '-title'">{{ title }}</span>
        <q-btn flat round icon="sym_r_close" aria-label="Close" class="game-picker-close" @click="$emit('close')" />
      </div>
      <input
        ref="search"
        class="game-picker-search"
        type="search"
        :autofocus="!touch"
        autocomplete="off"
        role="combobox"
        aria-autocomplete="list"
        aria-expanded="true"
        :aria-controls="uid + '-list'"
        :aria-activedescendant="activeId"
        :aria-labelledby="uid + '-title'"
        placeholder="Search"
        v-model="query"
        @input="active = 0"
      />
      <div v-if="facetGroups.length || orders.length > 1" class="game-picker-filters">
        <div
          v-for="group in facetGroups"
          :key="group.name"
          class="game-picker-facet"
          :class="{ 'game-picker-facet-one': group.values.length === 1 }"
          role="group"
          :aria-label="group.name"
        >
          <span v-if="group.values.length > 1" class="game-picker-label">{{ group.name }}</span>
          <q-select
            v-if="group.values.length > CHIPS_MOST"
            class="game-picker-select"
            dense outlined multiple use-chips use-input input-debounce="0"
            :options="facetOptions(group)"
            :model-value="chosen[group.name] || []"
            :aria-label="group.name"
            :placeholder="(chosen[group.name] || []).length ? '' : 'Any'"
            @filter="(text, update) => update(() => (typed = { ...typed, [group.name]: text.toLowerCase() }))"
            @update:model-value="(values) => choose(group.name, values)"
          />
          <template v-else>
            <button
              v-for="value in shownValues(group)"
              :key="value"
              type="button"
              class="game-tag game-picker-chip"
              :class="chipClass(value, isOn(group.name, value))"
              :style="chipStyle(value)"
              :aria-pressed="isOn(group.name, value)"
              @click="toggle(group.name, value)"
            >{{ group.values.length > 1 ? value : group.name }}</button>
            <button
              v-if="group.values.length > CHIPS_SHOWN"
              type="button"
              class="game-tag game-picker-chip game-picker-more"
              :aria-expanded="Boolean(opened[group.name])"
              @click="opened = { ...opened, [group.name]: !opened[group.name] }"
            >{{ opened[group.name] ? "less" : group.values.length - CHIPS_SHOWN + " more" }}</button>
          </template>
        </div>
        <div v-if="orders.length > 1" class="game-picker-facet" role="group" aria-label="Sort">
          <span class="game-picker-label">Sort</span>
          <button
            v-for="(order, at) in orders"
            :key="order.name"
            type="button"
            class="game-tag game-picker-chip"
            :class="{ 'game-picker-chip-on': at === orderAt }"
            :aria-pressed="at === orderAt"
            @click="sortBy(at)"
          >{{ order.name }}</button>
        </div>
      </div>
      <div class="game-picker-count" role="status" aria-live="polite">{{ countText }}</div>
      <q-virtual-scroll
        ref="scroller"
        class="game-picker-list"
        :items="rows"
        :virtual-scroll-item-size="columns > 1 ? 72 : 64"
        role="listbox"
        :id="uid + '-list'"
        :aria-labelledby="uid + '-title'"
        v-slot="{ item }"
      >
        <div v-if="item.head" :key="item.key" class="game-picker-group game-eyebrow" role="presentation">{{ item.head }}</div>
        <div v-else :key="item.key" class="game-picker-row" :class="{ 'game-picker-grid': columns > 1 }" :style="gridStyle" role="presentation">
          <div
            v-for="cell in item.cells"
            :key="cell.key"
            :id="optionId(cell.at)"
            role="option"
            :aria-selected="cell.at === active"
            :aria-disabled="Boolean(cell.choice.refusal)"
            :title="cell.choice.help || undefined"
            class="game-picker-option"
            :class="{
              'game-picker-active': cell.at === active,
              'game-picker-picked': picked.includes(cell.choice.id),
              'game-picker-refused': Boolean(cell.choice.refusal),
            }"
            @click="pick(cell.choice)"
            @mousemove="active = cell.at"
          >
            <div v-if="cell.choice.sprites.length" class="game-picker-sprites" aria-hidden="true">
              <template v-for="(sprite, at) in cell.choice.sprites" :key="at">
                <span v-if="sprite.width" class="game-sprite-frame" :style="frameStyle(sprite)"></span>
                <img v-else class="game-picker-image" :src="sprite.url" alt="" loading="lazy" />
              </template>
            </div>
            <div class="game-picker-body">
              <div class="game-picker-name">
                <span>{{ cell.choice.name }}</span>
                <span v-if="picked.includes(cell.choice.id)" class="game-picker-check">✓ picked</span>
              </div>
              <div v-if="cell.choice.tags.length" class="game-tags">
                <span
                  v-for="tag in cell.choice.tags"
                  :key="tag.name"
                  class="game-tag"
                  :class="tagClass(tag.colour)"
                  :style="tag.colour ? { '--game-tag': tag.colour } : undefined"
                >{{ tag.name }}</span>
              </div>
              <div v-if="cell.choice.refusal || cell.choice.brief" class="game-picker-brief">
                {{ cell.choice.refusal || cell.choice.brief }}
              </div>
            </div>
            <span v-if="cell.choice.badge" class="game-picker-badge">{{ cell.choice.badge }}</span>
          </div>
        </div>
      </q-virtual-scroll>
    </div>
  `,
  props: {
    title: String,
    choices: Array,
    facets: Array,
    orders: Array,
    columns: Number,
    picked: Array,
    pinned: Array,
    pinnedTitle: String,
  },
  emits: ["pick", "close"],
  data() {
    return {
      uid: `picker-${Math.random().toString(36).slice(2)}`,
      query: "",
      // A phone's keyboard would cover the list it opens on: the search waits for a tap there.
      touch: matchMedia("(hover: none)").matches,
      chosen: {},
      typed: {},
      opened: {},
      orderAt: 0,
      CHIPS_SHOWN,
      CHIPS_MOST,
      active: 0,
    };
  },
  computed: {
    byId() {
      return new Map(this.choices.map((choice) => [choice.id, choice]));
    },
    colours() {
      const colours = new Map();
      for (const choice of this.choices)
        for (const tag of choice.tags) if (tag.colour) colours.set(tag.name.toLowerCase(), tag.colour);
      return colours;
    },
    facetGroups() {
      return this.facets.map((name) => {
        const values = new Set();
        for (const choice of this.choices)
          for (const [facet, value] of choice.facets) if (facet === name) values.add(value);
        return { name, values: [...values].sort() };
      }).filter((group) => group.values.length);
    },
    ordered() {
      const order = this.orders[this.orderAt];
      return order ? order.ids.map((id) => this.byId.get(id)) : this.choices;
    },
    filtered() {
      const words = this.query.toLowerCase().split(/\s+/).filter(Boolean);
      const wanted = Object.entries(this.chosen).filter(([, values]) => values.length);
      return this.ordered.filter(
        (choice) =>
          words.every((word) => choice.search.includes(word)) &&
          wanted.every(([name, values]) =>
            choice.facets.some(([facet, value]) => facet === name && values.includes(value)),
          ),
      );
    },
    browsing() {
      return !this.query && !Object.values(this.chosen).some((values) => values.length);
    },
    sections() {
      const sections = [];
      if (this.browsing && this.pinned.length) {
        // The catalog's own choice carries the refusal a pinned copy may lack.
        sections.push({ head: this.pinnedTitle, choices: this.pinned.map((choice) => this.byId.get(choice.id) || choice) });
        sections.push({ head: "All", choices: this.filtered });
        return sections;
      }
      if (this.orderAt !== 0 || this.columns > 1) return [{ head: "", choices: this.filtered }];
      for (const choice of this.filtered) {
        const last = sections[sections.length - 1];
        if (last && last.head === choice.group) last.choices.push(choice);
        else sections.push({ head: choice.group, choices: [choice] });
      }
      return sections;
    },
    options() {
      return this.sections.flatMap((section) => section.choices);
    },
    rows() {
      const rows = [];
      let at = 0;
      this.sections.forEach((section, number) => {
        if (section.head) rows.push({ key: `head-${number}`, head: section.head });
        for (let start = 0; start < section.choices.length; start += this.columns) {
          const cells = section.choices.slice(start, start + this.columns).map((choice) => ({
            key: `${number}-${choice.id}`,
            choice,
            at: at++,
          }));
          rows.push({ key: `row-${number}-${start}`, cells });
        }
      });
      return rows;
    },
    activeId() {
      return this.options.length ? this.optionId(this.active) : undefined;
    },
    countText() {
      const shown = this.filtered.length;
      return shown === this.choices.length ? `${shown} choices` : `${shown} of ${this.choices.length}`;
    },
    gridStyle() {
      return this.columns > 1 ? { gridTemplateColumns: `repeat(${this.columns}, minmax(0, 1fr))` } : undefined;
    },
  },
  methods: {
    optionId(at) {
      return `${this.uid}-option-${at}`;
    },
    isOn(name, value) {
      return (this.chosen[name] || []).includes(value);
    },
    shownValues(group) {
      if (this.opened[group.name] || group.values.length <= CHIPS_SHOWN) return group.values;
      const first = group.values.slice(0, CHIPS_SHOWN);
      return [...first, ...group.values.filter((value) => !first.includes(value) && this.isOn(group.name, value))];
    },
    facetOptions(group) {
      const text = this.typed[group.name] || "";
      return group.values.filter((value) => value.toLowerCase().includes(text));
    },
    choose(name, values) {
      this.chosen = { ...this.chosen, [name]: values };
      this.active = 0;
    },
    toggle(name, value) {
      const values = this.chosen[name] || [];
      this.chosen = {
        ...this.chosen,
        [name]: values.includes(value) ? values.filter((each) => each !== value) : [...values, value],
      };
      this.active = 0;
    },
    sortBy(at) {
      this.orderAt = at;
      this.active = 0;
    },
    pick(choice) {
      if (!choice.refusal) this.$emit("pick", { choice_id: choice.id });
    },
    onKey(event) {
      if (event.target.closest(".game-picker-select")) return;
      const step = { ArrowDown: this.columns, ArrowUp: -this.columns }[event.key];
      const side = this.columns > 1 ? { ArrowRight: 1, ArrowLeft: -1 }[event.key] : undefined;
      if (step || side) {
        if (side && event.target === this.$refs.search) return;
        event.preventDefault();
        this.move(step || side);
      } else if (event.key === "Enter") {
        // Enter picks from the search or the list, never from a chip, a select or the close button.
        if (event.target !== this.$refs.search && !this.$refs.scroller.$el.contains(event.target)) return;
        event.preventDefault();
        const choice = this.options[this.active];
        if (choice) this.pick(choice);
      } else if (event.key === "Escape") {
        event.preventDefault();
        this.$emit("close");
      } else if (event.key === "/" && event.target !== this.$refs.search) {
        event.preventDefault();
        this.$refs.search.focus();
      }
    },
    move(by) {
      if (!this.options.length) return;
      this.active = Math.min(Math.max(this.active + by, 0), this.options.length - 1);
      const row = this.rows.findIndex((each) => each.cells && each.cells.some((cell) => cell.at === this.active));
      this.$refs.scroller.scrollTo(row);
    },
    frameStyle(sprite) {
      return {
        width: `${sprite.width}px`,
        height: `${sprite.height}px`,
        backgroundImage: `url(${sprite.url})`,
        backgroundPosition: `-${sprite.x}px -${sprite.y}px`,
      };
    },
    tagClass(colour) {
      if (!colour) return "";
      return light(colour) ? "game-tag-coloured game-tag-light" : "game-tag-coloured";
    },
    chipClass(value, on) {
      return [this.tagClass(this.colours.get(value.toLowerCase()) || ""), on ? "game-picker-chip-on" : ""];
    },
    chipStyle(value) {
      const colour = this.colours.get(value.toLowerCase());
      return colour ? { "--game-tag": colour } : undefined;
    },
  },
};

// The twin of panel_parts._light: a light chip takes dark text.
function light(colour) {
  const [red, green, blue] = [1, 3, 5].map((at) => parseInt(colour.slice(at, at + 2), 16) / 255);
  return 0.2126 * red ** 2.2 + 0.7152 * green ** 2.2 + 0.0722 * blue ** 2.2 > LIGHT_TAG_LUMINANCE;
}
