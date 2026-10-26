/* Incremental, acknowledged research events; never stores typed or pasted text. */
(() => {
  "use strict";
  class BehaviorTracker {
    constructor(options) {
      this.options = options;
      this.state = options.state || { pending: [], buffer: [], nextSeq: 1, eventCount: 0, dropped: 0, elapsed: 0, firstSeen: [], firstInput: [], visits: {}, preInputFocus: {}, maxOrder: -1 };
      this.baseElapsed = this.state.elapsed || 0;
      this.startedAt = performance.now();
      this.page = options.page || 2;
      this.pageStarted = document.hidden ? null : performance.now();
      this.focused = null;
      this.focusStarted = null;
      this.hiddenStarted = document.hidden ? performance.now() : null;
      this.frozen = false;
      this.uploadPromise = null;
      this.order = Array.from(new Set(Array.from(options.form.querySelectorAll("[name]")).filter(el => !el.closest("[data-track-exclude]")).map(el => el.name))).filter(name => name !== "consent_agreed");
      this.cleanup = [];
      this.listen(options.form, "focusin", event => this.focus(event.target));
      this.listen(options.form, "focusout", event => { if (event.target.name === this.focused) this.closeFocus(); });
      this.listen(options.form, "input", event => this.input(event));
      this.listen(options.form, "compositionend", event => {
        this.input(event);
        this.committedTarget = event.target;
        this.committedAt = performance.now();
      });
      this.listen(options.form, "paste", event => { if (this.eligible(event.target)) this.record("paste_event", { field: event.target.name }); });
      this.listen(document, "visibilitychange", () => this.visibility());
      this.listen(window, "pagehide", () => { this.checkpoint(); this.persist(); void this.flush(true).catch(() => {}); });
      this.record(options.state ? "session_resume" : "session_start");
      this.record("page_view");
      this.timer = setInterval(() => { if (!this.frozen) { this.checkpoint(); void this.flush().catch(() => {}); } }, 5000);
    }
    listen(target, type, callback) { target.addEventListener(type, callback); this.cleanup.push(() => target.removeEventListener(type, callback)); }
    time() { return Math.round(this.baseElapsed + performance.now() - this.startedAt); }
    phase() { return this.page >= 7 ? "survey" : "application"; }
    eligible(target) { return !this.frozen && !document.hidden && target?.name && this.order.includes(target.name) && !target.readOnly && !target.closest("[data-track-exclude]"); }
    record(type, extra = {}) {
      if (this.frozen) return;
      const queued = this.state.buffer.length + this.state.pending.reduce((sum, batch) => sum + batch.events.length, 0);
      if (queued >= 10000) { this.state.dropped += 1; return; }
      this.state.buffer.push({ type, phase: this.phase(), page: this.page, client_time_ms: this.time(), ...extra });
      this.state.eventCount += 1;
    }
    checkpoint() {
      if (this.frozen) return;
      const now = performance.now();
      if (this.pageStarted !== null) { this.record("page_duration", { duration_ms: Math.max(0, Math.round(now - this.pageStarted)) }); this.pageStarted = now; }
      if (this.focused && this.focusStarted !== null) {
        const duration = Math.max(0, Math.round(now - this.focusStarted));
        this.record("field_duration", { field: this.focused, duration_ms: duration });
        if (!this.state.firstInput.includes(this.focused)) this.state.preInputFocus[this.focused] = (this.state.preInputFocus[this.focused] || 0) + duration;
        this.focusStarted = now;
      }
      this.persist();
    }
    closeFocus() { this.checkpoint(); this.focused = null; this.focusStarted = null; this.editedThisVisit = false; this.insertedThisVisit = false; }
    focus(target) {
      if (!this.eligible(target)) return;
      const name = target.name;
      if (this.focused === name) return;
      this.closeFocus();
      if (!this.state.firstSeen.includes(name)) {
        const order = this.order.indexOf(name);
        if (order > this.state.maxOrder + 1) this.record("non_sequential", { field: name });
        this.state.maxOrder = Math.max(this.state.maxOrder, order);
        this.state.firstSeen.push(name);
      }
      if (this.lastField && this.lastField !== name && ["monthly_income", "total_debt"].includes(this.lastField) && ["monthly_income", "total_debt"].includes(name)) this.record("field_switch", { field: name });
      this.lastField = name;
      this.state.visits[name] = (this.state.visits[name] || 0) + 1;
      if (this.state.visits[name] > 1) this.record("field_revisit", { field: name });
      this.focused = name;
      this.focusStarted = performance.now();
      this.record("field_focus", { field: name });
    }
    input(event) {
      if (!this.eligible(event.target) || event.isComposing) return;
      if (event.type === "input" && event.target === this.committedTarget && performance.now() - this.committedAt < 20) {
        this.committedTarget = null;
        return;
      }
      const name = event.target.name;
      if (this.focused !== name) this.focus(event.target);
      if (!this.state.firstInput.includes(name)) {
        this.checkpoint();
        this.record("field_first_input", { field: name, duration_ms: this.state.preInputFocus[name] || 0 });
        this.state.firstInput.push(name);
      }
      this.record("input_event", { field: name });
      const type = event.inputType || "";
      if (type.startsWith("delete")) {
        this.record("delete_event", { field: name });
        if (this.insertedThisVisit) this.record("delete_after_input", { field: name });
      } else { this.insertedThisVisit = true; }
      if (this.state.visits[name] > 1 && !this.editedThisVisit) { this.record("field_edit_return", { field: name }); this.editedThisVisit = true; }
    }
    navigate(page, back = false) {
      if (this.frozen) return;
      this.closeFocus();
      this.record(back ? "page_back" : "step_advance");
      this.page = page;
      this.pageStarted = document.hidden ? null : performance.now();
      this.record("page_view");
      this.persist();
      void this.flush().catch(() => {});
    }
    visibility() {
      if (this.frozen) return;
      if (document.hidden) {
        this.checkpoint(); this.pageStarted = null; this.focusStarted = null; this.hiddenStarted = performance.now();
        this.record("visibility_change", { visibility: "hidden" });
      } else {
        if (this.hiddenStarted !== null) this.record("hidden_duration", { duration_ms: Math.round(performance.now() - this.hiddenStarted) });
        this.hiddenStarted = null; this.pageStarted = performance.now();
        if (this.focused && this.options.form.contains(document.activeElement)) this.focusStarted = performance.now();
        else this.focused = null;
        this.record("visibility_change", { visibility: "visible" });
      }
      this.persist(); void this.flush(true).catch(() => {});
    }
    persist() { this.state.elapsed = this.time(); this.options.persist(this.state); }
    seal() {
      while (this.state.buffer.length) {
        this.state.pending.push({ batch_id: BehaviorTracker.randomId(), batch_seq: this.state.nextSeq++, events: this.state.buffer.splice(0, 150) });
      }
      this.persist();
    }
    async flush(keepalive = false) {
      this.seal();
      if (this.uploadPromise) { await this.uploadPromise; this.seal(); if (this.state.pending.length) return this.flush(keepalive); return; }
      this.uploadPromise = (async () => {
        while (this.state.pending.length) {
          const batch = this.state.pending[0];
          await this.options.send(batch, keepalive);
          if (this.state.pending[0] === batch) this.state.pending.shift();
          this.persist();
        }
      })();
      try { await this.uploadPromise; } finally { this.uploadPromise = null; }
    }
    freeze() { this.checkpoint(); this.record("submit_attempt"); this.frozen = true; this.pageStarted = null; this.focusStarted = null; this.persist(); }
    resume() { this.frozen = false; this.pageStarted = document.hidden ? null : performance.now(); this.focused = null; this.persist(); }
    manifest() { return { batch_count: this.state.nextSeq - 1, event_count: this.state.eventCount, dropped_events: this.state.dropped }; }
    stop() { clearInterval(this.timer); this.frozen = true; this.cleanup.forEach(fn => fn()); }
  }
  BehaviorTracker.randomId = () => Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, "0")).join("");
  window.XinyueBehaviorTracker = BehaviorTracker;
})();
