// Avatar: an SVG face with five looks and five moods, plus "thinking", "listening"
// and "speaking" states. The mouth opening is set from the live audio volume.

const MOODS = {
  neutral:  { browL: "M74,86 Q84,83 94,86", browR: "M106,86 Q116,83 126,86", mouth: "M90,127 Q100,129 110,127" },
  pleased:  { browL: "M74,83 Q84,77 94,82", browR: "M106,82 Q116,77 126,83", mouth: "M87,123 Q100,137 113,123" },
  thinking: { browL: "M74,87 Q84,86 94,88", browR: "M106,82 Q116,75 126,81", mouth: "M92,129 Q103,125 111,127" },
  firm:     { browL: "M74,82 Q85,84 95,90", browR: "M105,90 Q115,84 126,82", mouth: "M90,128 L110,128" },
  upset:    { browL: "M74,90 Q85,83 95,85", browR: "M105,85 Q115,83 126,90", mouth: "M89,131 Q100,123 111,131" },
};

// Each look: skin, hair and clothing colours, plus the parts drawn behind and in front of the face.
const LOOKS = {
  "man-beard": {
    skin: "#D9A27E", ear: "#C98F6B", neck: "#C08560", suit: "#2F3E55", tie: "#8B2E2E",
    back: "",
    front: `<path d="M60,94 C56,56 80,46 100,46 C122,46 144,56 140,94 C135,74 121,64 100,64 C79,64 65,74 60,94 Z" fill="#262626"/>
      <path d="M61,104 C61,139 80,153 100,153 C120,153 139,139 139,104 C135,121 130,131 122,136 C114,141 86,141 78,136 C70,131 65,121 61,104 Z" fill="#262626" opacity=".88"/>
      <path d="M83,119 C92,113 108,113 117,119 C108,117 92,117 83,119 Z" fill="#262626"/>`,
  },
  "man-clean": {
    skin: "#C68B63", ear: "#B67B55", neck: "#AD744F", suit: "#3D4A3A", tie: "#C9A227",
    back: "",
    front: `<path d="M60,96 C55,58 78,44 102,45 C126,46 146,60 140,96 C138,80 128,66 110,63 C98,72 76,72 64,74 C61,80 60,88 60,96 Z" fill="#3B2A20"/>`,
  },
  "man-glasses": {
    skin: "#E0B08A", ear: "#D09E78", neck: "#C9946D", suit: "#4A4F5C", tie: "#2E6B8B",
    back: "",
    front: `<path d="M61,92 C58,60 78,48 100,48 C122,48 142,60 139,92 C136,78 128,70 118,68 C108,64 92,64 82,68 C72,70 64,78 61,92 Z" fill="#6E6E6E"/>
      <g fill="none" stroke="#1F1F1F" stroke-width="2.6"><rect x="72" y="89" width="24" height="18" rx="6"/><rect x="104" y="89" width="24" height="18" rx="6"/>
      <path d="M96,97 Q100,94 104,97"/><path d="M72,96 L62,94"/><path d="M128,96 L138,94"/></g>`,
  },
  "woman-hijab": {
    skin: "#D7A47F", ear: null, neck: null, suit: "#2F5D62", tie: null,
    back: `<path d="M50,104 C50,54 76,36 100,36 C124,36 150,54 150,104 C150,128 146,150 138,166 C160,176 174,188 180,205 L20,205 C26,188 40,176 62,166 C54,150 50,128 50,104 Z" fill="#2F5D62"/>`,
    front: `<path d="M62,98 C62,66 80,52 100,52 C120,52 138,66 138,98" fill="none" stroke="#24494D" stroke-width="3"/>`,
    face: { rx: 33, ry: 40, cy: 104 },
    brow: 3,
  },
  "woman-hair": {
    skin: "#E6B892", ear: "#D9A883", neck: "#D19F7B", suit: "#6B3F5E", tie: null,
    back: `<path d="M54,98 C50,52 78,40 100,40 C124,40 152,52 146,98 L152,156 C140,166 60,166 48,156 Z" fill="#2A1D17"/>`,
    front: `<path d="M61,94 C62,62 84,50 104,52 C126,54 140,70 139,94 C128,78 112,70 96,72 C84,74 70,82 61,94 Z" fill="#2A1D17"/>
      <circle cx="62" cy="116" r="2.6" fill="#D4AF37"/><circle cx="138" cy="116" r="2.6" fill="#D4AF37"/>`,
    brow: 3,
  },
};

function svgFor(lookName, moodName, uid) {
  const L = LOOKS[lookName] || LOOKS["man-clean"];
  const M = MOODS[moodName] || MOODS.neutral;
  const face = L.face || { rx: 40, ry: 48, cy: 100 };
  const browW = L.brow || 4;
  const female = lookName.startsWith("woman");
  const lip = female ? "#A84A4A" : "#8C3B35";
  const body = female
    ? `<path d="M30,205 C34,176 60,160 100,158 C140,160 166,176 170,205 Z" fill="${L.suit}"/>`
    : `<path d="M22,205 C26,170 52,156 84,152 L116,152 C148,156 174,170 178,205 Z" fill="${L.suit}"/>
       <path d="M84,152 L100,186 L116,152 Z" fill="#F8FAFC"/>
       <path d="M96,160 L104,160 L106,186 L100,194 L94,186 Z" fill="${L.tie}"/>`;
  return `
<svg viewBox="0 0 200 200" aria-hidden="true" focusable="false">
  <defs><clipPath id="clip-${uid}"><circle cx="100" cy="100" r="98"/></clipPath></defs>
  <circle class="av-bg" cx="100" cy="100" r="98"/>
  <g clip-path="url(#clip-${uid})">
    ${L.back}
    ${body}
    ${L.neck ? `<rect x="88" y="132" width="24" height="26" rx="8" fill="${L.neck}"/>` : ""}
    <g class="av-head">
      ${L.ear ? `<ellipse cx="60" cy="103" rx="7" ry="10" fill="${L.ear}"/><ellipse cx="140" cy="103" rx="7" ry="10" fill="${L.ear}"/>` : ""}
      <ellipse cx="100" cy="${face.cy}" rx="${face.rx}" ry="${face.ry}" fill="${L.skin}"/>
      ${L.front}
      <g class="av-eyes">
        <ellipse cx="84" cy="98" rx="4.2" ry="4.6" fill="#1F1A17"/><ellipse cx="116" cy="98" rx="4.2" ry="4.6" fill="#1F1A17"/>
        <circle cx="85.5" cy="96.5" r="1.2" fill="#fff"/><circle cx="117.5" cy="96.5" r="1.2" fill="#fff"/>
      </g>
      <path class="av-brow-l" d="${M.browL}" stroke="#1F1F1F" stroke-width="${browW}" stroke-linecap="round" fill="none"/>
      <path class="av-brow-r" d="${M.browR}" stroke="#1F1F1F" stroke-width="${browW}" stroke-linecap="round" fill="none"/>
      <path d="M100,101 C98,108 96,112 100,114" stroke="#A86F4E" stroke-width="2" stroke-linecap="round" fill="none"/>
      <path class="av-mouth" d="${M.mouth}" stroke="${lip}" stroke-width="3.4" stroke-linecap="round" fill="none"/>
      <ellipse class="av-mouth-open" cx="100" cy="128" rx="8.5" ry="4" fill="#5B1F1F" stroke="${lip}" stroke-width="1.5"/>
    </g>
  </g>
  <g class="av-think"><circle cx="152" cy="52" r="4"/><circle cx="164" cy="40" r="5"/><circle cx="178" cy="26" r="6"/></g>
</svg>`;
}

let counter = 0;

export class Avatar {
  constructor(container, look) {
    this.el = container;
    this.look = look;
    this.mood = "neutral";
    this.uid = `av${++counter}`;
    this.el.classList.add("avatar");
    this.render();
  }
  render() {
    this.el.innerHTML = svgFor(this.look, this.mood, this.uid);
    this.mouth = this.el.querySelector(".av-mouth-open");
  }
  setMood(mood) {
    if (!MOODS[mood] || mood === this.mood) return;
    this.mood = mood;
    const M = MOODS[mood];
    this.el.querySelector(".av-brow-l").setAttribute("d", M.browL);
    this.el.querySelector(".av-brow-r").setAttribute("d", M.browR);
    this.el.querySelector(".av-mouth").setAttribute("d", M.mouth);
  }
  setState(state) {           // idle | listening | thinking | speaking
    this.el.dataset.state = state;
    if (state !== "speaking") this.setMouth(0);
  }
  setMouth(level) {           // 0 = closed, 1 = wide open
    if (!this.mouth) return;
    this.mouth.setAttribute("ry", (0.8 + Math.min(1, level) * 7.5).toFixed(2));
  }
}

export function avatarThumb(look) {
  return svgFor(look, "neutral", `t${++counter}`);
}
