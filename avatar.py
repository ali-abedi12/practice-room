"""
Yousef's avatar: an SVG face with four moods, blinking, a "thinking" state,
and lip-sync driven by the actual audio volume.

How the lip-sync works:
- The reply audio is embedded in the page as a data URL.
- The browser's Web Audio API measures the volume ~60 times a second.
- Louder sound -> mouth opens wider. Silence -> mouth closes.
- If the browser blocks that (or autoplay), it falls back to a simple
  looping mouth animation, or a Play button.

Rendered with st.html(..., unsafe_allow_javascript=True), so it runs in the
main page rather than an iframe. That matters: browsers allow autoplay
after the user has interacted with the page, and typing a message counts.
"""

import base64
import html
import json

# Eyebrow and resting-mouth shapes for each mood (SVG path data).
FACES = {
    "neutral": {"brow_l": "M74,86 Q84,83 94,86", "brow_r": "M106,86 Q116,83 126,86",
                "mouth": "M90,127 Q100,129 110,127"},
    "pleased": {"brow_l": "M74,83 Q84,77 94,82", "brow_r": "M106,82 Q116,77 126,83",
                "mouth": "M87,123 Q100,137 113,123"},
    "thinking": {"brow_l": "M74,87 Q84,86 94,88", "brow_r": "M106,82 Q116,75 126,81",
                 "mouth": "M92,129 Q103,125 111,127"},
    "firm": {"brow_l": "M74,82 Q85,84 95,90", "brow_r": "M105,90 Q115,84 126,82",
             "mouth": "M90,128 L110,128"},
}

CSS = """
<style>
.ys-card{display:flex;flex-direction:column;align-items:center;gap:.6rem;padding:1.25rem 1rem 1rem;border-radius:18px;
  background:#F3F6FA;border:1px solid #DCE3EC;color:#1D2633;font-family:inherit}
.ys-avatar{width:200px;height:200px;position:relative;max-width:60vw;max-height:60vw}
.ys-avatar svg{width:100%;height:100%;display:block}
.ys-body{width:100%;display:flex;flex-direction:column;align-items:center;text-align:center}
.ys-name{font-weight:700;font-size:1.2rem;line-height:1.2}
.ys-role{font-size:.82rem;color:#4A5668;margin-bottom:.45rem}
.ys-chip{display:inline-block;font-size:.75rem;font-weight:600;padding:.12rem .55rem;border-radius:999px;
  margin-bottom:.55rem;border:1px solid transparent}
.ys-chip.neutral{background:#E6EAF0;color:#334155;border-color:#CBD3DE}
.ys-chip.pleased{background:#DDF3E4;color:#14532D;border-color:#A7DDB8}
.ys-chip.thinking{background:#FDF1D6;color:#713F12;border-color:#F0D48E}
.ys-chip.firm{background:#FBE1E1;color:#7F1D1D;border-color:#EBB0B0}
.ys-bubble{position:relative;width:100%;box-sizing:border-box;text-align:start;background:#fff;border:1px solid #DCE3EC;
  border-radius:14px;padding:.75rem .9rem;font-size:1rem;line-height:1.5;max-height:12rem;overflow-y:auto}
.ys-actions{margin-top:.55rem;display:flex;gap:.5rem;align-items:center;justify-content:center}
.ys-btn{font:inherit;font-size:.82rem;padding:.3rem .7rem;border-radius:8px;border:1px solid #9AA8BA;
  background:#fff;color:#1D2633;cursor:pointer}
.ys-btn:hover{background:#EEF2F7}
.ys-btn:focus-visible{outline:3px solid #2563EB;outline-offset:2px}
.ys-dots span{display:inline-block;width:7px;height:7px;margin:0 2px;border-radius:50%;background:#64748B;
  animation:ys-dot 1.2s infinite ease-in-out}
.ys-dots span:nth-child(2){animation-delay:.15s}.ys-dots span:nth-child(3){animation-delay:.3s}
@keyframes ys-dot{0%,80%,100%{transform:translateY(0);opacity:.4}40%{transform:translateY(-5px);opacity:1}}
.ys-eyes{transform-box:fill-box;transform-origin:center;animation:ys-blink 4.5s infinite}
@keyframes ys-blink{0%,95%,100%{transform:scaleY(1)}97%{transform:scaleY(.1)}}
.ys-head{transform-box:view-box;transform-origin:100px 150px;animation:ys-bob 6s infinite ease-in-out}
@keyframes ys-bob{0%,100%{transform:rotate(0)}50%{transform:rotate(1.2deg)}}
.ys-mouth-open{display:none}
.ys-talking .ys-mouth-open{display:block}
.ys-talking .ys-mouth-rest{display:none}
.ys-talking.ys-css-talk .ys-mouth-open{transform-box:fill-box;transform-origin:center;animation:ys-talk .28s infinite alternate}
@keyframes ys-talk{from{transform:scaleY(.25)}to{transform:scaleY(1)}}
.ys-waiting .ys-eyes{transform:translate(3px,-3px);animation:none}
.ys-think-dots{display:none}
.ys-waiting .ys-think-dots{display:block}
.ys-think-dots circle{animation:ys-dot 1.2s infinite ease-in-out}
.ys-think-dots circle:nth-child(2){animation-delay:.2s}.ys-think-dots circle:nth-child(3){animation-delay:.4s}
@media (prefers-reduced-motion: reduce){
  .ys-eyes,.ys-head,.ys-dots span,.ys-think-dots circle{animation:none}
}
@media (prefers-color-scheme: dark){
  .ys-card{background:#1E2633;border-color:#334155;color:#E5E9F0}
  .ys-role{color:#A7B2C3}
  .ys-bubble{background:#0F1520;border-color:#334155;color:#E5E9F0}
  .ys-btn{background:#0F1520;color:#E5E9F0;border-color:#4B5A70}
}
</style>
"""

SVG = """
<svg viewBox="0 0 200 200" role="img" aria-label="{aria}">
  <circle cx="100" cy="100" r="98" fill="#DCE6F2"/>
  <clipPath id="ys-clip-{uid}"><circle cx="100" cy="100" r="98"/></clipPath>
  <g clip-path="url(#ys-clip-{uid})">
    <path d="M22,205 C26,170 52,156 84,152 L116,152 C148,156 174,170 178,205 Z" fill="#2F3E55"/>
    <path d="M84,152 L100,186 L116,152 Z" fill="#F8FAFC"/>
    <path d="M96,160 L104,160 L106,186 L100,194 L94,186 Z" fill="#8B2E2E"/>
    <rect x="88" y="132" width="24" height="26" rx="8" fill="#C08560"/>
    <g class="ys-head">
      <ellipse cx="60" cy="103" rx="7" ry="10" fill="#C98F6B"/>
      <ellipse cx="140" cy="103" rx="7" ry="10" fill="#C98F6B"/>
      <ellipse cx="100" cy="100" rx="40" ry="48" fill="#D9A27E"/>
      <path d="M60,94 C56,56 80,46 100,46 C122,46 144,56 140,94 C135,74 121,64 100,64 C79,64 65,74 60,94 Z" fill="#262626"/>
      <path d="M61,104 C61,139 80,153 100,153 C120,153 139,139 139,104 C135,121 130,131 122,136
               C114,141 86,141 78,136 C70,131 65,121 61,104 Z" fill="#262626" opacity=".88"/>
      <path d="M83,119 C92,113 108,113 117,119 C108,117 92,117 83,119 Z" fill="#262626"/>
      <g class="ys-eyes">
        <ellipse cx="84" cy="98" rx="4.2" ry="4.6" fill="#1F1A17"/>
        <ellipse cx="116" cy="98" rx="4.2" ry="4.6" fill="#1F1A17"/>
        <circle cx="85.5" cy="96.5" r="1.2" fill="#fff"/>
        <circle cx="117.5" cy="96.5" r="1.2" fill="#fff"/>
      </g>
      <path class="ys-brow-l" d="{brow_l}" stroke="#1F1F1F" stroke-width="4" stroke-linecap="round" fill="none"/>
      <path class="ys-brow-r" d="{brow_r}" stroke="#1F1F1F" stroke-width="4" stroke-linecap="round" fill="none"/>
      <path d="M100,101 C98,108 96,112 100,114" stroke="#A86F4E" stroke-width="2" stroke-linecap="round" fill="none"/>
      <path class="ys-mouth-rest" d="{mouth}" stroke="#8C3B35" stroke-width="3.4" stroke-linecap="round" fill="none"/>
      <ellipse class="ys-mouth-open" cx="100" cy="128" rx="8.5" ry="5" fill="#5B1F1F" stroke="#8C3B35" stroke-width="1.5"/>
    </g>
  </g>
  <g class="ys-think-dots" fill="#64748B">
    <circle cx="152" cy="52" r="4"/><circle cx="164" cy="40" r="5"/><circle cx="178" cy="26" r="6"/>
  </g>
</svg>
"""

JS = """
<script>
(function () {
  var card = document.querySelector('[data-ys-uid="__UID__"]');
  if (!card) return;
  var msgId = card.getAttribute('data-ys-msg');
  var autoplay = card.getAttribute('data-ys-autoplay') === '1';
  var holder = card.querySelector('.ys-audio-src');
  var src = holder ? holder.getAttribute('data-src') : '';
  var playBtn = card.querySelector('.ys-play');
  // Streamlit's HTML sanitiser strips inline SVG, and any script whose text looks like markup,
  // so the face is stored with its angle brackets escaped and drawn here.
  var avatarBox = card.querySelector('.ys-avatar');
  if (avatarBox && !avatarBox.querySelector('svg')) avatarBox.innerHTML = __SVG__;
  window.__ysPlayed = window.__ysPlayed || {};

  function liveCard() {           // the newest card on the page (Streamlit may re-render)
    var all = document.querySelectorAll('[data-ys-card]');
    return all.length ? all[all.length - 1] : null;
  }
  function setTalking(on, cssOnly) {
    var c = liveCard(); if (!c) return;
    var av = c.querySelector('.ys-avatar');
    av.classList.toggle('ys-talking', on);
    av.classList.toggle('ys-css-talk', !!(on && cssOnly));
  }

  function lipSync(audio) {
    try {
      var Ctx = window.AudioContext || window.webkitAudioContext;
      var ctx = window.__ysCtx || (window.__ysCtx = new Ctx());
      return ctx.resume().then(function () {
        if (ctx.state !== 'running') { setTalking(true, true); return; }
        var source = ctx.createMediaElementSource(audio);
        var analyser = ctx.createAnalyser();
        analyser.fftSize = 512;
        source.connect(analyser); analyser.connect(ctx.destination);
        var buf = new Uint8Array(analyser.fftSize);
        // Start measuring once sound actually starts, not before.
        audio.addEventListener('playing', function () { setTalking(true, false); frame(); });
        function frame() {
          if (audio.ended || audio.paused) return;
          analyser.getByteTimeDomainData(buf);
          var sum = 0;
          for (var i = 0; i < buf.length; i++) { var v = (buf[i] - 128) / 128; sum += v * v; }
          var level = Math.sqrt(sum / buf.length);             // 0 = silence
          var c = liveCard();
          var mouth = c && c.querySelector('.ys-mouth-open');
          if (mouth) mouth.setAttribute('ry', (0.8 + Math.min(7.5, level * 45)).toFixed(2));
          requestAnimationFrame(frame);
        }
      });
    } catch (e) { setTalking(true, true); return Promise.resolve(); }
  }

  function play() {
    if (!src) return;
    if (window.__ysAudio) { try { window.__ysAudio.pause(); } catch (e) {} }
    var audio = new Audio(src);
    window.__ysAudio = audio;
    audio.addEventListener('ended', function () { setTalking(false); });
    audio.addEventListener('pause', function () { setTalking(false); });
    lipSync(audio).then(function () {
      return audio.play();
    }).catch(function () {
      setTalking(false);                       // autoplay blocked: offer a button
      if (playBtn) { playBtn.hidden = false; playBtn.focus({preventScroll: true}); }
    });
  }

  if (playBtn) playBtn.addEventListener('click', play);
  if (autoplay && src && !window.__ysPlayed[msgId]) {
    window.__ysPlayed[msgId] = true;
    play();
  }
})();
</script>
"""


def render_card(*, uid, msg_id, name, role, mood, mood_label, text, waiting=False,
                waiting_text="", audio=None, audio_mime="audio/wav", autoplay=False,
                play_label="Play", aria_label="Yousef"):
    """Return the HTML for the avatar card. Pass to st.html(..., unsafe_allow_javascript=True)."""
    face = FACES.get(mood, FACES["neutral"])
    svg = SVG.format(uid=uid, aria=html.escape(aria_label), **face)

    if waiting:
        bubble = (f'<span class="ys-dots" aria-hidden="true"><span></span><span></span><span></span></span> '
                  f'<span>{html.escape(waiting_text)}</span>')
    else:
        bubble = html.escape(text).replace("\n", "<br>")

    audio_holder = ""
    play_button = ""
    if audio and not waiting:
        data_url = f"data:{audio_mime};base64,{base64.b64encode(audio).decode()}"
        audio_holder = f'<span class="ys-audio-src" hidden data-src="{data_url}"></span>'
        play_button = f'<button type="button" class="ys-btn ys-play">🔊 {html.escape(play_label)}</button>'

    return (
        CSS
        + f'<div class="ys-card" data-ys-card data-ys-uid="{uid}" data-ys-msg="{html.escape(msg_id)}" '
          f'data-ys-autoplay="{1 if autoplay else 0}">'
        + f'<div class="ys-avatar{" ys-waiting" if waiting else ""}"></div>'
        + '<div class="ys-body">'
        + f'<div class="ys-name">{html.escape(name)}</div>'
        + f'<div class="ys-role">{html.escape(role)}</div>'
        + f'<span class="ys-chip {mood}">{html.escape(mood_label)}</span>'
        + f'<div class="ys-bubble" dir="auto" aria-live="polite">{bubble}</div>'
        + f'<div class="ys-actions">{play_button}</div>'
        + audio_holder
        + '</div></div>'
        + JS.replace("__UID__", json.dumps(uid)[1:-1])
             .replace("__SVG__", json.dumps(svg).replace("<", "\\u003c").replace(">", "\\u003e"))
    )
