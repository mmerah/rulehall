const SOUND_KEY = "rulehall.dice.sound";
const SOUND_EVENT = "rulehall-sound";
const STYLES = ["style/battle.css", "style/battle-log.css"];
const SCRIPTS = [
  "js/lib/jquery-1.11.0.min.js",
  "js/lib/html-sanitizer-minified.js",
  "js/battle-sound.js",
  "js/battledata.js",
  "data/pokedex-mini.js",
  "data/pokedex-mini-bw.js",
  "data/graphics.js",
  "data/pokedex.js",
  "data/moves.js",
  "data/abilities.js",
  "data/items.js",
  "data/teambuilder-tables.js",
  "js/battle-tooltips.js",
  "js/battle.js",
];

const STYLE = `
.game-showdown { width: 100%; max-width: 36rem; margin-inline: auto }
.game-showdown-stage { position: relative; overflow: hidden }
.game-showdown .battle { top: 0 !important; left: 0 !important; transform-origin: top left }
.game-showdown .battle-log { position: static !important; height: 4rem !important }
.game-showdown-wild .trainer-far .trainersprite { visibility: hidden }
`;

export default {
  template: `
    <div class="game-showdown" :class="{ 'game-showdown-wild': wild }">
      <div ref="stage" class="game-showdown-stage"><div ref="frame"></div></div>
      <div ref="log" class="battle-log"></div>
    </div>
  `,
  props: { base: String, lines: Array, sprites: String, music: Boolean, wild: Boolean },
  created() {
    this.queued = [];
  },
  async mounted() {
    window.exports = window;
    window.Config = { routes: { client: location.host + this.base } };
    const still = this.sprites === "2d";
    window.Storage = { prefs: (key) => ({ noanim: still, bwgfx: still })[key] };
    if (!window.Battle) await this.load();
    if (this.$.isUnmounted) return;
    this.battle = new Battle({ $frame: $(this.$refs.frame), $logFrame: $(this.$refs.log) });
    this.battle.setMute(!this.music || localStorage.getItem(SOUND_KEY) === "off");
    this.sound = (event) => this.battle.setMute(!this.music || !event.detail);
    window.addEventListener(SOUND_EVENT, this.sound);
    for (const line of this.lines) this.battle.add(line);
    this.battle.seekTurn(Infinity);
    this.resizer = new ResizeObserver(() => this.fit());
    this.resizer.observe(this.$el);
    for (const lines of this.queued.splice(0)) this.add(lines);
  },
  unmounted() {
    window.removeEventListener(SOUND_EVENT, this.sound);
    this.resizer?.disconnect();
    this.battle?.destroy();
  },
  methods: {
    add(lines) {
      if (!this.battle) {
        this.queued.push(lines);
        return;
      }
      for (const line of lines) this.battle.add(line);
      this.battle.play();
    },
    async load() {
      const url = (path) => `${this.base}/${path}`;
      document.head.append(Object.assign(document.createElement("style"), { textContent: STYLE }));
      await Promise.all(
        STYLES.map((path) => attach("link", { rel: "stylesheet", href: url(path) })),
      );
      for (const path of SCRIPTS) await attach("script", { src: url(path) });
      // The client asks for each sound over https, which this server does not speak.
      BattleSound.getSound = (path) => (BattleSound.soundCache[path] ??= new Audio(url(path)));
    },
    fit() {
      const frame = this.$refs.frame;
      const scale = this.$el.clientWidth / frame.offsetWidth;
      frame.style.transform = `scale(${scale})`;
      this.$refs.stage.style.height = `${frame.offsetHeight * scale}px`;
      // Mounted in a hidden column, the log could not scroll; it can once it has a size.
      this.battle.scene.log.updateScroll();
    },
  },
};

function attach(tag, attributes) {
  return new Promise((resolve, reject) => {
    const element = Object.assign(document.createElement(tag), attributes);
    element.onload = resolve;
    element.onerror = () => reject(new Error(`${tag} ${attributes.href ?? attributes.src}`));
    document.head.append(element);
  });
}
