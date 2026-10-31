// Practice Room: page logic.
// Views: scenario library, practice (voice or text), feedback, scenario builder, insights.
// All text from users or the AI is inserted with textContent, never as HTML.

import { Avatar, avatarThumb } from "./avatar.js";
import { Player, Mic, audioContext } from "./audio.js";

const main = document.getElementById("main");
const state = { lang: "en", strings: {}, scenarios: [], cleanup: null, flash: null };

// ---------------------------------------------------------------------------
// Language
// ---------------------------------------------------------------------------
function savedLang() {
  try { return localStorage.getItem("lang") || "en"; } catch (e) { return "en"; }
}
async function setLang(lang) {
  state.lang = lang === "ar" ? "ar" : "en";
  try { localStorage.setItem("lang", state.lang); } catch (e) { /* private mode: fine */ }
  state.strings = await (await fetch(`/static/i18n/${state.lang}.json`)).json();
  document.documentElement.lang = state.lang;
  document.documentElement.dir = state.lang === "ar" ? "rtl" : "ltr";
  document.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
  document.querySelectorAll("[data-i18n-aria]").forEach((el) => el.setAttribute("aria-label", t(el.dataset.i18nAria)));
  document.getElementById("lang-select").value = state.lang;
}
function t(key, vars = {}) {
  let s = state.strings[key] ?? key;
  for (const [k, v] of Object.entries(vars)) s = s.split(`{${k}}`).join(v);
  return s;
}
function num(n, digits = 0) {
  return new Intl.NumberFormat(state.lang === "ar" ? "ar-u-nu-latn" : "en-GB",
    { maximumFractionDigits: digits, minimumFractionDigits: 0 }).format(n);
}

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------
function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "text") el.textContent = v;
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}
function svgEl(markup) {           // only ever used with our own SVG strings, never user text
  const tpl = document.createElement("template");
  tpl.innerHTML = markup.trim();
  return tpl.content.firstElementChild;
}
const ICONS = {
  mic: '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill="currentColor" d="M12 15a3 3 0 0 0 3-3V6a3 3 0 1 0-6 0v6a3 3 0 0 0 3 3Zm5-3a1 1 0 1 1 2 0 7 7 0 0 1-6 6.92V21h3a1 1 0 1 1 0 2H8a1 1 0 1 1 0-2h3v-2.08A7 7 0 0 1 5 12a1 1 0 1 1 2 0 5 5 0 0 0 10 0Z"/></svg>',
  rec: '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="7" fill="currentColor"/></svg>',
  stop: '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor"/></svg>',
  send: '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill="currentColor" d="M3.4 20.4 21 12 3.4 3.6 3.4 10l12.6 2-12.6 2z"/></svg>',
  back: '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill="currentColor" d="M15.4 5.4 14 4l-8 8 8 8 1.4-1.4L8.8 12z"/></svg>',
};
const icon = (name) => svgEl(ICONS[name]);

function announce(msg) {
  const el = document.getElementById("announce");
  el.textContent = "";
  setTimeout(() => { el.textContent = msg; }, 50);
}
function alertMsg(msg) {
  const el = document.getElementById("announce-alert");
  el.textContent = "";
  setTimeout(() => { el.textContent = msg; }, 50);
}
function fill(el, ...children) {   // replaceChildren, but skips empty slots instead of printing "null"
  el.replaceChildren(...children.flat().filter((c) => c !== null && c !== undefined && c !== false));
}
function notice(container, kind, msg) {
  container.replaceChildren(h("div", { class: `notice notice-${kind}` }, msg));
}
async function api(path, opts = {}) {
  const res = await fetch(path, {
    ...opts,
    headers: opts.body && !(opts.body instanceof FormData) ? { "Content-Type": "application/json" } : undefined,
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw { status: res.status, detail: body.detail };
  return body;
}
function errorText(err) {
  const key = typeof err?.detail === "string" ? err.detail : "model_error";
  return state.strings[key] ? t(key, { n: 1000 }) : t("model_error");
}
function setTitle(text) {
  document.title = `${text} · ${t("app_name")}`;
}
function focusHeading() {
  const h1 = main.querySelector("h1");
  if (h1) { h1.setAttribute("tabindex", "-1"); h1.focus({ preventScroll: false }); }
}

// ---------------------------------------------------------------------------
// Router
// ---------------------------------------------------------------------------
async function route() {
  if (location.hash && !location.hash.startsWith("#/")) return;   // in-page links aren't pages
  if (state.cleanup) { state.cleanup(); state.cleanup = null; }
  const [, view = "library", id] = (location.hash || "#/library").split("/");
  document.querySelectorAll(".site-nav a").forEach((a) => {
    if (a.dataset.route === view) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
  main.replaceChildren(h("p", { text: t("loading") }));
  try {
    if (view === "practice" && id) await renderPractice(decodeURIComponent(id));
    else if (view === "create") await renderBuilder("create");
    else if (view === "edit" && id) await renderBuilder("edit", decodeURIComponent(id));
    else if (view === "duplicate" && id) await renderBuilder("duplicate", decodeURIComponent(id));
    else if (view === "insights") await renderInsights();
    else await renderLibrary();
  } catch (err) {
    main.replaceChildren(h("h1", { text: t("app_name") }), h("div", { class: "notice notice-error", role: "alert" }, errorText(err)));
  }
  // Move focus to the new page's heading on navigation, but not on first load,
  // so keyboard users still meet the "skip to main content" link first.
  if (state.loaded) focusHeading();
  state.loaded = true;
}

// ---------------------------------------------------------------------------
// Library
// ---------------------------------------------------------------------------
async function renderLibrary() {
  state.scenarios = await api(`/api/scenarios?lang=${state.lang}`);
  setTitle(t("library_title"));
  const flash = h("div");
  if (state.flash) { notice(flash, "ok", state.flash); announce(state.flash); state.flash = null; }

  const categories = [...new Set(state.scenarios.map((s) => s.category))];
  const select = h("select", { id: "cat-filter" },
    h("option", { value: "", text: t("filter_all") }),
    categories.map((c) => h("option", { value: c, text: t(`cat_${c}`) })));
  const list = h("ul", { class: "scenario-grid" });

  const draw = () => {
    const shown = state.scenarios.filter((s) => !select.value || s.category === select.value);
    list.replaceChildren(...shown.map(card));
    if (!shown.length) list.replaceChildren(h("li", { text: t("no_scenarios") }));
  };
  select.addEventListener("change", draw);

  main.replaceChildren(
    h("div", { class: "view-head" }, h("h1", { text: t("library_title") }), h("p", { text: t("library_intro") })),
    flash,
    h("div", { class: "filters" }, h("div", { class: "field" }, h("label", { for: "cat-filter", text: t("filter_category") }), select)),
    list,
  );
  draw();
}

function card(s) {
  const thumb = h("div", { class: "thumb", "aria-hidden": "true" });
  thumb.append(svgEl(avatarThumb(s.character.look)));
  const actions = h("div", { class: "btn-row" },
    h("button", { class: "btn btn-primary", type: "button", "aria-label": t("start_label", { title: s.title }),
      onclick: () => { audioContext(); location.hash = `#/practice/${encodeURIComponent(s.id)}`; } }, t("start")));
  if (s.preset) {
    actions.append(h("a", { class: "btn btn-small", href: `#/duplicate/${encodeURIComponent(s.id)}`,
      "aria-label": t("duplicate_label", { title: s.title }) }, t("duplicate")));
  } else {
    actions.append(
      h("a", { class: "btn btn-small", href: `#/edit/${encodeURIComponent(s.id)}`, "aria-label": t("edit_label", { title: s.title }) }, t("edit")),
      h("button", { class: "btn btn-small btn-danger", type: "button", "aria-label": t("delete_label", { title: s.title }),
        onclick: async () => {
          if (!confirm(t("confirm_delete", { title: s.title }))) return;
          await api(`/api/scenarios/${encodeURIComponent(s.id)}`, { method: "DELETE" });
          state.flash = t("deleted");
          await renderLibrary();
          focusHeading();
        } }, t("delete")));
  }
  return h("li", {},
    h("article", { class: "card scenario-card" },
      h("div", { class: "scenario-top" }, thumb,
        h("div", {}, h("h2", { text: s.title }), h("p", { class: "who", text: `${s.character.name} · ${s.character.role}` }))),
      h("p", { class: "summary", text: s.summary }),
      h("ul", { class: "tags" },
        h("li", { class: "tag", text: s.preset ? t("built_in") : t("custom") }),
        h("li", { class: "tag", text: t(`cat_${s.category}`) }),
        h("li", { class: `tag tag-${s.difficulty}` }, h("span", { class: "visually-hidden" }, `${t("difficulty")}: `), t(`difficulty_${s.difficulty}`))),
      actions));
}

// ---------------------------------------------------------------------------
// Practice
// ---------------------------------------------------------------------------
async function renderPractice(scenarioId) {
  const start = await api("/api/sessions", { method: "POST", body: JSON.stringify({ scenario_id: scenarioId, lang: state.lang }) });
  const sid = start.session_id;
  const sc = start.scenario;
  const name = sc.character.name;
  setTitle(sc.title);

  const S = { busy: false, voiceOut: true, handsFree: false, manual: false, muteReply: false, gotAudio: false, ended: false };

  // --- character stage ---
  const avatarBox = h("div", { role: "img" });
  const avatar = new Avatar(avatarBox, sc.character.look);
  const moodEl = h("span", { class: "mood", "data-mood": "neutral", text: t("mood_neutral") });
  const statusText = h("span", { text: t("status_idle") });
  const levelFill = h("span");
  const level = h("span", { class: "level", "aria-hidden": "true", hidden: true }, levelFill);
  const setAvatarLabel = (mood) => avatarBox.setAttribute("aria-label", t("avatar_label", { name, mood: t(`mood_${mood}`) }));
  setAvatarLabel("neutral");

  const setMood = (mood) => {
    avatar.setMood(mood);
    moodEl.dataset.mood = mood;
    moodEl.textContent = t(`mood_${mood}`);
    setAvatarLabel(mood);
  };
  const setStatus = (key, speak = false) => {
    statusText.textContent = t(key, { name });
    if (speak) announce(statusText.textContent);
  };

  // --- voice controls ---
  const handsBtn = h("button", { class: "btn btn-big btn-mic", type: "button", "aria-pressed": "false", "aria-describedby": "hands-help" },
    icon("mic"), h("span", { text: t("handsfree_on") }));
  const recBtn = h("button", { class: "btn btn-rec", type: "button", "aria-pressed": "false" }, icon("rec"), h("span", { text: t("record_one") }));
  const stopBtn = h("button", { class: "btn", type: "button", disabled: true, "aria-describedby": "stop-help" }, icon("stop"), h("span", { text: t("stop_speaking") }));
  const voiceSwitch = h("button", { type: "button", role: "switch", "aria-checked": "true", "aria-labelledby": "voice-out-label" });
  const turnsEl = h("span", { text: t("turns_left", { n: start.turns_left }) });
  const costEl = h("span", { text: t("session_cost", { cost: "0.0000" }) });

  // --- conversation ---
  const log = h("ol", { class: "log" });
  // role="log" marks it as a conversation; aria-live is off because each finished reply
  // is announced once through the status region, instead of word by word as it streams.
  const logWrap = h("div", { class: "log-wrap", tabindex: "0", role: "log", "aria-live": "off", "aria-labelledby": "convo-h" }, log);
  const practiceNotice = h("div");
  const textarea = h("textarea", { id: "msg", rows: "2", maxlength: "1000", "aria-describedby": "msg-hint", autocomplete: "off" });
  const sendBtn = h("button", { class: "btn btn-primary", type: "submit" }, icon("send"), h("span", { text: t("send") }));
  const form = h("form", { class: "card composer", novalidate: true },
    h("div", { class: "field" },
      h("label", { for: "msg", text: t("message_label") }),
      h("p", { id: "msg-hint", class: "hint", text: t("message_hint") }),
      textarea),
    sendBtn);
  const endBtn = h("button", { class: "btn", type: "button", disabled: true }, t("end"));
  const feedbackArea = h("section", { class: "feedback", "aria-live": "off" });
  const voiceCard = h("section", { class: "card voice-card", "aria-labelledby": "voice-h" },
    h("h2", { id: "voice-h", text: t("voice_controls") }),
    handsBtn,
    h("p", { id: "hands-help", class: "hint", text: t("handsfree_help", { name }) }),
    h("div", { class: "btn-row" }, recBtn, stopBtn),
    h("p", { id: "stop-help", class: "hint", text: t("stop_speaking_help") }),
    h("div", { class: "toggle-row" },
      h("span", { id: "voice-out-label", class: "label", text: t("voice_out") }),
      h("span", { class: "switch" }, voiceSwitch)));

  main.replaceChildren(
    h("div", { class: "view-head" },
      h("a", { href: "#/library", class: "btn btn-small" }, icon("back"), t("back_to_library")),
      h("h1", { text: sc.title, style: "margin-top:.75rem" })),
    h("div", { class: "practice" },
      h("aside", { class: "stage", "aria-label": name },
        h("div", { class: "card stage-card" },
          avatarBox,
          h("p", { class: "char-name", text: name }),
          h("p", { class: "char-role", text: sc.character.role }),
          h("p", { style: "margin:0" }, h("span", { class: "visually-hidden" }, `${t("mood")}: `), moodEl),
          h("div", { class: "status-line" }, statusText, level)),
        voiceCard,
        h("div", { class: "side-meta" }, turnsEl, costEl)),
      h("div", { class: "convo" },
        h("details", { class: "card brief", open: true }, h("summary", { text: t("your_brief") }), h("p", { text: sc.brief })),
        h("div", { class: "card" }, h("h2", { id: "convo-h", text: t("conversation") }), logWrap),
        practiceNotice,
        form,
        h("div", { class: "end-row" }, endBtn))),
    feedbackArea);

  const addMsg = (who, text, opts = {}) => {
    const li = h("li", { class: `msg ${who === "user" ? "msg-user" : "msg-char"}` },
      h("div", { class: "who" }, who === "user" ? t("you") : name,
        opts.spoken ? h("span", { class: "tag" }, t("spoken")) : null),
      h("div", { class: "text", dir: "auto", text }));
    log.append(li);
    logWrap.scrollTop = logWrap.scrollHeight;
    return li.querySelector(".text");
  };
  const addNote = (text) => { log.append(h("li", { class: "msg msg-note", text })); logWrap.scrollTop = logWrap.scrollHeight; };

  // --- audio out ---
  const player = new Player({
    onLevel: (v) => { if (avatar) avatar.setMouth(v); },
    onStart: () => { avatar.setState("speaking"); setStatus("status_speaking"); stopBtn.disabled = false; },
    onIdle: () => afterReply(),
  });

  function afterReply() {
    if (S.busy) return;          // still streaming: the end of this reply hasn't arrived yet
    stopBtn.disabled = true;
    if (S.ended) return;
    if (S.handsFree) { mic.resume(); }
    else { avatar.setState("idle"); setStatus("status_idle"); }
  }

  // --- audio in ---
  const mic = new Mic({
    onUtterance: (blob) => sendTurn({ audio: blob }),
    onLevel: (v) => { levelFill.style.width = `${Math.round(v * 100)}%`; },
    onState: (s) => {
      level.hidden = s === "off";
      if (s === "listening") { avatar.setState("listening"); setStatus("status_listening", true); }
      else if (s === "hearing") setStatus("status_hearing");
      else if (s === "recording") { avatar.setState("listening"); setStatus("status_recording", true); }
    },
  });

  async function micError(err) {
    const key = err && err.name === "NotAllowedError" ? "mic_denied" : "mic_unsupported";
    notice(practiceNotice, "error", t(key));
    alertMsg(t(key));
    setHandsFree(false);
  }

  async function setHandsFree(on) {
    S.handsFree = on;
    handsBtn.setAttribute("aria-pressed", String(on));
    handsBtn.querySelector("span").textContent = on ? t("handsfree_off") : t("handsfree_on");
    recBtn.disabled = on;
    if (on) {
      audioContext();
      if (!Mic.supported()) return micError();
      try { await mic.startHandsFree(); } catch (e) { return micError(e); }
      if (S.busy || player.playing) mic.pause();
    } else {
      mic.stop();
      if (!S.busy && !player.playing) { avatar.setState("idle"); setStatus("status_idle"); }
    }
  }
  handsBtn.addEventListener("click", () => setHandsFree(!S.handsFree));

  recBtn.addEventListener("click", async () => {
    if (S.manual) {
      S.manual = false;
      recBtn.setAttribute("aria-pressed", "false");
      recBtn.querySelector("span").textContent = t("record_one");
      handsBtn.disabled = false;
      mic.stopManualAndSend();
      return;
    }
    audioContext();
    if (!Mic.supported()) return micError();
    player.stop();
    try { await mic.startManual(); } catch (e) { return micError(e); }
    S.manual = true;
    recBtn.setAttribute("aria-pressed", "true");
    recBtn.querySelector("span").textContent = t("record_stop");
    handsBtn.disabled = true;
  });

  const stopSpeaking = () => {
    if (!player.playing && !S.busy) return;
    S.muteReply = true;
    player.stop();
  };
  stopBtn.addEventListener("click", stopSpeaking);
  const onKey = (e) => { if (e.key === "Escape") stopSpeaking(); };
  document.addEventListener("keydown", onKey);

  voiceSwitch.addEventListener("click", () => {
    S.voiceOut = voiceSwitch.getAttribute("aria-checked") !== "true";
    voiceSwitch.setAttribute("aria-checked", String(S.voiceOut));
    if (!S.voiceOut) stopSpeaking();
  });

  // --- sending a turn and reading the streamed reply ---
  async function sendTurn({ text, audio }) {
    if (S.busy || S.ended) return;
    S.busy = true;
    S.muteReply = false;
    S.gotAudio = false;
    player.stop();
    mic.pause();
    sendBtn.disabled = true;
    practiceNotice.replaceChildren();
    if (text) addMsg("user", text);
    avatar.setState("thinking");
    setStatus("status_thinking", true);

    const fd = new FormData();
    if (text) fd.append("text", text);
    if (audio) fd.append("audio", audio, "turn.wav");
    fd.append("voice_on", String(S.voiceOut));

    let bubble = null, restore = text || "", failed = false;
    try {
      const res = await fetch(`/api/sessions/${sid}/turn`, { method: "POST", body: fd });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw { status: res.status, detail: body.detail };
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let nl;
        while ((nl = buf.indexOf("\n")) >= 0) {
          const line = buf.slice(0, nl).trim();
          buf = buf.slice(nl + 1);
          if (!line) continue;
          const ev = JSON.parse(line);
          if (ev.type === "heard") {
            if (ev.text) addMsg("user", ev.text, { spoken: true });
            else { addNote(t("couldnt_hear")); announce(t("couldnt_hear")); }
          } else if (ev.type === "start") {
            setMood(ev.mood);
            bubble = addMsg("char", "");
            if (S.voiceOut) player.begin();
          } else if (ev.type === "delta") {
            if (bubble) { bubble.textContent += ev.text; logWrap.scrollTop = logWrap.scrollHeight; }
          } else if (ev.type === "audio") {
            if (S.voiceOut && !S.muteReply) { S.gotAudio = true; player.enqueue(ev.data, ev.mime); }
          } else if (ev.type === "voice_unavailable") {
            notice(practiceNotice, "info", t("voice_unavailable"));
          } else if (ev.type === "done") {
            if (bubble) bubble.textContent = ev.text;
            turnsEl.textContent = t("turns_left", { n: ev.turns_left });
            costEl.textContent = t("session_cost", { cost: ev.cost.toFixed(4) });
            announce(t("said", { name, text: ev.text }));
            endBtn.disabled = false;
          } else if (ev.type === "error") {
            failed = true;
            restore = ev.restore || restore;
            throw { detail: ev.key };
          }
        }
      }
    } catch (err) {
      failed = true;
      notice(practiceNotice, "error", errorText(err));
      alertMsg(errorText(err));
      if (restore && !textarea.value) textarea.value = restore;
      if (err?.detail === "session_expired" || err?.detail === "turn_limit") {
        form.hidden = true; voiceCard.hidden = true; mic.stop();
      }
    } finally {
      S.busy = false;
      sendBtn.disabled = false;
      if (failed || !S.gotAudio) { player.stop(); }   // nothing to play: go straight to the next turn
      else player.finish();
    }
  }

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = textarea.value.trim();
    if (!text) { textarea.focus(); return; }
    textarea.value = "";
    sendTurn({ text });
  });
  textarea.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); form.requestSubmit(); }
  });

  // --- ending and feedback ---
  endBtn.addEventListener("click", async () => {
    S.ended = true;
    mic.stop();
    player.stop();
    endBtn.disabled = true;
    form.hidden = true;
    voiceCard.hidden = true;
    avatar.setState("thinking");
    setStatus("ending", true);
    try {
      const fb = await api(`/api/sessions/${sid}/end`, { method: "POST" });
      avatar.setState("idle");
      setStatus("status_idle");
      renderFeedback(feedbackArea, fb, scenarioId);
    } catch (err) {
      S.ended = false;
      form.hidden = false; voiceCard.hidden = false; endBtn.disabled = false;
      notice(practiceNotice, "error", errorText(err));
      alertMsg(errorText(err));
    }
  });

  // --- the opening line ---
  addMsg("char", sc.opening);
  const ctx = audioContext();
  if (ctx.state === "running") {
    api(`/api/sessions/${sid}/opening-audio`).then((r) => {
      if (r.audio && S.voiceOut && !S.busy && !S.ended) { player.begin(); player.enqueue(r.audio, r.mime); player.finish(); }
    }).catch(() => {});
  }

  state.cleanup = () => { mic.stop(); player.stop(); document.removeEventListener("keydown", onKey); };
}

function renderFeedback(area, fb, scenarioId) {
  const n = fb.numbers;
  const stats = h("dl", { class: "stat-grid" },
    h("div", { class: "stat" }, h("dt", { text: t("overall_score") }), h("dd", { text: t("out_of_10", { n: fb.overall_score ?? "–" }) })));
  if (n) {
    stats.append(h("div", { class: "stat" }, h("dt", { text: t("final_value", { label: n.label }) }), h("dd", { text: `${num(n.value, 2)} ${n.unit}` })));
    if (n.total) stats.append(h("div", { class: "stat" }, h("dt", { text: t("total_value", { multiplier_label: n.multiplier_label }) }), h("dd", { text: num(n.total) })));
    if (n.vs_target !== undefined) {
      const good = n.vs_target >= 0;
      stats.append(h("div", { class: "stat" }, h("dt", { text: t("vs_target") }),
        h("dd", { class: good ? "good" : "bad", text: t(good ? "better_than_target" : "worse_than_target", { amount: num(Math.abs(n.vs_target)) }) })));
    }
    stats.append(h("div", { class: "stat" }, h("dt", { text: t("left_on_table") }),
      h("dd", {}, num(n.left_on_table), h("small", { class: "hint", text: t("left_on_table_help") }))));
  }

  const rows = (fb.criteria || []).map((c) => {
    const score = Math.max(0, Math.min(5, Number(c.score) || 0));
    return h("tr", {},
      h("th", { scope: "row", text: c.name }),
      h("td", {}, h("span", { class: "dots", "aria-hidden": "true", text: "●".repeat(score) + "○".repeat(5 - score) }), " ", t("out_of_5", { n: score })),
      h("td", { text: c.comment || "" }));
  });

  const list = (title, items) => items && items.length
    ? h("div", { class: "card" }, h("h3", { text: title }), h("ul", {}, items.map((x) => h("li", { text: x })))) : null;

  fill(area,
    h("h2", { id: "fb-h", tabindex: "-1", text: t("feedback_title"), style: "font-size:1.5rem" }),
    stats,
    !n && fb.outcome ? h("p", {}, h("strong", { text: `${t("outcome")}: ` }), fb.outcome.reached ? (fb.outcome.description || "") : t("outcome_none")) : null,
    fb.summary ? h("p", { text: fb.summary }) : null,
    rows.length ? h("div", { class: "table-wrap" }, h("table", {},
      h("caption", { class: "visually-hidden", text: t("criteria") }),
      h("thead", {}, h("tr", {}, h("th", { scope: "col", text: t("criterion") }), h("th", { scope: "col", text: t("score") }), h("th", { scope: "col", text: t("comment") }))),
      h("tbody", {}, rows))) : null,
    h("div", { class: "two-col" }, list(t("strengths"), fb.strengths), list(t("improvements"), fb.improvements)),
    fb.missed_opportunity ? h("div", { class: "card" }, h("h3", { text: t("missed") }), h("p", { text: fb.missed_opportunity })) : null,
    fb.reveal ? h("details", { class: "card brief" }, h("summary", { text: t("reveal") }), h("p", { text: fb.reveal })) : null,
    h("div", { class: "btn-row" },
      h("button", { class: "btn btn-primary", type: "button", onclick: () => { audioContext(); route(); } }, t("try_again")),
      h("a", { class: "btn", href: "#/library" }, t("back_to_library"))));
  area.querySelector("#fb-h").focus();
  announce(t("feedback_title"));
}

// ---------------------------------------------------------------------------
// Scenario builder
// ---------------------------------------------------------------------------
const pickText = (v) => (v && typeof v === "object" ? (v[state.lang] || v.en || Object.values(v)[0] || "") : (v || ""));

const FIELD_FOR_SERVER = {
  title: "f-title", summary: "f-summary", category: "f-category", difficulty: "f-difficulty-easy", brief: "f-brief",
  goal: "f-goal", "character.name": "f-name", "character.role": "f-role", "character.look": "f-look-0",
  opening: "f-opening", persona: "f-persona", private_info: "f-private", rubric: "f-rubric", reveal: "f-reveal",
  "offer.label": "f-offer-label", "offer.unit": "f-offer-unit", "offer.start": "f-offer-start",
  "offer.limit": "f-offer-limit", "offer.max_step": "f-offer-step", "offer.target": "f-offer-target",
  "offer.multiplier": "f-offer-mult", "offer.multiplier_label": "f-offer-mult-label",
};

async function renderBuilder(mode, id) {
  const cfg = await api("/api/config");
  let src = null;
  if (mode !== "create") src = await api(`/api/scenarios/${encodeURIComponent(id)}/source`);
  const editing = mode === "edit";
  setTitle(editing ? t("builder_title_edit") : t("builder_title_new"));

  const fieldsets = [];
  const textField = (fid, labelKey, { hintKey, required, multiline, rows, value, type = "text", maxlength } = {}) => {
    const describedBy = hintKey ? `${fid}-hint` : null;
    const input = multiline
      ? h("textarea", { id: fid, rows: rows || 3, "aria-describedby": describedBy, required, maxlength })
      : h("input", { id: fid, type, "aria-describedby": describedBy, required, maxlength, step: type === "number" ? "any" : null, inputmode: type === "number" ? "decimal" : null });
    input.value = value ?? "";
    return h("div", { class: "field" },
      h("label", { for: fid }, t(labelKey), required ? h("span", { class: "req" }, ` (${t("required")})`) : null),
      hintKey ? h("p", { id: `${fid}-hint`, class: "hint", text: t(hintKey) }) : null,
      input);
  };

  const v = (path, fallback = "") => {
    if (!src) return fallback;
    const parts = path.split(".");
    let cur = src;
    for (const p of parts) cur = cur ? cur[p] : undefined;
    return cur === undefined || cur === null ? fallback : pickText(cur);
  };

  const errorSummary = h("div", { tabindex: "-1" });
  const draftStatus = h("div", { "aria-live": "polite" });
  const draftInput = h("textarea", { id: "draft-desc", rows: "2", "aria-describedby": "draft-hint", maxlength: "2000" });
  const draftBtn = h("button", { class: "btn", type: "button" }, t("draft_button"));

  const category = h("select", { id: "f-category" }, cfg.categories.map((c) => h("option", { value: c, text: t(`cat_${c}`) })));
  category.value = src?.category || "other";

  const diff = src?.difficulty || "medium";
  const diffGroup = h("fieldset", { class: "field", style: "border:0;padding:0;margin:0 0 1.1rem;background:none" },
    h("legend", { class: "label", style: "padding:0;font-size:1rem" }, t("f_difficulty")),
    h("div", { class: "radio-row" }, ["easy", "medium", "hard"].map((d) =>
      h("label", { class: "radio-pill" },
        h("input", { type: "radio", name: "difficulty", value: d, id: `f-difficulty-${d}`, checked: d === diff }),
        h("span", { text: t(`difficulty_${d}`) })))));

  const look = src?.character?.look || "man-clean";
  const lookGroup = h("fieldset", { class: "field", style: "border:0;padding:0;margin:0 0 1.1rem;background:none" },
    h("legend", { class: "label", style: "padding:0;font-size:1rem" }, t("f_look")),
    h("div", { class: "look-grid" }, cfg.looks.map((l, i) => {
      const card = h("span", { class: "look-card" });
      card.append(svgEl(avatarThumb(l)), h("span", { text: t(`look_${l}`) }));
      return h("label", { class: "look-option" },
        h("input", { type: "radio", name: "look", value: l, id: `f-look-${i}`, checked: l === look, "aria-label": t(`look_${l}`) }),
        card);
    })));

  const offerOn = h("input", { type: "checkbox", id: "f-offer-on", checked: !!src?.offer, "aria-describedby": "f-offer-help", "aria-controls": "offer-fields" });
  const dirSelect = h("select", { id: "f-offer-direction" },
    h("option", { value: "down", text: t("f_offer_down") }), h("option", { value: "up", text: t("f_offer_up") }));
  dirSelect.value = src?.offer?.direction || "down";
  const offerFields = h("div", { id: "offer-fields", hidden: !src?.offer },
    h("div", { class: "grid-2" },
      textField("f-offer-label", "f_offer_label", { hintKey: "f_offer_label_hint", required: true, value: src?.offer?.label, maxlength: 60 }),
      textField("f-offer-unit", "f_offer_unit", { hintKey: "f_offer_unit_hint", required: true, value: src?.offer?.unit, maxlength: 20 }),
      textField("f-offer-start", "f_offer_start", { type: "number", required: true, value: src?.offer?.start }),
      textField("f-offer-limit", "f_offer_limit", { type: "number", required: true, value: src?.offer?.limit }),
      textField("f-offer-step", "f_offer_step", { type: "number", required: true, value: src?.offer?.max_step }),
      h("div", { class: "field" }, h("label", { for: "f-offer-direction", text: t("f_offer_direction") }), dirSelect),
      textField("f-offer-target", "f_offer_target", { type: "number", value: src?.offer?.target }),
      textField("f-offer-mult", "f_offer_mult", { type: "number", hintKey: "f_offer_mult_hint", value: src?.offer?.multiplier && src.offer.multiplier !== 1 ? src.offer.multiplier : "" }),
      textField("f-offer-mult-label", "f_offer_mult_label", { value: src?.offer?.multiplier_label, maxlength: 60 })));
  offerOn.addEventListener("change", () => { offerFields.hidden = !offerOn.checked; });

  let title = v("title");
  if (mode === "duplicate" && title) title += t("copy_suffix");
  const saveBtn = h("button", { class: "btn btn-primary", type: "submit" }, t("save"));

  const form = h("form", { class: "builder", novalidate: true },
    errorSummary,
    h("fieldset", {}, h("legend", { text: t("section_basics") }),
      textField("f-title", "f_title", { required: true, value: title, maxlength: 120 }),
      textField("f-summary", "f_summary", { value: v("summary"), maxlength: 200 }),
      h("div", { class: "field" }, h("label", { for: "f-category", text: t("f_category") }), category),
      diffGroup,
      textField("f-brief", "f_brief", { hintKey: "f_brief_hint", required: true, multiline: true, rows: 4, value: v("brief"), maxlength: 2000 }),
      textField("f-goal", "f_goal", { hintKey: "f_goal_hint", required: true, multiline: true, value: v("goal"), maxlength: 1500 })),
    h("fieldset", {}, h("legend", { text: t("section_character") }),
      h("div", { class: "grid-2" },
        textField("f-name", "f_name", { required: true, value: v("character.name"), maxlength: 60 }),
        textField("f-role", "f_role", { hintKey: "f_role_hint", required: true, value: v("character.role"), maxlength: 120 })),
      lookGroup,
      textField("f-opening", "f_opening", { required: true, multiline: true, rows: 2, value: v("opening"), maxlength: 500 })),
    h("fieldset", { class: "hidden-section" }, h("legend", { text: t("section_hidden") }),
      h("p", { class: "hint", text: t("section_hidden_help") }),
      textField("f-persona", "f_persona", { hintKey: "f_persona_hint", required: true, multiline: true, rows: 5, value: v("persona"), maxlength: 3000 }),
      textField("f-private", "f_private", { hintKey: "f_private_hint", multiline: true, rows: 4, value: v("private_info"), maxlength: 3000 }),
      textField("f-rubric", "f_rubric", { hintKey: "f_rubric_hint", required: true, multiline: true, rows: 5, value: (src?.rubric || []).join("\n") }),
      textField("f-reveal", "f_reveal", { hintKey: "f_reveal_hint", multiline: true, rows: 2, value: v("reveal"), maxlength: 1000 })),
    h("fieldset", {}, h("legend", { text: t("section_number") }),
      h("div", { class: "field" }, h("label", { class: "check", for: "f-offer-on" }, offerOn, h("span", { text: t("f_offer_enable") })),
        h("p", { id: "f-offer-help", class: "hint", text: t("f_offer_help") })),
      offerFields),
    h("p", { class: "hint", text: t("builder_note") }),
    h("div", { class: "btn-row" }, saveBtn, h("a", { class: "btn", href: "#/library" }, t("cancel"))));

  fill(main,
    h("div", { class: "view-head" },
      h("h1", { text: editing ? t("builder_title_edit") : t("builder_title_new") }),
      h("p", { text: t("builder_intro") })),
    mode === "create" ? h("section", { class: "draft-box builder", "aria-labelledby": "draft-h" },
      h("h2", { id: "draft-h", text: t("draft_heading") }),
      h("div", { class: "field" },
        h("label", { for: "draft-desc", text: t("draft_label") }),
        h("p", { id: "draft-hint", class: "hint", text: t("draft_hint") }),
        draftInput),
      draftBtn, draftStatus) : null,
    form);

  const $ = (fid) => document.getElementById(fid);

  draftBtn.addEventListener("click", async () => {
    const desc = draftInput.value.trim();
    if (desc.length < 10) { draftInput.focus(); return; }
    draftBtn.disabled = true;
    notice(draftStatus, "info", t("drafting"));
    try {
      const d = await api("/api/scenarios/draft", { method: "POST", body: JSON.stringify({ description: desc, lang: state.lang }) });
      $("f-title").value = d.title || "";
      $("f-summary").value = d.summary || "";
      if (cfg.categories.includes(d.category)) category.value = d.category;
      const dd = form.querySelector(`input[name=difficulty][value="${d.difficulty}"]`); if (dd) dd.checked = true;
      $("f-brief").value = d.brief || "";
      $("f-goal").value = d.goal || "";
      $("f-name").value = d.character?.name || "";
      $("f-role").value = d.character?.role || "";
      const lk = form.querySelector(`input[name=look][value="${d.character?.look}"]`); if (lk) lk.checked = true;
      $("f-opening").value = d.opening || "";
      $("f-persona").value = d.persona || "";
      $("f-private").value = d.private_info || "";
      $("f-rubric").value = (d.rubric || []).join("\n");
      clearErrors();                  // the old "required" errors no longer apply
      notice(draftStatus, "ok", t("drafted"));
    } catch (err) {
      notice(draftStatus, "error", t("draft_failed"));
    } finally {
      draftBtn.disabled = false;
    }
  });

  const clearErrors = () => {
    errorSummary.replaceChildren();
    form.querySelectorAll("[aria-invalid]").forEach((el) => {
      el.removeAttribute("aria-invalid");
      const err = document.getElementById(`${el.id}-err`);
      if (err) err.remove();
      const db = (el.getAttribute("aria-describedby") || "").split(" ").filter((x) => x && x !== `${el.id}-err`).join(" ");
      if (db) el.setAttribute("aria-describedby", db); else el.removeAttribute("aria-describedby");
    });
  };
  const showErrors = (errs) => {
    clearErrors();
    for (const e of errs) {
      const el = $(e.id);
      if (!el) continue;
      el.setAttribute("aria-invalid", "true");
      el.setAttribute("aria-describedby", `${el.getAttribute("aria-describedby") || ""} ${e.id}-err`.trim());
      el.closest(".field, fieldset").append(h("p", { id: `${e.id}-err`, class: "field-error", text: e.message }));
    }
    errorSummary.replaceChildren(h("div", { class: "notice notice-error" },
      h("h2", { style: "font-size:1rem;margin:0", text: t("errors_heading", { n: errs.length }) }),
      h("ul", {}, errs.map((e) => h("li", {}, h("a", { href: `#${e.id}`, onclick: (ev) => { ev.preventDefault(); $(e.id)?.focus(); } }, e.message))))));
    errorSummary.focus();
  };

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const errs = [];
    const val = (fid) => $(fid).value.trim();
    const need = (fid, labelKey) => { if (!val(fid)) errs.push({ id: fid, message: t("err_required", { field: t(labelKey) }) }); };
    need("f-title", "f_title"); need("f-brief", "f_brief"); need("f-goal", "f_goal");
    need("f-name", "f_name"); need("f-role", "f_role"); need("f-opening", "f_opening"); need("f-persona", "f_persona");
    const rubric = val("f-rubric").split("\n").map((x) => x.trim()).filter(Boolean);
    if (rubric.length < 2 || rubric.length > 8) errs.push({ id: "f-rubric", message: t("err_rubric") });
    let offer = null;
    if (offerOn.checked) {
      need("f-offer-label", "f_offer_label"); need("f-offer-unit", "f_offer_unit");
      const numField = (fid, labelKey, required) => {
        const raw = val(fid);
        if (!raw) { if (required) errs.push({ id: fid, message: t("err_required", { field: t(labelKey) }) }); return null; }
        const n = Number(raw);
        if (!Number.isFinite(n)) { errs.push({ id: fid, message: t("err_number", { field: t(labelKey) }) }); return null; }
        return n;
      };
      offer = {
        label: val("f-offer-label"), unit: val("f-offer-unit"),
        start: numField("f-offer-start", "f_offer_start", true), limit: numField("f-offer-limit", "f_offer_limit", true),
        max_step: numField("f-offer-step", "f_offer_step", true), direction: dirSelect.value,
        target: numField("f-offer-target", "f_offer_target", false),
        multiplier: numField("f-offer-mult", "f_offer_mult", false) || 1, multiplier_label: val("f-offer-mult-label"),
      };
    }
    if (errs.length) return showErrors(errs);

    const body = {
      title: val("f-title"), summary: val("f-summary"), category: category.value,
      difficulty: form.querySelector("input[name=difficulty]:checked").value,
      brief: val("f-brief"), goal: val("f-goal"),
      character: { name: val("f-name"), role: val("f-role"), look: form.querySelector("input[name=look]:checked").value },
      opening: val("f-opening"), persona: val("f-persona"), private_info: val("f-private"),
      rubric, offer, reveal: val("f-reveal"),
    };
    saveBtn.disabled = true;
    saveBtn.textContent = t("saving");
    try {
      if (editing) await api(`/api/scenarios/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(body) });
      else await api("/api/scenarios", { method: "POST", body: JSON.stringify(body) });
      state.flash = t("saved");
      location.hash = "#/library";
    } catch (err) {
      const serverErrs = err?.detail?.errors;
      if (serverErrs) {
        showErrors(serverErrs.map((x) => ({ id: FIELD_FOR_SERVER[x.field] || "f-title", message: t("err_server", { field: x.field, message: x.message }) })));
      } else {
        errorSummary.replaceChildren(h("div", { class: "notice notice-error", text: typeof err?.detail === "string" ? err.detail : t("model_error") }));
        errorSummary.focus();
      }
    } finally {
      saveBtn.disabled = false;
      saveBtn.textContent = t("save");
    }
  });
}

// ---------------------------------------------------------------------------
// Insights
// ---------------------------------------------------------------------------
async function renderInsights() {
  const d = await api(`/api/insights?lang=${state.lang}`);
  setTitle(t("insights_title"));
  const head = h("div", { class: "view-head" }, h("h1", { text: t("insights_title") }), h("p", { text: t("insights_intro") }));
  if (!d.sessions_started) { main.replaceChildren(head, h("p", { text: t("no_data") })); return; }
  const dash = (x, f) => (x === null || x === undefined ? "–" : f(x));
  const stat = (label, value) => h("div", { class: "stat" }, h("dt", { text: label }), h("dd", { text: value }));
  const max = Math.max(1, ...d.score_distribution);
  main.replaceChildren(
    head,
    h("dl", { class: "stat-grid" },
      stat(t("sessions_started"), num(d.sessions_started)),
      stat(t("sessions_completed"), num(d.sessions_completed)),
      stat(t("avg_score"), dash(d.avg_score, (x) => num(x, 1))),
      stat(t("avg_reply"), dash(d.avg_reply_seconds, (x) => t("seconds", { n: num(x, 1) }))),
      stat(t("total_cost"), `$${d.total_cost.toFixed(4)}`),
      stat(t("cost_per_session"), dash(d.cost_per_session, (x) => `$${x.toFixed(4)}`)),
      stat(t("error_rate"), dash(d.error_rate_pct, (x) => `${num(x, 1)}%`))),
    h("section", { class: "card", style: "margin-top:1rem", "aria-labelledby": "dist-h" },
      h("h2", { id: "dist-h", text: t("score_distribution") }),
      h("ol", { class: "bars" }, d.score_distribution.map((count, i) =>
        h("li", {},
          h("span", { class: "n", "aria-hidden": "true", text: count }),
          h("span", { class: "bar", "aria-hidden": "true", style: `height:${(count / max) * 120}px` }),
          h("span", { "aria-hidden": "true", text: i + 1 }),
          h("span", { class: "visually-hidden", text: `${t("score_n", { n: i + 1 })}: ${t("sessions_n", { n: count })}` }))))),
    h("div", { class: "table-wrap", style: "margin-top:1rem" }, h("table", {},
      h("caption", { style: "padding:.75rem", text: t("by_scenario") }),
      h("thead", {}, h("tr", {}, ["col_scenario", "col_started", "col_completed", "col_reached", "col_avg_score", "col_voice"].map((k) => h("th", { scope: "col", text: t(k) })))),
      h("tbody", {}, d.by_scenario.map((r) => h("tr", {},
        h("th", { scope: "row", text: r.title }),
        h("td", { text: num(r.started) }), h("td", { text: num(r.completed) }),
        h("td", { text: dash(r.reached_pct, (x) => `${x}%`) }),
        h("td", { text: dash(r.avg_score, (x) => num(x, 1)) }),
        h("td", { text: dash(r.voice_pct, (x) => `${x}%`) })))))));
}

// ---------------------------------------------------------------------------
// Start
// ---------------------------------------------------------------------------
document.getElementById("lang-select").addEventListener("change", async (e) => {
  await setLang(e.target.value);
  route();
});
window.addEventListener("hashchange", route);
document.querySelector(".skip-link").addEventListener("click", (e) => {
  e.preventDefault();               // don't change the address (that would reload the view)
  main.focus();
});
setLang(savedLang()).then(route);
