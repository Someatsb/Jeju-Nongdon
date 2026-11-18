/* 제주 농돈 - 질문 화면(input.html) 단계 넘김. 외부 라이브러리 없음.
   스크립트가 꺼져 있으면 모든 단계가 차례로 보이고 제출은 그대로 된다(html.js 클래스가 있을 때만 단계가 한 장씩 보인다). */
(function () {
  "use strict";
  var form = document.getElementById("qform");
  if (!form) return;

  var steps = [].slice.call(form.querySelectorAll(".qstep"));
  var LAST = steps.length - 1;
  var prog = document.querySelector("[data-progress]");
  var nextBtn = document.getElementById("next-btn");
  var prevBtn = form.querySelector(".btn-prev");
  var selfpay = (form.getAttribute("data-selfpay-crops") || "").split(" ");
  var cropNames = {};
  try { cropNames = JSON.parse(form.getAttribute("data-crops") || "{}"); } catch (e) { cropNames = {}; }
  var lo = Number(form.getAttribute("data-small-lo")), hi = Number(form.getAttribute("data-small-hi"));
  var year = Number(form.getAttribute("data-year")) || new Date().getFullYear();
  var cur = Math.max(0, Math.min(LAST, (Number(form.getAttribute("data-start")) || 1) - 1));
  var step2 = steps[1];
  var sub = step2 && step2.classList.contains("is-sub2") ? 2 : 1;   // 2번 질문 안의 화면: 1 첫째 작물, 2 둘째 작물
  function view() { return cur * 10 + (cur === 1 && sub === 2 ? 1 : 0); }   // 브라우저 기록에 남기는 화면 번호
  var qs = [view()], depth = 0;   // 지나온 화면(브라우저 기록 한 칸이 한 화면)

  function $(sel, root) { return (root || form).querySelector(sel); }
  function $$(sel, root) { return [].slice.call((root || form).querySelectorAll(sel)); }
  function val(name) {
    var e = form.elements[name];
    if (!e) return "";
    return (e.value || "").trim();
  }
  function num(name) {
    var v = val(name).replace(/,/g, "");
    return /^[0-9]+$/.test(v) ? Number(v) : null;
  }
  function fire(el, type) { el.dispatchEvent(new Event(type, { bubbles: true })); }
  function setOn(el, on) { if (el) el.classList.toggle("is-on", !!on); }
  function clearRadios(name) {
    $$('input[name="' + name + '"]').forEach(function (r) { r.checked = false; r.setAttribute("data-was", "0"); });
  }

  /* ---------- 단계 보이기 ---------- */
  function show(i, push, subTo) {
    cur = Math.max(0, Math.min(LAST, i));
    sub = cur === 1 && subTo === 2 ? 2 : 1;
    if (step2) step2.classList.toggle("is-sub2", sub === 2);
    if (window.NongdonUI && window.NongdonUI.closePad) window.NongdonUI.closePad();   // 단계가 바뀌면 숫자판은 닫는다
    steps.forEach(function (s, k) { s.classList.toggle("is-current", k === cur); });
    form.classList.toggle("is-last", cur === LAST);
    if (prog && window.NongdonUI) {
      window.NongdonUI.setProgress(prog, cur + 1);
    }
    if (push) {
      depth += 1; qs.length = depth; qs[depth] = view();
      try { history.pushState({ n: depth }, "", location.href); } catch (e) { /* 없어도 된다 */ }
    }
    update();
    if (prevBtn) {
      var t = cur === 0 ? (prevBtn.getAttribute("href") === "/counsel/preview" ? "결과 화면으로" : "처음으로") : "이전";
      var last = prevBtn.lastChild;
      if (last && last.nodeType === 3) last.nodeValue = t;
    }
  }

  function hint(id, on, text) {
    var h = document.getElementById(id);
    if (!h) return;
    if (text) h.textContent = text;
    h.hidden = !on;
  }
  /* 안 고른 칸의 테두리를 깜박여 어디를 눌러야 하는지 보인다 */
  function need(step, on, which) {
    var box = steps[step] && steps[step].querySelector(which ? '[data-need-for="' + which + '"]' : (step === 1 && sub === 2 ? '[data-tiles="crop2_crop_code"]' : "[data-need-box]"));
    if (!box) return;
    box.classList.toggle("is-need", !!on);
  }
  var warned = {};   /* 해를 모르면 넘어가도 되는 칸: 한 번 알려 주고, 다시 누르면 넘어간다 */
  function cityPicked() { return !!$('[data-city-tab].on'); }

  /* 이 단계에서 꼭 필요한 값이 비었으면 칸 옆에 쉬운 말을 보이고 false */
  function stepOk(i) {
    if (i === 0) {
      var ok = !!val("emd_code");
      hint("hint-emd", !ok, cityPicked() ? "사시는 읍·면·동을 눌러 주세요" : "먼저 제주시나 서귀포시를 눌러 주세요");
      need(0, !ok);
      return ok;
    }
    if (i === 1 && sub === 2) {
      var c2 = !!val("crop2_crop_code");
      hint("hint-crop2", !c2);
      need(1, !c2);
      if (c2 && !val("crop2_area_py") && !warned.area2) { warned.area2 = true; hint("hint-area2", true); return false; }
      return c2;
    }
    if (i === 1) {
      var ok2 = !!val("crop1_crop_code");
      hint("hint-crop", !ok2);
      need(1, !ok2);
      if (ok2 && !val("crop1_area_py") && !warned.area) { warned.area = true; hint("hint-area", true); return false; }
      return ok2;
    }
    if (i === 2) {
      var sexOk = !!val("owner_sex");
      hint("hint-sex", !sexOk);
      need(2, !sexOk, "sex");
      if (!sexOk) return false;
      var b = val("birth_year");
      if (b === "") {
        if (!warned.birth) { warned.birth = true; hint("hint-birth", true, "태어난 해를 눌러 주세요. 모르시면 이대로 '다음'을 한 번 더 눌러 주세요"); return false; }
        return true;
      }
      var ok3 = /^[0-9]{4}$/.test(b) && Number(b) >= 1900 && Number(b) <= 2010;
      hint("hint-birth", !ok3, "태어난 해는 네 자리로 눌러 주세요. 예: 1955");
      return ok3;
    }
    if (i === 3) {
      return true;   /* 등록한 해는 글에서 이미 "모르시면 비워 두세요"라고 했으므로 비워도 바로 넘어간다 */
    }
    return true;
  }

  /* 마지막 화면: 햇수·배우자·거주를 안 눌렀으면 한 번 알려 준다(다시 누르면 그대로 간다) */
  function mustOk() {
    var groups = $$("[data-must]");
    var missing = groups.filter(function (g) { return !$("input:checked", g); });
    groups.forEach(function (g) { g.classList.toggle("is-need", missing.indexOf(g) >= 0); });
    if (missing.length && !warned.must) { warned.must = true; hint("hint-must", true); return false; }
    hint("hint-must", false);
    return true;
  }

  function next() {
    if (!stepOk(cur)) return;
    if (cur < LAST) show(cur + 1, true);
  }
  function prev() {
    if (cur === 1 && sub === 2) {            // 둘째 작물 화면에서는 첫째 작물 화면으로
      if (depth > 0 && qs[depth - 1] === 10) history.back(); else show(1, true, 1);
    } else if (cur > 0) {
      if (depth > 0 && qs[depth - 1] === (cur - 1) * 10) history.back();   // 방금 지나온 화면이면 기록도 한 칸 뒤로
      else show(cur - 1, true);
    } else location.href = prevBtn ? prevBtn.getAttribute("href") || "/" : "/";
  }

  if (nextBtn) {
    nextBtn.addEventListener("click", function (e) {
      if (cur < LAST) { e.preventDefault(); next(); return; }
      /* 마지막 화면: 앞 단계에서 비운 필수 칸이 있으면 그 단계로 돌려보낸다 */
      for (var i = 0; i < 4; i++) {
        if (i === 1) sub = 1;      // 이 검사는 첫째 작물 화면 기준(둘째 작물은 고르지 않았으면 이미 '다음'에서 막혔다)
        if (!stepOk(i)) { e.preventDefault(); show(i, true, 1); return; }
      }
      if (!mustOk()) e.preventDefault();
    });
  }
  /* 숫자판의 확인: 판을 닫고 방금 누른 숫자를 큰 글씨로 보여 준다(맞으면 '다음'). 곧바로 넘기지 않는다 */
  form.addEventListener("numpad-done", function () { update(); });
  /* 처음으로 · 로고: 답이 지워진다고 한 번 묻는다 */
  var homeBtn = document.querySelector("[data-home-q]");
  if (homeBtn) homeBtn.addEventListener("click", function () { if (window.confirm("지금까지 한 답을 지우고 처음으로 갈까요?")) location.href = "/"; });
  var brand = document.querySelector(".brand");
  if (brand) brand.addEventListener("click", function (e) { if (!window.confirm("지금까지 한 답을 지우고 처음으로 갈까요?")) e.preventDefault(); });
  if (prevBtn) prevBtn.addEventListener("click", function (e) { e.preventDefault(); prev(); });
  window.addEventListener("popstate", function (e) {
    if (e.state && typeof e.state.n === "number" && qs[e.state.n] !== undefined) { depth = e.state.n; var v = qs[depth]; show(Math.floor(v / 10), false, v % 10 ? 2 : 1); }
  });
  /* 글 칸에서 Enter를 눌러도 제출하지 않는다(반쯤 넣은 폼이 넘어가지 않게) */
  form.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && e.target.tagName === "INPUT" && e.target.type !== "checkbox") e.preventDefault();
  });

  /* ---------- 시 탭 ---------- */
  function showCity(city) {
    $$("[data-city-tab]").forEach(function (t) {
      var on = t.getAttribute("data-city-tab") === city;
      t.classList.toggle("on", on);
      t.setAttribute("aria-selected", on ? "true" : "false");
    });
    $$("[data-city-panel]").forEach(function (p) { p.classList.toggle("on", p.getAttribute("data-city-panel") === city); });
    var pc = $("[data-pick-city]");
    if (pc) pc.hidden = true;
    hint("hint-emd", false);
    need(0, false);
  }
  $$("[data-city-tab]").forEach(function (t) {
    t.addEventListener("click", function () { showCity(t.getAttribute("data-city-tab")); });
  });

  /* ---------- 평수 −/+ · 빠른 단추 ---------- */
  function setNum(name, v) {
    var el = form.elements[name];
    if (!el) return;
    el.value = v > 0 ? String(v) : "";
    fire(el, "input");
  }
  $$("[data-num-for]").forEach(function (b) {
    b.addEventListener("click", function () {
      var name = b.getAttribute("data-num-for");
      if (b.hasAttribute("data-set")) setNum(name, Number(b.getAttribute("data-set")));
      else setNum(name, (num(name) || 0) + Number(b.getAttribute("data-delta")));
    });
  });

  /* ---------- 다른 밭도 있어요 · 둘째 작물 화면 ---------- */
  function removeCrop2() {
    clearRadios("crop2_crop_code");
    setNum("crop2_area_py", 0);
    setNum("total_area_py", 0);
    warned.area2 = false;
    hint("hint-crop2", false); hint("hint-area2", false); need(1, false);
    show(1, true, 1);
  }
  $$("[data-more]").forEach(function (b) { b.addEventListener("click", function () { show(1, true, 2); }); });
  var less = $("[data-less]");
  if (less) less.addEventListener("click", removeCrop2);

  /* ---------- 눌렀다 떼는 단추(다시 누르면 풀린다) ---------- */
  $$("[data-toggle] input[type=radio]").forEach(function (r) { r.setAttribute("data-was", r.checked ? "1" : "0"); });
  form.addEventListener("click", function (e) {
    var r = e.target;
    if (!r || r.tagName !== "INPUT" || r.type !== "radio") return;
    var grp = r.closest("[data-toggle]");
    if (!grp) return;
    var mates = $$('input[type=radio]', grp);
    if (r.getAttribute("data-was") === "1") {
      var def = grp.getAttribute("data-default");
      var d = def !== null ? mates.filter(function (m) { return m.value === def; })[0] : null;
      if (d) d.checked = true; else r.checked = false;
      r.setAttribute("data-was", "0");
      fire(r, "change");
    } else {
      mates.forEach(function (m) { m.setAttribute("data-was", "0"); });
      r.setAttribute("data-was", "1");
    }
  }, true);

  /* ---------- 다른 칸 값에 따라 나타나고 사라지는 것 ---------- */
  function totalPy() {   // 합친 평수, 비어 있으면 고른 작물 넓이의 합(하나라도 비면 모름)
    if (val("total_area_py")) return num("total_area_py");
    var sum = 0, n = 0;
    for (var i = 1; i <= 2; i++) {
      if (!val("crop" + i + "_crop_code")) continue;
      var a = num("crop" + i + "_area_py");
      if (a === null) return null;
      sum += a; n++;
    }
    return n ? sum : null;
  }
  function update() {
    var i, code, fund;
    for (i = 1; i <= 2; i++) {
      code = val("crop" + i + "_crop_code");
      fund = selfpay.indexOf(code) >= 0;
      var name = code ? (cropNames[code] || code) : (i === 1 ? "첫째 작물" : "둘째 작물");
      $$('[data-crop-name="' + i + '"]').forEach(function (el) { el.textContent = name; });
      if (i === 2) setOn($('[data-crop-row="2"]'), !!code);
      setOn($('[data-selfpay-row="' + i + '"]'), fund);
    }
    /* 등록한 해: 등록했다고 한 분께만 */
    var mg = val("mgmt_status");
    var yl = $('[data-when="mgmt"]');
    var showYear = mg === "over_2y" || mg === "under_2y";
    if (yl && yl.classList.contains("is-on") && !showYear) setNum("mgmt_last_reg_year", 0);
    setOn(yl, showYear);
    /* 땅: 합친 평수가 문턱 안일 때만 */
    var total = totalPy();
    var inRange = total !== null && total >= lo && total <= hi;
    var landRow = $('[data-when="land"]'), bigRow = $('[data-when="own4700"]');
    if (landRow && landRow.classList.contains("is-on") && !inRange) {      /* 문턱 밖이면 내 땅 두 단추만 풀고, 빌려서 짓는다는 답은 그대로 둔다 */
      $$('input[name="land_tenure"]').forEach(function (r) { if (r.value !== "rent_all") { r.checked = false; r.setAttribute("data-was", "0"); } });
    }
    setOn(landRow, inRange);
    var own = val("land_tenure") === "own_all" || val("land_tenure") === "own_part";
    if (bigRow && bigRow.classList.contains("is-on") && !(inRange && own)) clearRadios("owned_over_4700py");
    setOn(bigRow, inRange && own);
    /* 첫째로 고른 작물은 둘째 화면에서, 둘째로 고른 작물은 첫째 화면에서 흐리게 하고 못 누르게 한다 */
    var c1v = val("crop1_crop_code"), c2v = val("crop2_crop_code");
    $$('input[name="crop2_crop_code"]').forEach(function (r) { r.disabled = !!c1v && r.value === c1v; });
    $$('input[name="crop1_crop_code"]').forEach(function (r) { r.disabled = !!c2v && r.value === c2v; });
    /* 첫째 화면에는 고른 둘째 작물을 한 줄로 보여 준다 */
    var xl = $("[data-x2-line]"), mb = $("[data-more].more-btn");
    setOn(xl, !!c2v);
    if (mb) mb.classList.toggle("is-gone", !!c2v);
    var xn = $("[data-x2-name]"), xa = $("[data-x2-area]");
    if (xn) xn.textContent = c2v ? (cropNames[c2v] || c2v) : "";
    if (xa) { var a2 = num("crop2_area_py"); xa.textContent = a2 ? a2.toLocaleString("ko-KR") + "평 ·" : "·"; }
    var chip2 = $("[data-crop-chip2]");
    if (chip2) { chip2.textContent = c2v ? (cropNames[c2v] || c2v) : ""; chip2.hidden = !c2v; }
    /* 안 고른 채로는 다음 단추를 연하게(눌러도 이유를 알려 준다) */
    if (nextBtn) {
      var why = "";
      if (cur === 0 && !val("emd_code")) why = cityPicked() ? "사시는 읍·면·동을 눌러 주세요" : "먼저 제주시나 서귀포시를 눌러 주세요";
      else if (cur === 1 && sub === 1 && !val("crop1_crop_code")) why = "키우시는 것을 눌러 주세요";
      else if (cur === 1 && sub === 1 && !val("crop1_area_py")) why = "몇 평인지 눌러 주세요. 모르시면 '다음'을 한 번 더 눌러 주세요";
      else if (cur === 1 && sub === 2 && !c2v) why = "둘째로 키우시는 것을 눌러 주세요";
      else if (cur === 1 && sub === 2 && !val("crop2_area_py")) why = "몇 평인지 눌러 주세요. 모르시면 '다음'을 한 번 더 눌러 주세요";
      else if (cur === 2 && !val("owner_sex")) why = "성별을 눌러 주세요";
      else if (cur === 2 && !val("birth_year")) why = "태어난 해를 눌러 주세요. 모르시면 '다음'을 한 번 더 눌러 주세요";
      nextBtn.classList.toggle("is-wait", !!why);
      var bn = document.querySelector("[data-bar-note]");     /* 연한 '다음'이 왜 아직인지 아래 띠에 한 줄로 */
      if (bn && bn.textContent !== why) bn.textContent = why;
    }
    /* 숫자판이 떠 있어 작물 그림이 접혀도 어떤 작물인지 보이게 */
    var chip = $("[data-crop-chip]");
    if (chip) {
      var c1 = val("crop1_crop_code");
      chip.textContent = c1 ? (cropNames[c1] || c1) : "";
      chip.hidden = !c1;
    }
    /* 평수: 넣었으면 맞는지 보여 준다 */
    var an = $("[data-area-note]");
    if (an) {
      var a1 = num("crop1_area_py");
      if (!an.hasAttribute("data-orig")) an.setAttribute("data-orig", an.textContent);
      an.textContent = a1 ? a1.toLocaleString("ko-KR") + "평이에요. 맞으면 오른쪽 아래 '다음'을 눌러 주세요." : an.getAttribute("data-orig");
    }
    /* 올해 나이 */
    var out = $("[data-age]");
    if (out) {
      var by = val("birth_year");
      out.textContent = /^[0-9]{4}$/.test(by) && Number(by) >= 1900 && Number(by) <= 2010 ? "올해 " + (year - Number(by)) + "세" : "";
    }
  }
  form.addEventListener("input", function (e) {
    update();
    var n = e.target && e.target.name;
    if (n === "birth_year") hint("hint-birth", false);
    if (n === "crop1_area_py") hint("hint-area", false);
    if (n === "crop2_area_py") hint("hint-area2", false);
    if (n === "mgmt_last_reg_year") hint("hint-year", false);
  });
  form.addEventListener("change", function (e) {
    update();
    var n = e.target && e.target.name;
    if (n === "emd_code") hint("hint-emd", false);
    if (n === "crop1_crop_code") hint("hint-crop", false);
    if (n === "crop2_crop_code") { hint("hint-crop2", false); need(1, false); }
    if (n === "owner_sex") { hint("hint-sex", false); need(2, false, "sex"); }
    if (n === "farming_years" || n === "spouse" || n === "residence_3y") { var g = e.target.closest("[data-must]"); if (g) g.classList.remove("is-need"); }
  });

  /* 고른 읍면동이 있는 시 탭을 연다 */
  var picked = form.querySelector('input[name="emd_code"]:checked');
  if (picked) { var panel = picked.closest("[data-city-panel]"); if (panel) showCity(panel.getAttribute("data-city-panel")); }
  try { history.replaceState({ n: 0 }, "", location.href); } catch (e) { /* 없어도 된다 */ }
  show(cur, false, sub);
})();
