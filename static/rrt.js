/* Private random draws live only in this closure/DOM. No trackers or storage. */
(() => {
  "use strict";
  let initialized = false;
  window.XinyueRrt = { init(options) {
    if (initialized) return;
    initialized = true;
    const id = value => document.getElementById(value);
    const panel = id("rrt-panel");
    if (!panel) return;
    let voucher = null, busy = false;
    const status = text => { id("rrt-status").textContent = text; };
    function finish(text) {
      voucher = null;
      id("rrt-private-question").textContent = "";
      panel.querySelectorAll('input[type="radio"]').forEach(el => { el.checked = false; });
      id("rrt-intro").hidden = true; id("rrt-question-area").hidden = true;
      status(text);
    }
    id("rrt-decline").addEventListener("click", () => finish("本次未参加独立调查，申请回执已保存。"));
    id("rrt-start").addEventListener("click", async () => {
      if (busy) return;
      if (!id("rrt-consent").checked) { status("请阅读随机规则并自愿勾选同意，或选择暂不参加。"); return; }
      if (!window.crypto?.getRandomValues) { status("当前浏览器不支持可靠私下随机，你可以不参加本调查。"); return; }
      busy = true; id("rrt-start").disabled = true; id("rrt-decline").disabled = true;
      try {
        const invitation = await options.issue();
        if (invitation.already_recorded) { finish("这次独立调查已保存，无需重复填写。"); return; }
        voucher = invitation.voucher;
        const draws = crypto.getRandomValues(new Uint8Array(2));
        const question = draws[0] & 1 ? id("rrt-private-question").dataset.sensitiveQuestion + "没有到期借款经历，请选“否”。" :
          "本次独立公平随机结果为“" + (draws[1] & 1 ? "正面" : "反面") + "”。请回答：这个随机结果是否为正面？";
        id("rrt-private-question").textContent = question;
        draws.fill(0);
        id("rrt-intro").hidden = true; id("rrt-question-area").hidden = false;
        status("请只回答屏幕当次显示的这一题，也可以跳过。");
      } catch (_) { status("调查暂未开始，请稍后重试；已保存的申请不受影响。"); }
      finally { busy = false; id("rrt-start").disabled = false; id("rrt-decline").disabled = false; }
    });
    async function send(choice) {
      if (busy || !voucher) return;
      if (!choice) { status("请选择是或否，或点击跳过这题。"); return; }
      busy = true; id("rrt-send").disabled = true; id("rrt-skip").disabled = true;
      const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 20000);
      try {
        const response = await fetch("/api/rrt/responses", { method: "POST", signal: controller.signal,
          headers: { "Content-Type": "application/json", Authorization: "Bearer " + voucher },
          body: JSON.stringify({ choice, protocol_version: panel.dataset.version }) });
        const body = await response.json();
        if (!response.ok || !body.ok || !body.data.recorded) throw new Error("unconfirmed");
        finish("独立调查已保存。感谢参与！申请回执仍在上方。" );
      } catch (_) { status("尚未收到调查保存确认，请保留当前页面重试，不要重新抽签。申请回执已保存。"); }
      finally { clearTimeout(timeout); busy = false; id("rrt-send").disabled = false; id("rrt-skip").disabled = false; }
    }
    id("rrt-send").addEventListener("click", () => send(panel.querySelector('input[name="rrt-choice"]:checked')?.value));
    id("rrt-skip").addEventListener("click", () => send("skipped"));
  } };
})();
