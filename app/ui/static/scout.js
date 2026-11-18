/* 제주 농돈 - 새 공고 찾아보기 진행 화면: 2.5초마다 상태를 받아 글자만 바꾸고, 끝나면 결과 화면으로 다시 불러온다. */
(function () {
  "use strict";
  var box = document.querySelector("[data-status-url]");
  if (!box) return;
  var url = box.getAttribute("data-status-url");
  function set(id, text) { var el = document.getElementById(id); if (el && el.textContent !== String(text)) el.textContent = text; }
  function poll() {
    fetch(url, { cache: "no-store", credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (j.state && j.state !== "run") { location.reload(); return; }
        set("sc-stage", j.stage || "");
        set("sc-seen", j.seen || 0);
        set("sc-picked", j.picked || 0);
        set("sc-time", j.elapsed_s || 0);
        setTimeout(poll, 2500);
      })
      .catch(function () { setTimeout(poll, 4000); });
  }
  setTimeout(poll, 2500);
})();
