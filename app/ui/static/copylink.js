/* 제주 농돈 - 링크 복사하기(결과 화면 자세히 보기 · 지원 안내 화면 공용). 누르면 data-copy-url 의 공식 원문 주소를 복사하고,
   단추 옆 .lk-done 에 "복사했어요. 카카오톡이나 문자에 붙여 넣으세요"를 4초 보인다(aria-live). 복사가 안 되면 주소가 든 입력칸(.lk-fallback)을 보여 주고 전체 선택한다. */
(function () {
  "use strict";
  var SHOW_MS = 4000;
  var timers = new WeakMap();

  function wrapOf(btn) { return btn.closest(".lk, .sp-link") || btn.parentElement; }

  function say(wrap, text) {
    var done = wrap.querySelector(".lk-done");
    if (!done) return;
    done.textContent = text || done.getAttribute("data-msg") || "";
    clearTimeout(timers.get(done));
    timers.set(done, setTimeout(function () { done.textContent = ""; }, SHOW_MS));
  }

  function showInput(wrap, url) {
    var inp = wrap.querySelector(".lk-fallback");
    if (!inp) return false;
    inp.value = url;
    inp.hidden = false;
    inp.focus();
    inp.select();
    try { inp.setSelectionRange(0, url.length); } catch (e) { /* 일부 브라우저는 읽기 전용 칸에서 막는다 */ }
    var ok = false;
    try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
    return ok;
  }

  function copied(wrap) {
    var inp = wrap.querySelector(".lk-fallback");
    if (inp) inp.hidden = true;
    say(wrap);
  }

  /* 클립보드를 쓸 수 없을 때: 주소 입력칸을 보여 주고 전체 선택한다. 복사가 됐다고 확인될 때만 "복사했어요"를 말하고, 입력칸은 그대로 둔다(눈으로 확인할 수 있게). */
  function manual(wrap, url) {
    if (showInput(wrap, url)) say(wrap);
    else say(wrap, "주소가 선택됐어요. 길게 눌러 복사하세요");
  }

  document.addEventListener("click", function (ev) {
    var btn = ev.target.closest && ev.target.closest(".lk-copy");
    if (!btn) return;
    ev.preventDefault();
    var url = btn.getAttribute("data-copy-url") || "";
    var wrap = wrapOf(btn);
    if (!url) return;
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(url).then(function () { copied(wrap); }, function () { manual(wrap, url); });
    } else {
      manual(wrap, url);
    }
  });
})();
