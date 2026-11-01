// Audio in and out.
//
// Player: plays the character's reply sentence by sentence, with no gaps, and reports
//         the volume ~60 times a second so the avatar's mouth can follow it.
// Mic:    hands-free mode listens continuously, notices when you start and stop talking
//         (voice activity detection), and hands back each turn as a WAV recording.
//         It can also record a single message on demand.

let ctx = null;

export function audioContext() {
  // Must first be created or resumed inside a click, or browsers block sound.
  if (!ctx) ctx = new (window.AudioContext || window.webkitAudioContext)();
  if (ctx.state === "suspended") ctx.resume();
  return ctx;
}

function b64ToArrayBuffer(b64) {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes.buffer;
}

export class Player {
  constructor({ onLevel, onStart, onIdle }) {
    this.onLevel = onLevel || (() => {});
    this.onStart = onStart || (() => {});
    this.onIdle = onIdle || (() => {});
    this.sources = new Set();
    this.nextTime = 0;
    this.chain = Promise.resolve();   // keeps sentences in order while they decode
    this.expectingMore = false;       // true while a reply is still streaming in
    this.generation = 0;              // bumps on stop() so late chunks are dropped
    this.loopRunning = false;
  }

  get playing() { return this.sources.size > 0; }

  _graph() {
    const c = audioContext();
    if (!this.analyser) {
      this.analyser = c.createAnalyser();
      this.analyser.fftSize = 512;
      this.analyser.connect(c.destination);
      this.buf = new Uint8Array(this.analyser.fftSize);
    }
    return c;
  }

  enqueue(b64, mime) {
    const gen = this.generation;
    this.chain = this.chain.then(async () => {
      if (gen !== this.generation) return;
      const c = this._graph();
      let buffer;
      try { buffer = await c.decodeAudioData(b64ToArrayBuffer(b64)); }
      catch (e) { console.warn("Couldn't decode audio", mime, e); return; }
      if (gen !== this.generation) return;
      const src = c.createBufferSource();
      src.buffer = buffer;
      src.connect(this.analyser);
      const at = Math.max(c.currentTime + 0.02, this.nextTime);
      src.start(at);
      this.nextTime = at + buffer.duration;
      const wasIdle = this.sources.size === 0;
      this.sources.add(src);
      src.onended = () => {
        this.sources.delete(src);
        this._maybeIdle();
      };
      if (wasIdle) this.onStart();
      this._loop();
    });
  }

  // Call when the reply has finished streaming, so we know when the last sentence ends.
  finish() {
    this.expectingMore = false;
    this.chain.then(() => this._maybeIdle());
  }

  begin() { this.expectingMore = true; }

  _maybeIdle() {
    if (this.sources.size === 0 && !this.expectingMore) {
      this.onLevel(0);
      this.onIdle();
    }
  }

  stop() {
    this.generation++;
    this.expectingMore = false;
    for (const s of this.sources) { try { s.stop(); } catch (e) { /* already stopped */ } }
    this.sources.clear();
    this.nextTime = 0;
    this.chain = Promise.resolve();
    this.onLevel(0);
    this.onIdle();
  }

  _loop() {
    if (this.loopRunning) return;
    this.loopRunning = true;
    const tick = () => {
      if (this.sources.size === 0) { this.loopRunning = false; this.onLevel(0); return; }
      this.analyser.getByteTimeDomainData(this.buf);
      let sum = 0;
      for (let i = 0; i < this.buf.length; i++) { const v = (this.buf[i] - 128) / 128; sum += v * v; }
      this.onLevel(Math.min(1, Math.sqrt(sum / this.buf.length) * 6));
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }
}

// ---------------------------------------------------------------------------
// Microphone
// ---------------------------------------------------------------------------
const TARGET_RATE = 16000;        // speech models don't need more; keeps uploads small

export class Mic {
  constructor({ onUtterance, onState, onLevel, silenceMs = 1500 }) {
    this.onUtterance = onUtterance;
    this.onState = onState || (() => {});
    this.onLevel = onLevel || (() => {});
    this.silenceMs = silenceMs;
    this.mode = "off";            // off | handsfree | manual
    this.paused = false;          // true while the character is thinking or speaking
  }

  static supported() {
    return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && (window.AudioContext || window.webkitAudioContext));
  }

  async _open() {
    if (this.stream) return;
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
    });
    const c = audioContext();
    this.rate = c.sampleRate;
    this.source = c.createMediaStreamSource(this.stream);
    // ScriptProcessor is old but works in every browser without extra files.
    this.proc = c.createScriptProcessor(2048, 1, 1);
    this.mute = c.createGain();
    this.mute.gain.value = 0;
    this.source.connect(this.proc);
    this.proc.connect(this.mute);
    this.mute.connect(c.destination);
    this.frameMs = (2048 / this.rate) * 1000;
    this._reset();
    this.noise = 0.01;
    this.proc.onaudioprocess = (e) => this._frame(e.inputBuffer.getChannelData(0));
  }

  _reset() {
    this.preroll = [];            // the last ~300 ms before speech starts, so the first word isn't clipped
    this.frames = [];
    this.speaking = false;
    this.loudFrames = 0;
    this.quietMs = 0;
    this.speechMs = 0;
  }

  async startHandsFree() {
    await this._open();
    this.mode = "handsfree";
    this.paused = false;
    this._reset();
    this.onState("listening");
  }

  async startManual() {
    await this._open();
    this.mode = "manual";
    this._reset();
    this.onState("recording");
  }

  stopManualAndSend() {
    if (this.mode !== "manual") return;
    const frames = this.frames;
    this.mode = "off";
    this._reset();
    this.onState("off");
    if (frames.length) this.onUtterance(this._wav(frames));
  }

  pause() { this.paused = true; this._reset(); }
  resume() {
    if (this.mode !== "handsfree") return;
    this.paused = false;
    this._reset();
    this.onState("listening");
  }

  stop() {
    this.mode = "off";
    this.paused = false;
    this._reset();
    this.onLevel(0);
    if (this.proc) this.proc.onaudioprocess = null;
    if (this.stream) this.stream.getTracks().forEach((t) => t.stop());
    try { this.source && this.source.disconnect(); this.proc && this.proc.disconnect(); this.mute && this.mute.disconnect(); } catch (e) { /* fine */ }
    this.stream = this.source = this.proc = this.mute = null;
    this.onState("off");
  }

  _frame(input) {
    if (this.mode === "off") return;
    const data = new Float32Array(input);   // copy: the browser reuses the buffer
    let sum = 0;
    for (let i = 0; i < data.length; i++) sum += data[i] * data[i];
    const rms = Math.sqrt(sum / data.length);
    this.onLevel(this.paused && this.mode === "handsfree" ? 0 : Math.min(1, rms * 8));

    if (this.mode === "manual") { this.frames.push(data); return; }
    if (this.paused) return;

    // Voice activity detection: compare loudness against a running estimate of background noise.
    const threshold = Math.max(0.012, this.noise * 3);
    const loud = rms > threshold;

    if (!this.speaking) {
      if (!loud) this.noise = this.noise * 0.95 + rms * 0.05;
      this.preroll.push(data);
      if (this.preroll.length > Math.ceil(300 / this.frameMs)) this.preroll.shift();
      this.loudFrames = loud ? this.loudFrames + 1 : 0;
      if (this.loudFrames >= 3) {                 // ~130 ms of sound: someone is talking
        this.speaking = true;
        this.frames = this.preroll.slice();
        this.preroll = [];
        this.speechMs = this.loudFrames * this.frameMs;
        this.quietMs = 0;
        this.onState("hearing");
      }
      return;
    }

    this.frames.push(data);
    if (loud) { this.quietMs = 0; this.speechMs += this.frameMs; }
    else this.quietMs += this.frameMs;

    const tooLong = this.frames.length * this.frameMs > 60000;
    if (this.quietMs >= this.silenceMs || tooLong) {
      const frames = this.frames;
      const enoughSpeech = this.speechMs >= 350;  // ignore coughs and clicks
      this._reset();
      if (enoughSpeech) {
        this.paused = true;                       // stop listening while the turn is handled
        this.onUtterance(this._wav(frames));
      } else {
        this.onState("listening");
      }
    }
  }

  _wav(frames) {
    // Join, downsample to 16 kHz, convert to 16-bit PCM and add a WAV header.
    const total = frames.reduce((n, f) => n + f.length, 0);
    const joined = new Float32Array(total);
    let o = 0;
    for (const f of frames) { joined.set(f, o); o += f.length; }
    const ratio = this.rate / TARGET_RATE;
    const outLen = Math.floor(joined.length / ratio);
    const pcm = new Int16Array(outLen);
    for (let i = 0; i < outLen; i++) {
      // average the samples that fall into this output sample (simple low-pass)
      const start = Math.floor(i * ratio), end = Math.min(joined.length, Math.floor((i + 1) * ratio));
      let acc = 0;
      for (let j = start; j < end; j++) acc += joined[j];
      const v = Math.max(-1, Math.min(1, acc / Math.max(1, end - start)));
      pcm[i] = v < 0 ? v * 0x8000 : v * 0x7fff;
    }
    const buffer = new ArrayBuffer(44 + pcm.length * 2);
    const view = new DataView(buffer);
    const str = (off, s) => { for (let i = 0; i < s.length; i++) view.setUint8(off + i, s.charCodeAt(i)); };
    str(0, "RIFF"); view.setUint32(4, 36 + pcm.length * 2, true); str(8, "WAVE");
    str(12, "fmt "); view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
    view.setUint32(24, TARGET_RATE, true); view.setUint32(28, TARGET_RATE * 2, true);
    view.setUint16(32, 2, true); view.setUint16(34, 16, true);
    str(36, "data"); view.setUint32(40, pcm.length * 2, true);
    new Int16Array(buffer, 44).set(pcm);
    return new Blob([buffer], { type: "audio/wav" });
  }
}
