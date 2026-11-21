/* 랜덤 좌표 생존기 - 배경 소리 엔진 (Web Audio 합성, 파일 없음)
 *
 * 엔진(survival/sound.py)이 정한 소리 신호를 상태창 안의 <div id="rs-sound-cue" data-cue="..."> 로 받는다.
 * 그 값이 바뀌면 층별 크기를 2초에 걸쳐 부드럽게 바꾼다. 모든 소리는 노이즈·발진기로 합성한다.
 * 브라우저는 사용자가 클릭하기 전에는 소리를 낼 수 없으므로, 첫 클릭(예: '낙하 시작')에서 시작한다.
 *
 * 같은 신호의 sfx({events, nonce})는 이번 턴의 사건 효과음이다. nonce가 바뀔 때 한 번만 울린다.
 */
(() => {
  if (window.rsSound) return;

  const LAYERS = ["wind", "rain", "thunder", "birds", "insects", "stream", "waves", "fire", "crowd", "traffic"];
  // 층마다 실제 출력 크기의 상한 (합성 소리마다 체감 크기가 달라 맞춰 준다)
  const SCALE = { wind: 0.5, rain: 0.45, thunder: 0.9, birds: 0.18, insects: 0.05, stream: 0.3,
                  waves: 0.5, fire: 0.45, crowd: 0.25, traffic: 0.35 };
  const STORE = "rs-sound";

  const prefs = (() => {
    const fallback = { on: true, volume: 0.6 };
    try { return Object.assign(fallback, JSON.parse(localStorage.getItem(STORE) || "{}")); }
    catch (e) { return fallback; }
  })();
  const savePrefs = () => { try { localStorage.setItem(STORE, JSON.stringify(prefs)); } catch (e) { /* 저장 불가 */ } };

  let ctx = null, master = null, muffle = null, sfxBus = null;
  let lastNonce = null;
  const layers = {};            // 이름 → GainNode (층의 크기)
  let target = { layers: {}, indoor: false, key: "silent" };
  let lastKey = null;
  let noise = {};

  // ---------- 재료: 노이즈 버퍼 ----------
  function makeNoise(kind) {
    const length = ctx.sampleRate * 4;
    const buffer = ctx.createBuffer(1, length, ctx.sampleRate);
    const data = buffer.getChannelData(0);
    let b0 = 0, b1 = 0, b2 = 0, last = 0;
    for (let i = 0; i < length; i++) {
      const white = Math.random() * 2 - 1;
      if (kind === "white") {
        data[i] = white * 0.5;
      } else if (kind === "pink") {   // 간단한 핑크 노이즈 (Paul Kellet 근사)
        b0 = 0.99765 * b0 + white * 0.0990460;
        b1 = 0.96300 * b1 + white * 0.2965164;
        b2 = 0.57000 * b2 + white * 1.0526913;
        data[i] = (b0 + b1 + b2 + white * 0.1848) * 0.12;
      } else {                        // 브라운 노이즈: 낮고 둥근 소리 (바람, 파도, 천둥)
        last = (last + 0.02 * white) / 1.02;
        data[i] = last * 3.5;
      }
    }
    return buffer;
  }

  function loop(buffer) {
    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.loop = true;
    source.loopStart = Math.random() * 3;   // 층마다 다른 지점에서 시작해 반복이 덜 들리게
    source.start(0, source.loopStart);
    return source;
  }

  function filter(type, frequency, q = 0.7) {
    const node = ctx.createBiquadFilter();
    node.type = type;
    node.frequency.value = frequency;
    node.Q.value = q;
    return node;
  }

  function chain(...nodes) {
    for (let i = 0; i < nodes.length - 1; i++) nodes[i].connect(nodes[i + 1]);
    return nodes[nodes.length - 1];
  }

  // 느린 흔들림: param 을 center ± depth 사이로 움직인다
  function wobble(param, center, depth, rate, wave = "sine") {
    param.value = center;
    const osc = ctx.createOscillator();
    osc.type = wave;
    osc.frequency.value = rate;
    const amount = ctx.createGain();
    amount.gain.value = depth;
    osc.connect(amount).connect(param);
    osc.start();
  }

  function layerGain(name) {
    const gain = ctx.createGain();
    gain.gain.value = 0;
    gain.connect(muffle);
    layers[name] = gain;
    return gain;
  }

  // ---------- 이어지는 소리 ----------
  function buildContinuous() {
    // 바람: 브라운 노이즈를 대역 통과 필터로 걸러, 필터 주파수와 크기를 천천히 흔든다 (돌풍)
    const windBand = filter("bandpass", 450, 0.6);
    const windSwell = ctx.createGain();
    chain(loop(noise.brown), windBand, windSwell, layerGain("wind"));
    wobble(windBand.frequency, 450, 250, 0.07);
    wobble(windSwell.gain, 0.75, 0.25, 0.13);

    // 비: 흰 노이즈의 높은 쪽 + 낮게 깔리는 웅웅거림
    const rain = layerGain("rain");
    chain(loop(noise.white), filter("highpass", 1200), filter("lowpass", 9000), rain);
    const roar = ctx.createGain();
    roar.gain.value = 0.35;
    chain(loop(noise.pink), filter("lowpass", 800), roar, rain);

    // 개울: 핑크 노이즈를 빠르게 흔들어 물이 흐르는 느낌
    const streamBand = filter("bandpass", 1800, 0.5);
    chain(loop(noise.pink), streamBand, layerGain("stream"));
    wobble(streamBand.frequency, 1800, 500, 2.7);

    // 파도: 낮은 노이즈의 크기를 8초 주기로 크게 오르내린다
    const waveSwell = ctx.createGain();
    chain(loop(noise.brown), filter("lowpass", 700), waveSwell, layerGain("waves"));
    wobble(waveSwell.gain, 0.6, 0.4, 0.12);

    // 모닥불: 낮게 타오르는 소리 (탁탁 튀는 소리는 아래 scheduler)
    const fire = layerGain("fire");
    const fireLow = ctx.createGain();
    fireLow.gain.value = 0.5;
    chain(loop(noise.brown), filter("lowpass", 400), fireLow, fire);

    // 사람들: 말소리 대역의 노이즈를 천천히 흔든다 (웅성임)
    const murmur = ctx.createGain();
    const voices = filter("bandpass", 650, 0.9);
    chain(loop(noise.pink), voices, murmur, layerGain("crowd"));
    wobble(murmur.gain, 0.7, 0.3, 0.4);
    wobble(voices.frequency, 650, 150, 0.23);

    // 차량: 멀리서 들리는 낮은 웅웅거림 (지나가는 차는 scheduler)
    chain(loop(noise.brown), filter("lowpass", 250), layerGain("traffic"));

    // 벌레(귀뚜라미): 높은 음을 빠르게 끊고, 다시 한 번 느리게 끊는다
    const chirp = ctx.createOscillator();
    chirp.frequency.value = 4400;
    const fast = ctx.createGain();
    const slow = ctx.createGain();
    chain(chirp, fast, slow, layerGain("insects"));
    wobble(fast.gain, 0.5, 0.5, 28, "square");
    wobble(slow.gain, 0.5, 0.5, 0.9, "square");
    chirp.start();

    layerGain("birds");
    layerGain("thunder");
  }

  // ---------- 가끔 나는 소리 (확률로 띄엄띄엄) ----------
  function burst(name, { frequency = 1000, type = "bandpass", q = 1, attack = 0.005, hold = 0.02, decay = 0.05,
                         level = 1, kind = "white" } = {}) {
    const now = ctx.currentTime;
    const source = ctx.createBufferSource();
    source.buffer = noise[kind];
    const env = ctx.createGain();
    env.gain.setValueAtTime(0, now);
    env.gain.linearRampToValueAtTime(level, now + attack);
    env.gain.setValueAtTime(level, now + attack + hold);
    env.gain.exponentialRampToValueAtTime(0.0001, now + attack + hold + decay);
    chain(source, filter(type, frequency, q), env, layers[name]);
    source.start(now, Math.random() * 3);
    source.stop(now + attack + hold + decay + 0.05);
  }

  function birdCall() {
    const now = ctx.currentTime;
    const notes = 2 + Math.floor(Math.random() * 4);
    const base = 2200 + Math.random() * 2500;
    for (let i = 0; i < notes; i++) {
      const start = now + i * (0.09 + Math.random() * 0.06);
      const osc = ctx.createOscillator();
      const env = ctx.createGain();
      osc.frequency.setValueAtTime(base * (0.9 + Math.random() * 0.2), start);
      osc.frequency.exponentialRampToValueAtTime(base * (1.2 + Math.random() * 0.4), start + 0.07);
      env.gain.setValueAtTime(0, start);
      env.gain.linearRampToValueAtTime(1, start + 0.01);
      env.gain.exponentialRampToValueAtTime(0.0001, start + 0.08);
      chain(osc, env, layers.birds);
      osc.start(start);
      osc.stop(start + 0.1);
    }
  }

  const occasional = {
    birds: { rate: 0.5, play: birdCall },
    fire: { rate: 6, play: () => burst("fire", { frequency: 2500 + Math.random() * 3000, type: "highpass",
                                                  level: 0.6 + Math.random() * 0.8 }) },
    thunder: { rate: 0.04, play: () => burst("thunder", { frequency: 180, type: "lowpass", kind: "brown",
                                                          attack: 0.15, hold: 0.4, decay: 3.5, level: 1 }) },
    traffic: { rate: 0.12, play: () => burst("traffic", { frequency: 500, q: 0.6, kind: "pink",
                                                          attack: 1.5, hold: 0.3, decay: 2, level: 0.8 }) },
  };

  function tick() {
    if (!ctx || ctx.state !== "running") return;
    for (const [name, spec] of Object.entries(occasional)) {
      const level = target.layers[name] || 0;
      if (level > 0 && Math.random() < spec.rate * 0.25 * Math.min(1, level * 1.5)) spec.play();
    }
  }

  // ---------- 사건 효과음 (이번 턴에 일어난 중요한 일) ----------
  const NOTE = (name) => {   // "C5" → 주파수
    const steps = { C: -9, D: -7, E: -5, F: -4, G: -2, A: 0, B: 2 }[name[0]];
    const sharp = name[1] === "#" ? 1 : 0;
    const octave = Number(name.slice(sharp ? 2 : 1));
    return 440 * Math.pow(2, (steps + sharp + (octave - 4) * 12) / 12);
  };

  function tone(at, frequency, { type = "sine", length = 0.3, level = 0.5, attack = 0.01, glide = null,
                                 cutoff = null } = {}) {
    const osc = ctx.createOscillator();
    osc.type = type;
    osc.frequency.setValueAtTime(frequency, at);
    if (glide) osc.frequency.exponentialRampToValueAtTime(glide, at + length);
    const env = ctx.createGain();
    env.gain.setValueAtTime(0.0001, at);
    env.gain.exponentialRampToValueAtTime(level, at + attack);
    env.gain.exponentialRampToValueAtTime(0.0001, at + length);
    if (cutoff) chain(osc, filter("lowpass", cutoff), env, sfxBus);
    else chain(osc, env, sfxBus);
    osc.start(at);
    osc.stop(at + length + 0.05);
  }

  function sweep(at, from, peak, to, length, level = 0.5) {   // 바람 가르는 소리 (이동)
    const source = ctx.createBufferSource();
    source.buffer = noise.pink;
    const band = filter("bandpass", from, 1.2);
    band.frequency.setValueAtTime(from, at);
    band.frequency.exponentialRampToValueAtTime(peak, at + length * 0.45);
    band.frequency.exponentialRampToValueAtTime(to, at + length);
    const env = ctx.createGain();
    env.gain.setValueAtTime(0.0001, at);
    env.gain.exponentialRampToValueAtTime(level, at + length * 0.45);
    env.gain.exponentialRampToValueAtTime(0.0001, at + length);
    chain(source, band, env, sfxBus);
    source.start(at, Math.random() * 2);
    source.stop(at + length + 0.05);
  }

  function thump(at, level = 0.9) {   // 낮은 북소리 (위험)
    tone(at, 120, { length: 0.5, level, glide: 40 });
    const source = ctx.createBufferSource();
    source.buffer = noise.brown;
    const env = ctx.createGain();
    env.gain.setValueAtTime(0.0001, at);
    env.gain.exponentialRampToValueAtTime(level * 0.6, at + 0.01);
    env.gain.exponentialRampToValueAtTime(0.0001, at + 0.35);
    chain(source, filter("lowpass", 200), env, sfxBus);
    source.start(at);
    source.stop(at + 0.4);
  }

  const notes = (at, names, gap, options) => names.forEach((n, i) => tone(at + i * gap, NOTE(n), options));

  const SFX = {
    offer: (t) => notes(t, ["C6", "E6", "G6", "C7"], 0.1, { length: 0.9, level: 0.25 }),
    success: (t) => notes(t, ["G5", "C6"], 0.12, { type: "triangle", length: 0.45, level: 0.35 }),
    fail: (t) => notes(t, ["E4", "C4"], 0.18, { type: "square", length: 0.45, level: 0.12, cutoff: 1500 }),
    danger: (t) => { thump(t); thump(t + 0.32, 0.7); tone(t + 0.05, NOTE("C#3"), { type: "sawtooth", length: 1.2,
                                                                                   level: 0.08, cutoff: 600 }); },
    clue: (t) => { tone(t, NOTE("E6"), { length: 0.35, level: 0.25 }); tone(t + 0.22, NOTE("E6"), { length: 0.35, level: 0.1 }); },
    discover: (t) => notes(t, ["D5", "F#5", "A5"], 0.1, { type: "triangle", length: 0.5, level: 0.3 }),
    lucky: (t) => notes(t, ["E6", "G#6", "B6", "E7", "B6"], 0.06, { length: 0.4, level: 0.15 }),
    travel: (t) => sweep(t, 250, 2200, 500, 1.3, 0.6),
    engine: (t) => { tone(t, 45, { type: "sawtooth", length: 0.9, level: 0.25, glide: 90, cutoff: 400, attack: 0.05 }); },
    ticket: (t) => { tone(t, 2093, { length: 0.25, level: 0.2 }); tone(t + 0.1, 2637, { length: 0.4, level: 0.2 }); },
    arrest: (t) => { for (let i = 0; i < 4; i++) tone(t + i * 0.35, i % 2 ? 960 : 720, { type: "triangle", length: 0.34,
                                                                                         level: 0.2, attack: 0.03 }); },
    dismiss: (t) => tone(t, 330, { type: "triangle", length: 0.35, level: 0.2, glide: 220 }),
    win: (t) => { notes(t, ["C5", "E5", "G5"], 0.14, { type: "triangle", length: 0.4, level: 0.3 });
                  ["C5", "E5", "G5", "C6"].forEach((n) => tone(t + 0.45, NOTE(n), { type: "triangle", length: 1.8, level: 0.18 })); },
    death: (t) => ["A3", "C4", "E4"].forEach((n, i) => tone(t + i * 0.25, NOTE(n), { length: 2.6, level: 0.18,
                                                                                    attack: 0.2, cutoff: 900 })),
  };

  function playSfx(events) {
    if (!ctx || ctx.state !== "running" || !prefs.on) return;
    let at = ctx.currentTime + 0.05;
    for (const name of events) {
      if (!SFX[name]) continue;
      SFX[name](at);
      at += 0.6;   // 여러 개면 차례로
    }
  }

  // ---------- 적용 ----------
  function applyTarget(smooth = 1.0) {
    if (!ctx) return;
    const now = ctx.currentTime;
    for (const name of LAYERS) {
      const level = (target.layers[name] || 0) * SCALE[name];
      layers[name].gain.setTargetAtTime(level, now, smooth);
    }
    muffle.frequency.setTargetAtTime(target.indoor ? 900 : 18000, now, smooth);
  }

  function setMaster() {
    if (!master) return;
    master.gain.setTargetAtTime(prefs.on ? prefs.volume : 0, ctx.currentTime, 0.2);
  }

  function start() {
    if (!prefs.on) return;
    if (!ctx) {
      const Context = window.AudioContext || window.webkitAudioContext;
      if (!Context) return;
      ctx = new Context();
      master = ctx.createGain();
      master.gain.value = 0;
      muffle = filter("lowpass", 18000);
      chain(muffle, master, ctx.destination);
      sfxBus = ctx.createGain();   // 효과음은 실내에서도 먹먹해지지 않는다
      chain(sfxBus, master);
      noise = { white: makeNoise("white"), pink: makeNoise("pink"), brown: makeNoise("brown") };
      buildContinuous();
      setInterval(tick, 250);
      applyTarget(0.5);
      setMaster();
    }
    if (ctx.state === "suspended") ctx.resume();
  }

  function readCue() {
    const nodes = document.querySelectorAll("#rs-sound-cue");
    if (!nodes.length) return;
    let cue;
    try { cue = JSON.parse(nodes[nodes.length - 1].dataset.cue || "{}"); } catch (e) { return; }
    if (cue.sfx && cue.sfx.nonce !== lastNonce) {
      const first = lastNonce === null;   // 페이지를 연 직후 이미 화면에 있던 신호는 지난 일이다
      lastNonce = cue.sfx.nonce;
      if (!first) playSfx(cue.sfx.events || []);
    }
    if (!cue.layers || cue.key === lastKey) return;
    lastKey = cue.key;
    target = cue;
    applyTarget();
  }

  // ---------- 화면: 소리 켜기/끄기, 크기 ----------
  function buildControls() {
    if (document.getElementById("rs-sound-controls")) return;
    const box = document.createElement("div");
    box.id = "rs-sound-controls";
    box.innerHTML =
      '<button type="button" aria-label="배경 소리 켜기/끄기"></button>' +
      '<input type="range" min="0" max="1" step="0.05" aria-label="배경 소리 크기">';
    const button = box.querySelector("button");
    const slider = box.querySelector("input");
    const refresh = () => {
      button.textContent = prefs.on ? "🔊 소리" : "🔇 소리";
      button.setAttribute("aria-pressed", String(prefs.on));
      slider.value = prefs.volume;
      slider.disabled = !prefs.on;
    };
    button.addEventListener("click", () => {
      prefs.on = !prefs.on;
      savePrefs();
      if (prefs.on) start();
      setMaster();
      refresh();
    });
    slider.addEventListener("input", () => {
      prefs.volume = Number(slider.value);
      savePrefs();
      setMaster();
    });
    refresh();
    document.body.appendChild(box);
  }

  function init() {
    buildControls();
    readCue();
    new MutationObserver(readCue).observe(document.body, {
      subtree: true, childList: true, attributes: true, attributeFilter: ["data-cue"],
    });
    // 브라우저 정책: 첫 클릭·키 입력 뒤에만 소리를 낼 수 있다
    for (const type of ["pointerdown", "keydown"]) document.addEventListener(type, start, { capture: true });
    // 다른 탭으로 가면 멈추고 돌아오면 다시 켠다 (그동안의 효과음이 한꺼번에 터지지 않게)
    document.addEventListener("visibilitychange", () => {
      if (!ctx) return;
      if (document.hidden) ctx.suspend();
      else if (prefs.on) ctx.resume();
    });
  }

  window.rsSound = {
    apply: (cue) => { target = cue; applyTarget(); },
    prefs,
    // 지금 층별 목표 크기 (확인·디버깅용)
    levels: () => Object.fromEntries(LAYERS.map((name) => [name, layers[name] ? layers[name].gain.value : null])),
    running: () => Boolean(ctx) && ctx.state === "running",
    play: (events) => playSfx(events),   // 효과음 미리 듣기·확인용
    effects: Object.keys(SFX),
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
