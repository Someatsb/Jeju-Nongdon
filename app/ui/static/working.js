/* 찾는 중 화면(2026-11-16): 설명 글(AI)과 지금 접수 중인 공고 맞춰 보기가 둘 다 끝날 때까지 기다린 뒤 결과 화면으로 간다(결과 화면이 읽는 중에 두 번 바뀌지 않게).
   /counsel/ai 응답 {state: run|done|failed, match: {state: run|done|none}} 에서 state 와 match.state 가 둘 다 run 이 아니면 끝난 것이다. 가장 짧게 1.4초는 보여 준다(재생 모드는 바로 끝난다).
   30초가 지나도 안 끝나면 있는 것만으로 간다(결과 화면이 뒤늦게 채운다). /counsel/ai 가 오류를 내도 멈추지 않고 간다. 진행 막대는 천천히 차되 끝나기 전에는 다 차지 않고, 지어낸 퍼센트는 없다.
   1.2초가 지나도 안 끝났으면 하는 일 세 줄을 보이고 실제 상태에 따라 체크한다. 넘어가려 한 뒤 8초가 지나도 화면이 안 바뀌면 "직원에게 말씀해 주세요"를 보인다. */
(function () {
  "use strict";
  var bar = document.querySelector("[data-w-bar]");
  var MIN_MS = 1400, REVEAL_MS = 1200, LIMIT_MS = 30000, POLL_MS = 1000, SLOW_MS = 8000;
  var t0 = Date.now(), gone = false, shown = false, timer = null;
  function go() {
    if (gone) return;
    gone = true;
    if (timer) { clearInterval(timer); timer = null; }
    window.location.replace("/counsel/preview");
    setTimeout(function () { var slow = document.querySelector("[data-w-slow]"); if (slow) slow.hidden = false; }, SLOW_MS);
  }
  function fillBar(ms, ease) {
    if (!bar) return;
    bar.style.transition = "width " + (ms / 1000) + "s " + ease;
    bar.style.width = ease === "linear" ? "100%" : "92%";
  }
  function tick(step, done) {
    var li = document.querySelector('[data-w-step="' + step + '"]');
    if (!li) return;
    li.classList.toggle("is-done", !!done);
    var sr = li.querySelector("[data-w-sr]");
    if (sr) sr.textContent = done ? "(끝났어요)" : "(하는 중)";
  }
  function reveal() {
    var more = document.querySelector("[data-w-more]");
    if (more && !shown) { shown = true; more.hidden = false; }
  }
  function finish() {      /* 둘 다 끝났다: 막대를 채우고(최소 MIN_MS 까지 보여 준 뒤) 넘어간다 */
    if (timer) { clearInterval(timer); timer = null; }
    tick("match", true); tick("text", true);
    var wait = Math.max(MIN_MS - (Date.now() - t0), 350);
    fillBar(wait, "linear");
    setTimeout(go, wait + 120);
  }
  function check() {
    if (gone) return;
    var el = Date.now() - t0;
    if (el >= LIMIT_MS) { finish(); return; }
    fetch("/counsel/ai", { credentials: "same-origin", cache: "no-store" }).then(function (r) { return r.json(); }).then(function (j) {
      var textRun = j.state === "run", matchRun = !!(j.match && j.match.state === "run");
      if (!textRun && !matchRun) { finish(); return; }
      if (Date.now() - t0 >= REVEAL_MS) reveal();
      tick("text", !textRun); tick("match", !matchRun);
    }).catch(function () { finish(); });      /* 못 물으면 기다리지 않고 간다(결과 화면이 뒤늦게 채운다) */
  }
  setTimeout(function () { if (!gone) fillBar(LIMIT_MS, "cubic-bezier(.2,.55,.4,1)"); }, 30);
  setTimeout(function () { if (!gone && timer) reveal(); }, REVEAL_MS + 50);
  setTimeout(check, 250);
  timer = setInterval(check, POLL_MS);
})();
