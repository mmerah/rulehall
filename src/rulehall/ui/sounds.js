// One click when dice land on the card.
const SOUND_KEY = "rulehall.dice.sound";
const SOUND_EVENT = "rulehall-sound";

export default {
  template: "<div></div>",
  props: { base: String },
  mounted() {
    this.roll = new Audio(`${this.base}roll.wav`);
    this.$emit("sound", this.soundOn());
  },
  methods: {
    play() {
      requestAnimationFrame(() => setTimeout(() => this.hit(), this.reeling()));
    },
    // A sound belongs on the face the reel settles on, not on the first frame of the spin.
    reeling() {
      const reel = document.querySelector(".game-die-live .game-die-value");
      const spin = reel ? getComputedStyle(reel) : null;
      return spin
        ? (parseFloat(spin.animationDuration) + parseFloat(spin.animationDelay)) * 1000
        : 0;
    },
    hit() {
      if (!this.soundOn()) return;
      this.roll.currentTime = 0;
      // Autoplay policy before the first gesture is not an error the player reads.
      this.roll.play().catch(() => {});
    },
    toggleSound() {
      const on = !this.soundOn();
      localStorage.setItem(SOUND_KEY, on ? "on" : "off");
      window.dispatchEvent(new CustomEvent(SOUND_EVENT, { detail: on }));
      this.$emit("sound", on);
    },
    soundOn() {
      return localStorage.getItem(SOUND_KEY) !== "off";
    },
  },
};
