/* 확인 화면: 소농·면적직불 카드를 누르면 "올해 직불 교육을 들으셨어요?" 두 단추가 나온다(스크립트가 꺼져 있으면 늘 보인다). */
(function () {
  "use strict";
  /* 아무것도 안 눌렀으면 단추 글이 "받은 것 없어요, 결과 보기"로 바뀐다(눌렀으면 "결과 보기") */
  var form = document.querySelector("form.cform");
  var none = document.querySelector("[data-lab-none]"), some = document.querySelector("[data-lab-some]");
  function label() {
    if (!form || !none || !some) return;
    var any = form.querySelector("input[type=checkbox]:checked, input[type=radio]:checked");
    none.hidden = !!any;
    some.hidden = !any;
    /* 고른 개수를 아래 띠에 작게 알린다(화면 읽기 프로그램에도: aria-live) */
    var count = document.querySelector("[data-count]");
    if (count) {
      var n = form.querySelectorAll("input[type=checkbox]:checked").length;
      count.textContent = n ? n + "가지 골랐어요" : "고른 것이 없어요";
    }
  }
  if (form) { form.addEventListener("change", label); window.addEventListener("pageshow", label); label(); }
  /* Tab 으로 칸에 오면 브라우저가 칸을 화면 안에 있다고 보고 그대로 둬, 아래 붙박이 띠 밑에 가려질 수 있다. 가려지면 띠 위로 올려 보인다 */
  var bar = document.querySelector(".actionbar");
  if (form && bar) form.addEventListener("focusin", function (e) {
    var t = e.target;
    if (!t || t.name === undefined || !t.closest) return;
    var box = t.closest(".choice") || t;
    var over = box.getBoundingClientRect().bottom - bar.getBoundingClientRect().top;
    if (over > 0) window.scrollBy(0, over + 16);
  });
  var home = document.querySelector("[data-home-c]");
  if (home) home.addEventListener("click", function (e) { if (!window.confirm("지금까지 한 답을 지우고 처음으로 갈까요?")) e.preventDefault(); });
  var edu = document.querySelector("[data-edu]");
  if (!edu) return;
  var boxes = document.querySelectorAll("input[data-direct]");
  function update() {
    var on = false;
    for (var i = 0; i < boxes.length; i++) if (boxes[i].checked) on = true;
    edu.classList.toggle("is-on", on);
  }
  for (var i = 0; i < boxes.length; i++) boxes[i].addEventListener("change", update);
  window.addEventListener("pageshow", update);
  update();
})();
