(() => {
  "use strict";
  const form = document.getElementById("loan-application-form");
  if (!form) return;
  const KEY = "xinyue.original-eight-page.v3";
  const pages = Array.from(form.querySelectorAll(".form-page"));
  const byId = id => document.getElementById(id);
  const error = byId("form-error");
  const saveState = byId("save-state");
  const prev = byId("prev-btn"), next = byId("next-btn"), submit = byId("submit-btn");
  const rawNames = ["nickname", "age", "education", "occupation", "monthly_income", "total_debt", "loan_amount", "loan_term", "loan_purpose", "interest_rate", "interest_rate_confirmed", "final_confirmed"];
  let state = { page: 1, participantId: null, token: null, seq: 0, submissionKey: null, behavior: null, submitting: false, submitted: false };
  let tracker = null, draftTimer = null, retryTimer = null, draftPromise = null, dirty = false;

  function showError(message = "") { error.textContent = message; error.hidden = !message; }
  function saved(message, failed = false) { saveState.textContent = message; saveState.className = failed ? "is-error" : "is-saved"; }
  function inputFor(name) { return form.elements.namedItem(name); }
  function rawForm() {
    return Object.fromEntries(rawNames.map(name => { const el = inputFor(name); return [name, el.type === "checkbox" ? el.checked : el.value]; }));
  }
  function answers() { return Object.fromEntries(Array.from({ length: 29 }, (_, i) => { const name = `rs_q${String(i + 1).padStart(2, "0")}`; const selected = form.querySelector(`input[name="${name}"]:checked`); return [name, selected ? Number(selected.value) : null]; })); }
  function apiForm() {
    const raw = rawForm();
    const result = { form_layout: "original-eight-page-v1" };
    for (const name of rawNames.filter(name => name !== "final_confirmed")) {
      if (["age", "monthly_income", "total_debt", "loan_amount", "loan_term", "interest_rate"].includes(name)) result[name] = raw[name] === "" ? null : Number(raw[name]);
      else result[name] = raw[name] === "" ? null : raw[name];
    }
    return result;
  }
  function persist() {
    if (!state.token || state.submitted) return;
    try { sessionStorage.setItem(KEY, JSON.stringify({ ...state, form: rawForm(), answers: answers(), experiment: form.dataset.experimentVersion })); }
    catch (_) { saved("浏览器暂存不可用，请保持本页打开并留意保存状态。", true); }
  }
  function ratio() {
    const income = inputFor("monthly_income").value, debt = inputFor("total_debt").value;
    byId("debt_ratio").value = income !== "" && debt !== "" && Number(income) > 0 ? (Number(debt) / Number(income) * 100).toFixed(2) : "";
  }
  function updateReview() {
    ratio();
    const data = apiForm(), review = byId("application-review");
    review.replaceChildren();
    const items = [["称呼", data.nickname || "未填写"], ["年龄", data.age === null ? "未填写" : `${data.age}岁`], ["月可支配收入", data.monthly_income === null ? "未作答" : `${data.monthly_income}元`], ["当前总负债", data.total_debt === null ? "未作答" : `${data.total_debt}元`], ["模拟贷款金额", data.loan_amount === null ? "未填写" : `${data.loan_amount}元`], ["模拟期限", data.loan_term === null ? "未填写" : `${data.loan_term}个月`], ["模拟用途", data.loan_purpose || "未填写"], ["模拟年化利率", data.interest_rate === null ? "未选择" : `${data.interest_rate}%`]];
    for (const [label, value] of items) { const dt = document.createElement("dt"), dd = document.createElement("dd"); dt.textContent = label; dd.textContent = value; review.append(dt, dd); }
  }
  function render(page, tracking = true) {
    if (tracker && tracking && page !== state.page) tracker.navigate(page, page < state.page);
    state.page = page;
    pages.forEach(el => { el.hidden = Number(el.dataset.page) !== page; });
    byId("step-indicator").textContent = `第 ${page} / 8 页`;
    prev.disabled = page === 1 || state.submitting;
    next.hidden = page === 8; submit.hidden = page !== 8;
    next.disabled = state.submitting; submit.disabled = state.submitting;
    byId("session-info").hidden = !state.participantId;
    byId("participant-code").textContent = state.participantId || "";
    inputFor("consent_agreed").disabled = !!state.token;
    const count = Object.values(answers()).filter(value => value !== null).length;
    form.querySelectorAll(".answered-count").forEach(el => { el.textContent = count; });
    if (page === 6) updateReview();
    showError(); persist();
    window.scrollTo({ top: 0, behavior: "auto" });
  }
  function validPage(pageNumber) {
    const page = pages.find(el => Number(el.dataset.page) === pageNumber);
    const invalid = Array.from(page.querySelectorAll("input,select")).find(el => !el.checkValidity());
    page.querySelectorAll(".is-missing").forEach(el => el.classList.remove("is-missing"));
    if (invalid) {
      if (state.page !== pageNumber) render(pageNumber);
      invalid.closest(".scale-question")?.classList.add("is-missing");
      invalid.focus(); invalid.reportValidity();
      showError(pageNumber >= 7 ? "请完成本页所有题目后继续。" : "请检查本页必填项和数字范围。" );
      return false;
    }
    return true;
  }
  async function request(path, options = {}) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(path, { ...options, signal: controller.signal, headers: { "Content-Type": "application/json", ...(state.token ? { Authorization: `Bearer ${state.token}` } : {}), ...options.headers } });
      let body = null; try { body = await response.json(); } catch (_) { /* Non-JSON errors must not be treated as receipts. */ }
      if (!response.ok || !body?.ok) {
        const failure = new Error(body?.error?.message || "保存失败，请检查网络后重试。");
        failure.code = body?.error?.code;
        throw failure;
      }
      return body.data;
    } finally { clearTimeout(timeout); }
  }
  const sessionPath = suffix => `/api/sessions/${encodeURIComponent(state.participantId)}${suffix}`;
  function startTracker(restored = false) {
    if (tracker) tracker.stop();
    tracker = new window.XinyueBehaviorTracker({
      form, page: state.page, state: restored ? state.behavior : null,
      persist: behavior => { state.behavior = behavior; persist(); },
      send: (batch, keepalive) => request(sessionPath("/behavior-batches"), { method: "POST", body: JSON.stringify(batch), keepalive }),
    });
  }
  function context() {
    const ua = navigator.userAgent.toLowerCase();
    const browser = /micromessenger/.test(ua) ? "wechat" : /edg\//.test(ua) ? "edge" : /firefox/.test(ua) ? "firefox" : /chrome|crios/.test(ua) ? "chrome" : /safari/.test(ua) ? "safari" : "other";
    return { device_type: innerWidth < 600 ? "mobile" : innerWidth < 1000 ? "tablet" : "desktop", browser, viewport_width: innerWidth, viewport_height: innerHeight, input_type_supported: "InputEvent" in window && "inputType" in InputEvent.prototype };
  }
  async function createSession() {
    if (!validPage(1)) return;
    next.disabled = true;
    try {
      const params = new URLSearchParams(location.search);
      const source = params.get("source");
      const payload = { consent: true, consent_version: form.dataset.consentVersion, is_test: form.dataset.isTest === "true", client_context: context() };
      if (source && /^[A-Za-z0-9_-]{1,64}$/.test(source)) payload.source = source;
      const session = await request("/api/sessions", { method: "POST", body: JSON.stringify(payload) });
      state.participantId = session.participant_id; state.token = session.write_token;
      state.submissionKey = window.XinyueBehaviorTracker.randomId(); state.page = 2;
      startTracker(); render(2, false); saved("填写后将自动保存");
    } catch (failure) { showError(failure.name === "AbortError" || failure instanceof TypeError ? "网络连接失败，尚未确认创建会话，请重试。" : failure.message); }
    finally { next.disabled = false; }
  }
  function scheduleSave() {
    if (!state.token || state.submitting || state.submitted) return;
    dirty = true; clearTimeout(draftTimer); clearTimeout(retryTimer);
    draftTimer = setTimeout(() => void saveDraft(), 850);
  }
  async function saveDraft() {
    if (!state.token || state.submitted || state.submitting) return;
    if (draftPromise) return draftPromise;
    const invalidNumber = Array.from(form.querySelectorAll('input[type="number"]')).find(el => el.value !== "" && !el.checkValidity());
    if (invalidNumber) { saved("部分数字超出范围，修正后自动保存。", true); return; }
    dirty = false;
    const payload = { client_seq: ++state.seq, form: apiForm(), scale_answers: answers() };
    persist(); saved("正在保存…");
    draftPromise = request(sessionPath("/draft"), { method: "PUT", body: JSON.stringify(payload) });
    try { await draftPromise; saved("草稿已保存"); }
    catch (failure) { saved("暂未保存，网络恢复后重试；请保持本页打开。", true); dirty = true; if (failure.code === "protocol_version_mismatch") showError(failure.message); }
    finally {
      draftPromise = null;
      if (dirty && !state.submitting && !state.submitted) retryTimer = setTimeout(() => void saveDraft(), 4000);
    }
  }
  function showSuccess(receipt) {
    if (!receipt?.receipt_id || receipt.status !== "submitted") throw new Error("尚未收到保存回执，请保留本页后重试。");
    state.submitted = true; state.submitting = false; tracker?.stop();
    clearTimeout(draftTimer); clearTimeout(retryTimer);
    try { sessionStorage.removeItem(KEY); } catch (_) { /* Server receipt remains authoritative. */ }
    form.hidden = true; byId("step-indicator").hidden = true;
    byId("receipt-participant").textContent = receipt.participant_id;
    byId("receipt-id").textContent = receipt.receipt_id;
    byId("behavior-receipt").textContent = receipt.behavior_status === "complete" ? "本次填写记录已同步保存。" : "申请和量表已保存，部分填写过程记录需要研究者核查。";
    byId("submit-message").hidden = false; byId("submit-message").focus();
    saved("已提交");
  }
  async function status() { return request(sessionPath("")); }
  async function submitApplication(event) {
    event.preventDefault();
    if (state.submitting || state.submitted || !state.token) return;
    for (let page = 2; page <= 8; page++) if (!validPage(page)) return;
    const payload = { submission_key: state.submissionKey, form: apiForm(), scale_answers: answers(), final_confirmed: inputFor("final_confirmed").checked };
    state.submitting = true; clearTimeout(draftTimer); clearTimeout(retryTimer);
    form.querySelectorAll("input,select,button").forEach(el => { el.disabled = true; });
    submit.textContent = "正在保存…"; showError();
    try {
      const current = await status();
      if (current.status === "submitted") { showSuccess(current.receipt); return; }
      if (draftPromise) { try { await draftPromise; } catch (_) { /* Final payload contains the latest complete answers. */ } }
      tracker.freeze();
      await tracker.flush();
      payload.behavior_manifest = tracker.manifest();
      const receipt = await request(sessionPath("/submit"), { method: "POST", body: JSON.stringify(payload) });
      showSuccess(receipt);
    } catch (failure) {
      // A lost response may follow a committed transaction. Recover the receipt first.
      try { const current = await status(); if (current.status === "submitted") { showSuccess(current.receipt); return; } } catch (_) { /* Remain retryable if offline. */ }
      state.submitting = false; tracker?.resume();
      form.querySelectorAll("input,select,button").forEach(el => { el.disabled = false; });
      submit.textContent = "重新提交";
      showError(failure instanceof TypeError || failure.name === "AbortError" ? "网络连接中断，尚未收到保存确认。答案已保留，请恢复网络后重试。" : failure.message);
      persist();
    }
  }
  function onEdit(event) {
    if (!state.token || state.submitted || state.submitting) return;
    if (event.target.name === "monthly_income" || event.target.name === "total_debt") ratio();
    event.target.closest(".scale-question")?.classList.remove("is-missing");
    const count = Object.values(answers()).filter(value => value !== null).length;
    form.querySelectorAll(".answered-count").forEach(el => { el.textContent = count; });
    showError(); persist(); scheduleSave();
  }
  next.addEventListener("click", async () => {
    if (state.submitting) return;
    if (state.page === 1 && !state.token) return createSession();
    if (validPage(state.page)) { render(state.page + 1); scheduleSave(); }
  });
  prev.addEventListener("click", () => { if (state.page > 1 && !state.submitting) render(state.page - 1); });
  form.addEventListener("input", onEdit); form.addEventListener("change", onEdit); form.addEventListener("submit", submitApplication);
  window.addEventListener("online", () => { if (state.token && !state.submitted) { scheduleSave(); void tracker?.flush().catch(() => {}); } });
  async function restore() {
    let stored = null; try { stored = JSON.parse(sessionStorage.getItem(KEY)); } catch (_) { /* Fresh participation. */ }
    if (stored?.token && stored.experiment === form.dataset.experimentVersion && stored.participantId && stored.submissionKey) {
      state = { ...state, ...stored, submitting: false, submitted: false };
      state.page = Math.max(2, Math.min(8, Number(state.page) || 2));
      for (const name of rawNames) { const el = inputFor(name); if (stored.form?.[name] !== undefined) { if (el.type === "checkbox") el.checked = !!stored.form[name]; else el.value = stored.form[name] ?? ""; } }
      for (const [name, value] of Object.entries(stored.answers || {})) { if (/^rs_q\d{2}$/.test(name) && Number.isInteger(value) && value >= 1 && value <= 7) { const el = form.querySelector(`input[name="${name}"][value="${value}"]`); if (el) el.checked = true; } }
      inputFor("consent_agreed").checked = true; ratio(); render(state.page, false);
      try {
        const current = await status();
        if (current.status === "submitted") { showSuccess(current.receipt); return; }
        state.seq = Math.max(state.seq, current.draft_seq || 0);
      } catch (failure) { if (failure.code === "protocol_version_mismatch") { showError(failure.message); return; } }
      startTracker(true); saved("已恢复本标签页的填写进度"); scheduleSave();
    } else render(1, false);
  }
  void restore();
})();
