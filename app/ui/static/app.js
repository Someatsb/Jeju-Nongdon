/* 제주 농돈 - 공용 화면 스크립트(외부 라이브러리 없음). 쓰는 법은 templates/_ui.html 맨 위 주석.
   소리로 듣기 · 화면 숫자판 · 두 번 누름 방지 · 진행 표시 갱신. 스크립트가 꺼져 있어도 화면은 그대로 쓸 수 있다. */
(function () {
  "use strict";

  /* ---------- 소리로 듣기 ---------- */
  var synth = window.speechSynthesis;
  function koVoice() {
    if (!synth || !synth.getVoices) return null;
    var vs = synth.getVoices();
    for (var i = 0; i < vs.length; i++) if (/^ko/i.test(vs[i].lang)) return vs[i];
    return null;
  }
  function speakText(btn) {
    var t = btn.getAttribute("data-speak");
    var sel = btn.getAttribute("data-speak-from");
    if (!t && sel) { var el = document.querySelector(sel); t = el ? el.textContent : ""; }
    return (t || "").replace(/\s+/g, " ").trim();
  }
  function refreshSpeak() {
    var v = koVoice();
    var btns = document.querySelectorAll("[data-speak]");
    for (var i = 0; i < btns.length; i++) btns[i].hidden = !v;
  }
  function onSpeakClick(btn) {
    var v = koVoice();
    if (!v) return;
    if (btn.classList.contains("speaking")) { synth.cancel(); return; }
    synth.cancel();
    var text = speakText(btn);
    if (!text) return;
    var u = new SpeechSynthesisUtterance(text);
    u.lang = v.lang; u.voice = v; u.rate = 0.9;
    var off = function () { btn.classList.remove("speaking"); };
    u.onend = off; u.onerror = off;
    btn.classList.add("speaking");
    synth.speak(u);
  }
  if (synth) {
    refreshSpeak();
    if (synth.addEventListener) synth.addEventListener("voiceschanged", refreshSpeak);
    else synth.onvoiceschanged = refreshSpeak;
    window.addEventListener("pagehide", function () { synth.cancel(); });
  }

  /* ---------- 화면 숫자판 ---------- */
  var pad = null, cur = null, openedAt = 0;
  function padEl() {
    pad = pad || document.getElementById("numpad");
    return pad;
  }
  function fire(el) { el.dispatchEvent(new Event("input", { bubbles: true })); }
  function showValue() {
    /* 숫자판 안에는 따로 입력 표시를 두지 않는다(위의 칸이 곧 입력 표시) */
  }
  function openPad(input) {
    var p = padEl(); if (!p) return;
    cur = input;
    openedAt = Date.now();   /* 숫자판이 뜨면 화면 높이가 줄어 칸이 움직인다: 그 클릭이 바깥 눌림으로 읽혀 닫히지 않게 */
    p.hidden = false;
    document.body.classList.add("numpad-open");
    p.querySelector("[data-numpad-title]").textContent = (input.getAttribute("data-numpad-label") || "") + " · 숫자를 눌러 주세요";
    showValue();
    document.body.style.setProperty("--numpad-h", p.offsetHeight + "px");
    /* 숫자판이 칸을 가리면 칸이 보이게 올린다 */
    var r = input.getBoundingClientRect(), ph = p.offsetHeight;
    if (r.bottom > window.innerHeight - ph - 8) window.scrollBy(0, r.bottom - (window.innerHeight - ph - 8));
    /* 질문 부분이 따로 스크롤되는 좁은 창: 칸이 보이는 곳으로 */
    try { input.scrollIntoView({ block: "center" }); } catch (err) { /* 옛 브라우저 */ }
  }
  function closePad() {
    var p = padEl(); if (!p) return;
    p.hidden = true; cur = null;
    document.body.classList.remove("numpad-open");
    document.body.style.removeProperty("--numpad-h");
  }
  function press(key) {
    if (!cur) return;
    var max = parseInt(cur.getAttribute("data-maxlen") || "9", 10);
    if (key === "ok") { var done = cur; closePad(); done.dispatchEvent(new CustomEvent("numpad-done", { bubbles: true })); return; }
    if (key === "back") cur.value = cur.value.slice(0, -1);
    else if (cur.value.length < max) cur.value += key;
    showValue(); fire(cur);
  }
  document.addEventListener("focusin", function (e) {
    if (e.target && e.target.matches && e.target.matches("[data-numpad]")) openPad(e.target);
  });
  document.addEventListener("click", function (e) {
    var t = e.target;
    if (!t || !t.closest) return;
    var f = t.closest("[data-numpad]");
    if (f) { if (cur !== f) openPad(f); return; }
    var k = t.closest(".numkey");
    if (k) { press(k.getAttribute("data-key")); return; }
    var sp = t.closest("[data-speak]");
    if (sp) { onSpeakClick(sp); return; }
    if (cur && !t.closest("#numpad") && Date.now() - openedAt > 700) closePad();
  });
  /* 숫자판 단추를 눌러도 칸의 입력 초점이 빠지지 않게 */
  document.addEventListener("mousedown", function (e) {
    if (e.target.closest && e.target.closest("#numpad")) e.preventDefault();
  });
  document.addEventListener("keydown", function (e) {
    if (!cur) return;
    if (e.key === "Escape" || e.key === "Enter") { closePad(); if (e.key === "Enter") e.preventDefault(); }
  });
  document.addEventListener("input", function (e) {
    var t = e.target;
    if (t && t.matches && t.matches("[data-numpad]")) {
      var v = t.value.replace(/[^0-9]/g, "");
      if (v !== t.value) t.value = v;
      if (t === cur) showValue();
    }
  });

  /* ---------- 제출 두 번 누름 방지 ---------- */
  document.addEventListener("submit", function (e) {
    var f = e.target;
    if (!f || !f.hasAttribute || !f.hasAttribute("data-once")) return;
    if (e.defaultPrevented) return;
    if (f.getAttribute("data-submitted") === "1") { e.preventDefault(); return; }
    f.setAttribute("data-submitted", "1");
    var bs = f.querySelectorAll("[data-submit]");
    for (var i = 0; i < bs.length; i++) { bs[i].classList.add("is-busy"); bs[i].setAttribute("aria-disabled", "true"); }
  });
  window.addEventListener("pageshow", function (e) {
    var fs = document.querySelectorAll("form[data-submitted]");
    for (var i = 0; i < fs.length; i++) {
      fs[i].removeAttribute("data-submitted");
      var bs = fs[i].querySelectorAll("[data-submit]");
      for (var j = 0; j < bs.length; j++) { bs[j].classList.remove("is-busy"); bs[j].removeAttribute("aria-disabled"); }
    }
    if (e.persisted) refreshSpeak();
  });

  /* ---------- 로고를 길게 누르면 직원 메뉴(어르신 화면에는 직원 메뉴 링크를 두지 않는다) ---------- */
  var holdT = null, held = false;
  document.addEventListener("pointerdown", function (e) {
    var b = e.target.closest && e.target.closest(".brand");
    if (!b) return;
    held = false;
    holdT = setTimeout(function () { held = true; window.location.href = "/staff"; }, 1800);
  });
  ["pointerup", "pointercancel", "pointerleave"].forEach(function (t) {
    document.addEventListener(t, function () { if (holdT) { clearTimeout(holdT); holdT = null; } });
  });

  /* ---------- 진행 표시 · 오류 말풍선 (단계 화면이 쓴다) ---------- */
  window.NongdonUI = {
    setProgress: function (el, n, text) {
      var total = parseInt(el.getAttribute("data-total"), 10);
      var segs = el.querySelectorAll(".seg");
      for (var i = 0; i < segs.length; i++) {
        segs[i].classList.toggle("on", !!text || i + 1 < n);
        segs[i].classList.toggle("now", !text && i + 1 === n);
      }
      var lab = el.querySelector("[data-progress-label]");
      if (lab) { if (text) lab.textContent = text; else lab.innerHTML = total + "개 중 <b>" + n + "번째</b>"; }
      el.setAttribute("aria-label", text || (total + "개 중 " + n + "번째"));
    },
    closePad: closePad,
    showHint: function (id) { var h = document.getElementById(id); if (h) h.hidden = false; },
    hideHint: function (id) { var h = document.getElementById(id); if (h) h.hidden = true; }
  };
})();
