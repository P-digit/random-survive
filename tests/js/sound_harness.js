// survival/static/sound.js 를 가짜 브라우저(Web Audio·DOM)에서 돌려 본다. 결과를 JSON 한 줄로 출력한다.
// 사용: node sound_harness.js <sound.js 경로> <cue JSON>
const fs = require("fs");
const vm = require("vm");

const [scriptPath, cueJson] = process.argv.slice(2);
const calls = { started: 0, scheduled: 0, errors: [] };

class Param {
  constructor(value = 0) { this.value = value; }
  setTargetAtTime(v) { this.value = v; }
  setValueAtTime(v) { this.value = v; }
  linearRampToValueAtTime(v) { this.value = v; }
  exponentialRampToValueAtTime(v) {
    if (!(v > 0)) calls.errors.push("exponentialRamp to non-positive value");
    this.value = v;
  }
}
class Node {
  connect(target) { return target instanceof Param ? undefined : target; }
}
class Gain extends Node { constructor() { super(); this.gain = new Param(1); } }
class Filter extends Node { constructor() { super(); this.frequency = new Param(350); this.Q = new Param(1); this.type = "lowpass"; } }
class Osc extends Node {
  constructor() { super(); this.frequency = new Param(440); this.type = "sine"; }
  start() { calls.started++; } stop() {}
}
class Source extends Node { start() { calls.started++; } stop() {} }
class AudioContext {
  constructor() { this.sampleRate = 8000; this.currentTime = 0; this.state = "suspended"; this.destination = new Node(); }
  resume() { this.state = "running"; }
  suspend() { this.state = "suspended"; }
  createGain() { return new Gain(); }
  createBiquadFilter() { return new Filter(); }
  createOscillator() { return new Osc(); }
  createBufferSource() { calls.scheduled++; return new Source(); }
  createBuffer(channels, length) { const data = new Float32Array(length); return { getChannelData: () => data }; }
}

const listeners = {};
let observer = null;
let cueNodes = [];
const intervals = [];
const appended = [];
function element(tag) {
  const el = { tag, children: [], dataset: {}, attributes: {}, textContent: "", value: "", disabled: false,
    listeners: {}, innerHTML: "",
    setAttribute(k, v) { this.attributes[k] = v; },
    addEventListener(t, f) { this.listeners[t] = f; },
    querySelector(sel) { return (this._kids = this._kids || { button: element("button"), input: element("input") })[sel]; } };
  return el;
}
const document = {
  readyState: "complete",
  body: { appendChild: (el) => appended.push(el) },
  getElementById: (id) => appended.find((el) => el.id === id) || null,
  createElement: element,
  querySelectorAll: (sel) => (sel === "#rs-sound-cue" ? cueNodes : []),
  addEventListener: (type, fn) => { (listeners[type] = listeners[type] || []).push(fn); },
};
const store = {};
const window = {
  AudioContext,
  localStorage: { getItem: (k) => store[k] || null, setItem: (k, v) => { store[k] = v; } },
};
const context = {
  window, document, console, Math, JSON, Object, Number, String, Boolean, Float32Array,
  localStorage: window.localStorage,
  setInterval: (fn) => intervals.push(fn),
  MutationObserver: class { constructor(fn) { observer = fn; } observe() {} },
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(scriptPath, "utf8"), context);

const sound = window.rsSound;
const result = { controls: Boolean(document.getElementById("rs-sound-controls")) };
// 1) 신호가 먼저 와도 클릭 전에는 소리를 만들지 않는다
cueNodes = [{ dataset: { cue: cueJson } }];
observer();
result.beforeClick = { running: sound.running(), levels: sound.levels() };
// 2) 첫 클릭에서 시작하고, 받아 둔 신호를 적용한다
for (const fn of listeners.pointerdown || []) fn();
result.afterClick = { running: sound.running(), levels: sound.levels() };
// 3) 가끔 나는 소리(새, 불꽃, 천둥, 차)를 여러 번 굴려 본다
const before = calls.scheduled;
for (let i = 0; i < 400; i++) intervals.forEach((fn) => fn());
result.occasionalPlayed = calls.scheduled - before + calls.started;
// 4) 사건 효과음: nonce가 바뀌면 한 번 울리고, 같은 nonce로 다시 와도(그림 갱신 등) 다시 울리지 않는다
const base = JSON.parse(cueJson);
const withSfx = (nonce, events) => [{ dataset: { cue: JSON.stringify(Object.assign({}, base, { sfx: { nonce, events } })) } }];
let mark = calls.started;
cueNodes = withSfx("next-turn", sound.effects);
observer();
result.sfxPlayed = calls.started - mark;
mark = calls.started;
observer();
result.sfxReplayed = calls.started - mark;
result.effects = sound.effects;
// 5) 다른 탭으로 가면 멈추고, 그동안 온 효과음은 울리지 않으며, 돌아오면 다시 켠다
document.hidden = true;
for (const fn of listeners.visibilitychange || []) fn();
mark = calls.started;
cueNodes = withSfx("while-hidden", ["danger"]);
observer();
result.hidden = { running: sound.running(), played: calls.started - mark };
document.hidden = false;
for (const fn of listeners.visibilitychange || []) fn();
result.visibleAgain = sound.running();
// 5) 같은 신호가 다시 와도 그대로, 소리 끄기 버튼
observer();
const button = appended[0].querySelector("button");
button.listeners.click();
result.muted = { on: sound.prefs.on, label: button.textContent, saved: store["rs-sound"] };
mark = calls.started;
cueNodes = withSfx("after-mute", ["offer", "danger"]);
observer();
result.sfxWhileMuted = calls.started - mark;
result.errors = calls.errors;
console.log(JSON.stringify(result));
