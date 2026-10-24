(() => {
  "use strict";
  const body = document.getElementById("records-body"), status = document.getElementById("sync-state");
  if (!body || !status) return;
  const formatTime = value => value ? new Date(value).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false }) : "—";
  function cell(row, value) { const td = document.createElement("td"); td.textContent = value; row.append(td); return td; }
  let active = false;
  async function refresh() {
    if (document.hidden || active) { setTimeout(refresh, 5000); return; }
    active = true;
    const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 10000);
    try {
      const response = await fetch(`/admin/api/overview${location.search}`, { signal: controller.signal });
      if (response.status === 401) { status.textContent = "登录已过期，请重新登录。"; return; }
      const result = await response.json();
      if (!response.ok || !result.ok) throw new Error("refresh failed");
      const data = result.data;
      for (const [id, key] of [["stat-total", "total"], ["stat-submitted", "submitted"], ["stat-progress", "in_progress"], ["stat-formal", "formal"], ["stat-tests", "tests"]]) document.getElementById(id).textContent = data[key];
      const fragment = document.createDocumentFragment();
      for (const item of data.participants) {
        const row = document.createElement("tr");
        cell(row, item.participant_id); cell(row, item.is_test ? "测试" : "正式"); cell(row, item.status === "submitted" ? "已提交" : "填写中");
        cell(row, `${item.progress}%`); cell(row, formatTime(item.created_at)); cell(row, formatTime(item.saved_at)); cell(row, formatTime(item.submitted_at));
        const coverage = { complete: "已同步", incomplete: "需核查", received: "接收中", not_started: "未开始" }[item.behavior_status] || "待核查";
        cell(row, `${item.received_batches}批 / ${item.received_events}条 · ${coverage}`);
        const td = cell(row, ""), link = document.createElement("a"); link.textContent = "查看"; link.className = "table-link"; link.href = `/admin/participants/${encodeURIComponent(item.participant_id)}`; td.append(link); fragment.append(row);
      }
      if (!data.participants.length) { const row = document.createElement("tr"), td = cell(row, "此筛选范围内没有记录。"); td.colSpan = 9; fragment.append(row); }
      body.replaceChildren(fragment);
      status.textContent = `每5秒自动刷新 · 最后同步：${formatTime(data.synced_at)}`;
    } catch (_) { status.textContent = "暂时无法刷新，现有列表已保留，稍后自动重试。"; }
    finally { clearTimeout(timeout); active = false; setTimeout(refresh, 5000); }
  }
  setTimeout(refresh, 5000);
})();
