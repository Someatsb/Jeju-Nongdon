/* 결과 화면: "자세히 보기" 덮개 · 종이 크게 보기 덮개 · 문자 안내 덮개, "종이로 뽑기"를 누른 뒤 돌아오면 "종이가 나왔습니다" 안내를 띄운다.
   스크립트가 꺼져 있으면 "자세히 보기"는 화면 맨 아래 내용으로 가는 링크로 남는다(종이로 뽑기도 그대로 링크). */
(function () {
  "use strict";
  /* AI 글 자리와 지금 접수 중인 공고 자리: 결과는 먼저 떠 있고, 설명 글(AI)과 새 공고 맞춰 보기는 뒤에서 따로 끝난다. 둘 중 하나라도 도는 중이면 1초마다 /counsel/ai 에 물어
     다 되는 대로 자리(data-ai-slot)마다 채운다. 응답은 {state: run|done|failed, fragments: {묶음 이름: 조각}, match: {state: run|done|none, lines, more_names},
     match_html: {new_notices, match_alert, match_links}(맞춰 보기가 끝난 뒤에만)}. 설명 글이 끝나도 맞춰 보기가 도는 동안은 계속 묻는다. 어르신 화면에 오류 말은 없다.
     조각은 서버가 이스케이프해서 만든 HTML 이고, 스크립트가 직접 만드는 글(화면 읽기 알림)은 textContent 로만 쓴다. */
  var aiEl = document.getElementById("ai-state");
  var aiRun = !!aiEl && aiEl.getAttribute("data-ai") === "run";
  var matchRun = !!aiEl && aiEl.getAttribute("data-match") === "run";
  var aiWaiters = [], aiWait = document.getElementById("ai-wait"), aiTimer = null, aiTries = 0, AI_GIVE_UP = 46;     /* 서버 인쇄 길이 45초까지만 기다리므로 화면도 그만큼 */
  var matchTries = 0, MATCH_GIVE_UP = 62;                                                                          /* 맞춰 보기 마지막 한도(서버 40초)보다 조금 더 */
  function busy() { return aiRun || matchRun; }
  function aiFill(frag) {
    Object.keys(frag || {}).forEach(function (name) {
      var val = frag[name] || "";
      if (name === "speak") {
        var sp = document.querySelector(".btn-speak[data-speak]");
        if (sp && val) sp.setAttribute("data-speak", val);
        return;
      }
      var el = document.querySelector('[data-ai-slot="' + name + '"]');
      if (!el) return;
      if (name === "sub") { el.classList.remove("rb-pending"); el.textContent = val; el.hidden = !val; return; }
      el.innerHTML = val;
    });
  }
  function settled() {      /* 둘 다 끝났으면 멈추고, 끝나기를 기다리던 일(종이 열기)을 부른다 */
    if (busy()) return;
    if (aiTimer) { clearInterval(aiTimer); aiTimer = null; }
    var w = aiWaiters; aiWaiters = [];
    w.forEach(function (f) { try { f(); } catch (e) { /* 하나가 실패해도 나머지는 간다 */ } });
  }
  function aiSettle(frag) {
    aiRun = false;
    if (aiEl) aiEl.setAttribute("data-ai", "done");
    aiFill(frag);
    settled();
  }
  /* 지금 접수 중인 공고: 끝난 결과로 상자·알림 줄·공고 원문 줄을 채우고, 맞을 수 있는 공고가 있으면 화면 읽기 프로그램에 알린다 */
  function zoneCount() {      /* 지금 하실 일 제목·위 띠의 곳 수: 가실 곳 상자와 지금 접수 중인 공고 상자를 함께 센다 */
    var z = document.getElementById("now");
    if (!z) return;
    var n = z.querySelectorAll("article.bx").length, h = z.querySelector(".zn-h"), t = z.querySelector(".zn-n"), b = document.querySelector(".rb-n");
    if (t && !n) t.parentNode.removeChild(t);
    else if (n && !t && h) { t = document.createElement("span"); t.className = "zn-n"; h.appendChild(t); }
    if (t && n) t.textContent = " " + n + "곳";
    var none = z.querySelector(".zn-none");
    if (none) none.hidden = n > 0;
    if (b) { b.textContent = n ? "지금 가실 곳은 " + n + "곳이에요" : "지금 바로 하실 일은 없어요"; b.classList.toggle("is-none", !n); }
  }
  function matchFill(html) {
    html = html || {};
    var box = document.querySelector('[data-ai-slot="new_notices"]');
    if (box) { box.innerHTML = html.new_notices || ""; box.hidden = !box.innerHTML.trim(); }
    zoneCount();
    var al = document.querySelector('[data-ai-slot="match_alert"]');
    if (al) al.innerHTML = html.match_alert || "";
    var lk = document.querySelector('[data-ai-slot="match_links"]');
    if (lk) {
      lk.innerHTML = html.match_links || "";
      var lb = lk.closest(".lk-box");
      if (lb) lb.hidden = !lb.querySelector("li.lk");
    }
  }
  function matchStaff() {     /* 직원이 볼 내용 칸은 어르신용 응답과 떼어 두었으므로 따로 한 번 받아 채운다 */
    var slot = document.querySelector("[data-match-staff]");
    if (!slot) return;
    fetch("/counsel/match-staff", { credentials: "same-origin", cache: "no-store" }).then(function (r) { return r.json(); }).then(function (j) {
      slot.innerHTML = j.html || "";
    }).catch(function () { slot.textContent = ""; });
  }
  function matchSettle(j) {
    matchRun = false;
    var m = j.match || {};
    if (aiEl) aiEl.setAttribute("data-match", m.state || "none");
    matchFill(j.match_html);
    var n = (m.lines || []).length, live = document.getElementById("nn-live");
    if (live && n > 0) live.textContent = "지금 접수 중인 공고 " + n + "개가 맞을 수 있어요";
    matchStaff();
    settled();
  }
  function matchGiveUp() {    /* 끝내 안 끝나면 조용히 접는다(오류 말 없음) */
    matchRun = false;
    if (aiEl) aiEl.setAttribute("data-match", "none");
    matchFill({});
    var slot = document.querySelector("[data-match-staff]");
    if (slot) slot.textContent = "";
    settled();
  }
  function aiPoll() {
    aiTries++; matchTries++;
    fetch("/counsel/ai", { credentials: "same-origin", cache: "no-store" }).then(function (r) { return r.json(); }).then(function (j) {
      if (aiRun) {
        if (j.state !== "run") aiSettle(j.fragments);
        else if (aiTries >= AI_GIVE_UP) aiSettle({ sub: "", detail_ai: "", staff: "" });
      }
      if (matchRun) {
        if (j.match && j.match.state && j.match.state !== "run") matchSettle(j);
        else if (matchTries >= MATCH_GIVE_UP) matchGiveUp();
      }
    }).catch(function () {
      if (aiRun && aiTries >= AI_GIVE_UP) aiSettle({ sub: "", detail_ai: "", staff: "" });
      if (matchRun && matchTries >= MATCH_GIVE_UP) matchGiveUp();
    });
  }
  if (busy()) { aiTimer = setInterval(aiPoll, 1000); setTimeout(aiPoll, 250); }
  /* 설명 글과 새 공고 맞춰 보기가 다 되면 f 를 부른다(이미 됐으면 바로) */
  function aiReady(f) { if (!busy()) f(); else aiWaiters.push(f); }
  function aiWaitShow(on) {
    if (!aiWait) return;
    aiWait.hidden = !on;
    if (on) { var c = aiWait.querySelector("[data-ai-wait-close]"); if (c) c.focus(); }
  }
  var aiCancelled = null;       /* 덮개를 닫으면 기다리던 일(종이 열기)을 그만둔다 */
  document.addEventListener("click", function (e) {
    if (e.target.closest && e.target.closest("[data-ai-wait-close]")) { if (aiCancelled) aiCancelled(); aiWaitShow(false); }
  });
  /* 자세히 보기: 같은 화면 위 덮개(올해는 어려운 것 · 창구 확인 · 쉬운 말 설명 · 종이 크게 보기 · 직원이 볼 내용) */
  var dt = document.getElementById("detail"), dtOpen = document.getElementById("dt-open");
  function dtShow() {
    if (!dt) return;
    dt.classList.add("open");
    document.body.classList.add("dt-open");
    var body = dt.querySelector(".dt-body");
    if (body) body.scrollTop = 0;
    var c = dt.querySelector("[data-dt-close]");
    if (c) c.focus();
  }
  function dtHide() {
    if (!dt || !dt.classList.contains("open")) return;
    dt.classList.remove("open");
    document.body.classList.remove("dt-open");
    if (dtOpen) dtOpen.focus();
  }
  document.addEventListener("click", function (e) {
    var o = e.target.closest && e.target.closest("[data-dt-open]");
    if (o) { e.preventDefault(); dtShow(); return; }
    if (e.target.closest && e.target.closest("[data-dt-close]")) dtHide();
  });

  /* 종이 크게 보기: 같은 화면 위에 덮개로 연다(새 창이 아니라서 돌아오는 길을 잃지 않는다) */
  var modal = document.getElementById("pv-modal"), mframe = document.getElementById("pv-modal-frame");
  function openModal(which) {
    if (!modal || !mframe) return;
    modal.hidden = false;
    document.body.classList.add("pv-open");
    mframe.onload = function () {
      try {
        var doc = mframe.contentDocument, el = doc && doc.querySelector('[data-page="' + which + '"]');
        if (el) doc.scrollingElement.scrollTop = el.getBoundingClientRect().top + doc.scrollingElement.scrollTop - 12;
      } catch (e) { /* 못 읽으면 그대로 */ }
    };
    mframe.src = mframe.getAttribute("data-src") || "/counsel/preview?view=screen";
    var c = modal.querySelector("[data-pv-close]");
    if (c) c.focus();
  }
  function closeModal() {
    if (!modal) return;
    modal.hidden = true;
    document.body.classList.remove("pv-open");
  }
  document.addEventListener("click", function (e) {
    var o = e.target.closest && e.target.closest("[data-pv-open]");
    if (o) {
      var which = o.getAttribute("data-pv-open");
      if (!busy()) { openModal(which); return; }
      var cancelled = false;                       /* 종이에 AI 글이 들어가므로 다 될 때까지 "종이를 준비하고 있어요"를 보이고, 되면 연다 */
      aiCancelled = function () { cancelled = true; };
      aiWaitShow(true);
      aiReady(function () { if (cancelled) return; aiWaitShow(false); openModal(which); });
      return;
    }
    if (e.target.closest && e.target.closest("[data-pv-close]")) closeModal();
  });
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    if (aiWait && !aiWait.hidden) { if (aiCancelled) aiCancelled(); aiWaitShow(false); }
    else if (modal && !modal.hidden) closeModal();
    else if (rm && !rm.hidden) rmClose();
    else dtHide();
  });

  /* 처음으로: 종이를 아직 안 뽑았으면 답이 지워진다고 한 번 물어본다 */
  document.addEventListener("submit", function (e) {
    var msg = e.target.getAttribute && e.target.getAttribute("data-confirm");
    if (msg && !document.body.classList.contains("printed") && !window.confirm(msg)) e.preventDefault();
  }, true);

  /* 마감 전에 문자로 알려 드릴까요?: 같은 화면 위 덮개에서 번호와 동의를 받아 /counsel/reminder 로 보낸다(번호는 저장 파일 밖 어디에도 남지 않는다) */
  var rm = document.getElementById("rm-modal"), rmForm = document.getElementById("rm-form");
  var rmPhone = rmForm && rmForm.elements["reminder_phone"], rmAgree = rmForm && rmForm.elements["reminder_consent"];
  var rmFmt = rm && rm.querySelector("[data-rm-fmt]"), rmSend = document.getElementById("rm-send");
  function rmShow(id, text) { var e = document.getElementById(id); if (!e) return; e.textContent = text || ""; e.hidden = !text; }
  function rmClear() { rmShow("rm-err-phone", ""); rmShow("rm-err-consent", ""); rmShow("rm-err-line", ""); }
  function rmFormat() {
    if (!rmPhone || !rmFmt) return;
    var d = rmPhone.value.replace(/[^0-9]/g, ""), t = d;
    if (d.length > 7) t = d.slice(0, 3) + "-" + d.slice(3, 7) + "-" + d.slice(7);
    else if (d.length > 3) t = d.slice(0, 3) + "-" + d.slice(3);
    rmFmt.textContent = t;
  }
  function rmOpen() {
    if (!rm) return;
    rmClear();
    rm.hidden = false;
    document.body.classList.add("rm-on");
    if (rmSend) { rmSend.disabled = false; rmSend.classList.remove("is-busy"); }
    var c = rm.querySelector("[data-rm-close]");
    if (c) c.focus();
  }
  function rmClose() {
    if (!rm || rm.hidden) return;
    if (window.NongdonUI && window.NongdonUI.closePad) window.NongdonUI.closePad();
    rm.hidden = true;
    document.body.classList.remove("rm-on");
  }
  document.addEventListener("click", function (e) {
    var t = e.target.closest && e.target.closest("[data-rm-open]");
    if (t) { rmOpen(); return; }
    if (e.target.closest && e.target.closest("[data-rm-close]")) rmClose();
  });
  if (rmPhone) rmPhone.addEventListener("input", function () { rmFormat(); rmShow("rm-err-phone", ""); rmShow("rm-err-line", ""); });
  if (rmAgree) rmAgree.addEventListener("change", function () { rmShow("rm-err-consent", ""); });
  /* 저장하고 나면 구역 2의 안내 줄과 문자 알림 단추 글(모든 단추)을 "신청했어요"로 바꾼다: 어디서 눌렀든 눌렀는지 보인다. 상담번호는 직원이 볼 내용 칸에만 */
  function rmDone(j) {
    var labs = document.querySelectorAll(".rm-open .rm-lab");
    for (var i = 0; i < labs.length; i++) labs[i].textContent = "문자 알림 신청했어요";
    var msg = document.querySelector("[data-rm-msg]");
    if (msg && j.line) msg.textContent = j.line;
    var sid = document.querySelector("[data-reminder-sid]");
    if (sid && j.sid) { var b = sid.querySelector("b"); if (b) b.textContent = j.sid; sid.hidden = false; }
  }
  if (rmForm) rmForm.addEventListener("submit", function (e) {
    e.preventDefault();
    if (rmSend && rmSend.disabled) return;
    rmClear();
    if (rmSend) { rmSend.disabled = true; rmSend.classList.add("is-busy"); }
    var body = "reminder_phone=" + encodeURIComponent(rmPhone.value) + (rmAgree && rmAgree.checked ? "&reminder_consent=on" : "");
    fetch("/counsel/reminder", { method: "POST", credentials: "same-origin", cache: "no-store",
                                 headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: body })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (rmSend) { rmSend.disabled = false; rmSend.classList.remove("is-busy"); }
        var er = j.errors || {};
        if (er.reminder_phone || er.reminder_consent) { rmShow("rm-err-phone", er.reminder_phone); rmShow("rm-err-consent", er.reminder_consent); return; }
        if (!j.ok) { rmShow("rm-err-line", j.line || "지금은 저장하지 못했어요. 직원에게 말씀해 주세요."); return; }
        rmPhone.value = ""; rmFormat(); if (rmAgree) rmAgree.checked = false;     /* 번호는 화면에도 남기지 않는다 */
        rmClose();
        var l = document.getElementById("reminder-line");
        if (l) { l.textContent = j.line; l.hidden = !j.line; }
        rmDone(j);
      })
      .catch(function () {
        if (rmSend) { rmSend.disabled = false; rmSend.classList.remove("is-busy"); }
        rmShow("rm-err-line", "연결이 잠깐 끊겼어요. 다시 '알려 주세요'를 눌러 주세요.");
      });
  });

  var line = document.getElementById("reminder-line");
  function refreshLine() {
    if (!line) return;
    fetch("/counsel/reminder-status", { credentials: "same-origin" }).then(function (r) { return r.text(); }).then(function (t) {
      line.textContent = t; line.hidden = !t;
    }).catch(function () {});
  }
  var timer = null;
  function stop() { if (timer) { clearInterval(timer); timer = null; } }
  function printed() {
    document.body.classList.add("printed");
    var a = document.getElementById("after-print");
    if (a) a.hidden = false;
    stop();
    window.scrollTo(0, 0);
  }
  function check() {
    fetch("/counsel/print-status", { credentials: "same-origin", cache: "no-store" }).then(function (r) { return r.text(); }).then(function (t) {
      if (t.trim() === "1") printed();
    }).catch(function () {});
    refreshLine();
  }
  var btn = document.getElementById("print-btn");
  function watchPrint() {
    stop();
    var n = 0;
    timer = setInterval(function () { if (++n > 150) stop(); else check(); }, 2000);
  }
  if (btn) btn.addEventListener("click", function (e) {
    if (!busy()) { watchPrint(); return; }          /* 평소처럼 새 탭이 열린다 */
    /* AI 글이 아직이면 덮개를 보이고, 다 되면 인쇄 화면으로 간다. 새 탭은 지금 열어 두어야(누른 직후) 막히지 않는다 */
    e.preventDefault();
    var win = null, cancelled = false, url = btn.getAttribute("href");
    try {
      win = window.open("", "_blank");
      if (win && win.document) win.document.write('<meta charset="utf-8"><title>종이를 준비하고 있어요</title><p style="font:700 32px sans-serif;padding:48px;text-align:center">종이를 준비하고 있어요. 잠깐만 기다려 주세요.</p>');
    } catch (err) { win = null; }
    aiCancelled = function () { cancelled = true; try { if (win) win.close(); } catch (err) { /* 닫지 못해도 괜찮다 */ } };
    aiWaitShow(true);
    aiReady(function () {
      if (cancelled) return;
      aiWaitShow(false);
      if (win && !win.closed) win.location.href = url; else window.open(url, "_blank");
      watchPrint();
    });
  });
  window.addEventListener("focus", check);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) check(); });
})();
