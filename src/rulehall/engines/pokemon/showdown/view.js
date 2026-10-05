const SOUND_KEY = "rulehall.dice.sound";
const SOUND_EVENT = "rulehall-sound";
const BGM_VOLUME = 30;
// The setBgm numbers of BattleScene in data/graphics.js.
const BATTLE_MUSIC = { "bw-trainer": 5, "bw-rival": 6, "bw2-kanto-gym-leader": 8, "spl-elite4": -101 };
// The image files of each Showdown battle background generation, under the client root.
const BATTLE_BACKGROUND_FILES = {
  gen6: (name) => `sprites/gen6bgs/bg-${name}.jpg`,
  gen5: (name) => `fx/bg-${name}.png`,
  gen4: (name) => `fx/bg-gen4-${name}.png`,
  gen3: (name) => `fx/bg-gen3-${name}.png`,
};
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

// The frame is 640x360 with a 100px bar each side; the page shows the bars' and the weather's facts itself.
const FRAME_WIDTH = 640;
const FRAME_HEIGHT = 360;
const FIELD_WIDTH = 440;
const STYLE = `
.game-showdown { position: relative; overflow: hidden }
.game-showdown .battle { top: 0 !important; left: 0 !important; border: 0; transform-origin: top left }
.game-showdown .leftbar, .game-showdown .rightbar, .game-showdown .weather em { display: none }
.game-showdown-journal .game-showdown-log.battle-log {
  position: static; width: auto; height: auto; border: 0; background: transparent;
  color: var(--game-muted); font: .8rem/1.4 var(--game-body);
}
.game-showdown-journal .inner { padding: .35rem 2rem .1rem .7rem }
.game-showdown-journal .inner-preempt { padding: 0 2rem .35rem .7rem }
.game-showdown-journal .battle-history { margin: 0; padding: .05rem 0 }
.game-showdown-journal .inner > :last-child { color: var(--game-text) }
.game-showdown-journal .game-showdown-log.battle-log h2 {
  margin: .5rem 0 .15rem; padding: 0; border: 0; background: none; color: var(--game-accent);
  font: 700 .62rem/1.4 var(--game-body); letter-spacing: .08em; text-transform: uppercase;
}
.game-showdown-journal .spacer { height: .3rem }
`;

export default {
  template: `
    <div class="game-showdown">
      <div ref="frame"></div>
      <Teleport defer :to="dock">
        <div class="dark game-showdown-journal" :class="{ 'game-showdown-journal-open': open }">
          <div ref="log" class="battle-log game-showdown-log" @click="open = !open"></div>
        </div>
      </Teleport>
    </div>
  `,
  props: {
    base: String,
    lines: Array,
    sprites: String,
    music: Boolean,
    dock: String,
    battleBackground: String,
    battleMusic: String,
  },
  data: () => ({ open: false }),
  created() {
    this.queued = [];
  },
  async mounted() {
    window.exports = window;
    window.Config = { routes: { client: location.host + this.base } };
    const still = this.sprites === "2d";
    window.Storage = { prefs: (key) => ({ noanim: still, bwgfx: still })[key] };
    if (!window.Battle) await this.load();
    // The log is teleported to its dock only once the rest of the page has mounted.
    await this.$nextTick();
    if (this.$.isUnmounted) return;
    this.battle = new Battle({ $frame: $(this.$refs.frame), $logFrame: $(this.$refs.log) });
    this.pinBattleBackgroundAndMusic();
    this.battle.setMute(!this.music || localStorage.getItem(SOUND_KEY) === "off");
    this.sound = (event) => this.battle.setMute(!this.music || !event.detail);
    window.addEventListener(SOUND_EVENT, this.sound);
    for (const line of this.lines) this.battle.add(line);
    this.battle.seekTurn(Infinity);
    this.resizer = new ResizeObserver(() => this.fit());
    this.resizer.observe(this.$el);
    this.resizer.observe(this.$refs.log);
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
    pinBattleBackgroundAndMusic() {
      const scene = this.battle.scene;
      const [gen, name] = this.battleBackground.split(/-(.*)/);
      const image = BATTLE_BACKGROUND_FILES[gen](name);
      const updateGen = scene.updateGen.bind(scene);
      // The client re-rolls the battle background on every |gen|, |rated| and reset.
      scene.updateGen = () => {
        updateGen();
        scene.backdropImage = image;
        scene.$bg?.css("background-image", `url(${Dex.resourcePrefix}${image})`);
      };
      scene.updateGen();
      scene.setBgm(BATTLE_MUSIC[this.battleMusic]);
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
      // Showdown's music drowns the speech at its default volume.
      BattleSound.setBgmVolume(BGM_VOLUME);
    },
    fit() {
      const { clientWidth: width, clientHeight: height } = this.$el;
      const scale = Math.min(height / FRAME_HEIGHT, width / FIELD_WIDTH);
      const left = (width - FRAME_WIDTH * scale) / 2;
      const top = (height - FRAME_HEIGHT * scale) / 2;
      this.$refs.frame.style.transform = `translate(${left}px, ${top}px) scale(${scale})`;
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
