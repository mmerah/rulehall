// Voice playback of finished lines and the microphone for the composer.
const AUTO_READ_KEY = "rulehall.auto-read";
const RECORDING_TYPES = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/mp4"];
const RECORDING_LIMIT_MS = 60000;
// 60 s at this rate stays under the socket's 1 MB message cap once base64 encoded.
const RECORDING_BITS_PER_SECOND = 32000;
const SILENCE = "data:audio/wav;base64,UklGRiUAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQEAAACA";
const READ_ALOUD = "Read aloud";
const STOP_READING = "Stop reading";

export default {
  template: "<div></div>",
  mounted() {
    this.clips = [];
    this.current = null;
    this.waitingId = null;
    this.offScreen = false;
    this.audio = new Audio();
    this.audio.addEventListener("ended", () => {
      if (this.current) this.next();
    });
    this.watcher = new IntersectionObserver((entries) => {
      this.offScreen = !entries[entries.length - 1].isIntersecting;
      this.emitSpeaking();
    });
    this.onEscape = (event) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      if (document.querySelector(".q-dialog, .q-menu")) return;
      this.$emit("escaped");
    };
    // iOS plays a socket-driven clip only on an element a gesture has played once.
    this.prime = () => {
      document.removeEventListener("pointerdown", this.prime, true);
      document.removeEventListener("keydown", this.prime, true);
      if (this.current) return;
      this.audio.src = SILENCE;
      this.audio
        .play()
        .then(() => {
          if (!this.current) this.audio.pause();
        })
        .catch(() => {});
    };
    document.addEventListener("keydown", this.onEscape);
    document.addEventListener("pointerdown", this.prime, true);
    document.addEventListener("keydown", this.prime, true);
    this.recorder = null;
    this.starting = false;
    this.$emit("auto_read", this.autoReadOn());
    this.$emit(
      "microphone",
      window.isSecureContext &&
        !!navigator.mediaDevices?.getUserMedia &&
        typeof MediaRecorder !== "undefined",
    );
  },
  unmounted() {
    document.removeEventListener("keydown", this.onEscape);
    document.removeEventListener("pointerdown", this.prime, true);
    document.removeEventListener("keydown", this.prime, true);
    this.watcher.disconnect();
    this.audio.pause();
  },
  methods: {
    play(url, id) {
      if (!this.autoReadOn()) return;
      this.enqueue({ url, id });
    },
    replay(url, id) {
      this.stop();
      this.enqueue({ url, id });
    },
    wait(id) {
      this.mark(this.waitingId, null);
      this.waitingId = id;
      this.mark(id, "waiting");
    },
    enqueue(clip) {
      this.clips.push(clip);
      if (!this.current) this.next();
    },
    next() {
      if (this.current) this.mark(this.current.id, null);
      const clip = this.clips.shift() ?? null;
      this.current = clip;
      if (clip && clip.id === this.waitingId) this.waitingId = null;
      this.watcher.disconnect();
      this.offScreen = false;
      if (clip) {
        this.mark(clip.id, "speaking");
        const bubble = document.getElementById(`c${clip.id}`);
        if (bubble) this.watcher.observe(bubble);
        this.audio.src = clip.url;
        // A blocked or broken clip is skipped; a failed decode leaves `paused` false, so pause.
        this.audio.play().catch(() => {
          if (this.current !== clip) return;
          this.audio.pause();
          this.next();
        });
      }
      this.emitSpeaking();
    },
    stop() {
      this.clips = [];
      this.audio.pause();
      if (this.current) this.mark(this.current.id, null);
      this.current = null;
      this.mark(this.waitingId, null);
      this.waitingId = null;
      this.watcher.disconnect();
      this.offScreen = false;
      this.emitSpeaking();
    },
    reveal() {
      if (!this.current) return;
      document.getElementById(`c${this.current.id}`)?.scrollIntoView({ block: "center" });
    },
    mark(id, state) {
      const bubble = id === null ? null : document.getElementById(`c${id}`);
      if (!bubble) return;
      const button = bubble.querySelector(".game-read-aloud");
      if (state === null) delete bubble.dataset.voice;
      else bubble.dataset.voice = state;
      if (state === "speaking") bubble.setAttribute("aria-current", "true");
      else bubble.removeAttribute("aria-current");
      button?.setAttribute("aria-label", state === "speaking" ? STOP_READING : READ_ALOUD);
    },
    emitSpeaking() {
      this.$emit("speaking", { bubble_id: this.current?.id ?? null, off_screen: this.offScreen });
    },
    toggleAutoRead() {
      const on = !this.autoReadOn();
      localStorage.setItem(AUTO_READ_KEY, on ? "on" : "off");
      if (!on) this.stop();
      this.$emit("auto_read", on);
    },
    autoReadOn() {
      return localStorage.getItem(AUTO_READ_KEY) === "on";
    },
    async toggleRecording() {
      if (this.starting) return;
      if (this.recorder) {
        this.recorder.stop();
        return;
      }
      this.starting = true;
      let stream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      } catch {
        this.$emit("denied");
        return;
      } finally {
        this.starting = false;
      }
      const mimeType = RECORDING_TYPES.find((type) => MediaRecorder.isTypeSupported(type));
      const recorder = new MediaRecorder(stream, {
        mimeType,
        audioBitsPerSecond: RECORDING_BITS_PER_SECOND,
      });
      const chunks = [];
      const limit = setTimeout(() => recorder.stop(), RECORDING_LIMIT_MS);
      recorder.ondataavailable = (event) => chunks.push(event.data);
      recorder.onstop = () => {
        clearTimeout(limit);
        stream.getTracks().forEach((track) => track.stop());
        this.recorder = null;
        this.$emit("recording", false);
        const blob = new Blob(chunks, { type: recorder.mimeType });
        const reader = new FileReader();
        reader.onload = () =>
          this.$emit("recorded", { audio: reader.result.split(",", 2)[1], mime: blob.type });
        reader.readAsDataURL(blob);
      };
      this.recorder = recorder;
      recorder.start();
      this.$emit("recording", true);
    },
  },
};
