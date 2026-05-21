// Walker client: hotkeys, per-entry actions, bulk-accept, view-time tracking,
// and SSE-driven lock/breadcrumb/body refresh.
(function () {
  "use strict";

  const body = document.body;
  if (body.dataset.page !== "changes") return;

  const reviewId = body.dataset.review;
  const cycle = body.dataset.cycle;

  function isEditable() {
    return body.dataset.editable === "true";
  }

  // ---- per-entry actions ----
  async function postChange(id, action, extra) {
    const res = await fetch(`/review/${reviewId}/change/${id}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(Object.assign({ action: action }, extra || {})),
    });
    if (res.ok) refreshBody();
    return res.ok;
  }

  function entryFor(el) {
    return el.closest(".entry");
  }

  function bindActions(root) {
    (root || document).querySelectorAll(".actions button").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const id = btn.closest(".actions").dataset.id;
        const action = btn.dataset.action;
        if (action === "accept") postChange(id, "accept");
        else if (action === "skip") postChange(id, "skip");
        else if (action === "reopen") postChange(id, "reopen");
        else if (action === "modify") toggleEdit(id);
      });
    });
    (root || document).querySelectorAll(".edit-save").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const form = btn.closest(".edit-form");
        const id = form.dataset.id;
        postChange(id, "edit", {
          after: form.querySelector(".edit-after").value,
          "human-verdict": form.querySelector(".edit-verdict").value,
          "human-rationale": form.querySelector(".edit-rationale").value,
          "human-commentary": form.querySelector(".edit-commentary").value,
        });
      });
    });
  }

  function toggleEdit(id) {
    const form = document.querySelector(`.edit-form[data-id="${id}"]`);
    if (form) form.classList.toggle("hidden");
  }

  // ---- bulk-accept (current filter) ----
  function bindBulk(root) {
    const btn = (root || document).querySelector("#bulk-accept");
    if (!btn) return;
    btn.addEventListener("click", async function () {
      const f = document.querySelector("#filters");
      const payload = {
        provenance: f.querySelector('[name=provenance]').value,
        "suggested-verdict": f.querySelector('[name=suggested_verdict]').value,
        status: f.querySelector('[name=status]').value,
        "target-section": f.querySelector('[name=target_section]').value,
      };
      const res = await fetch(`/review/${reviewId}/bulk-accept`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (res.ok) refreshBody();
    });
  }

  // ---- hotkeys: j/k navigate, a accept, m modify, s skip ----
  let focusIdx = 0;
  function entries() {
    return Array.prototype.slice.call(document.querySelectorAll(".entry"));
  }
  function focusEntry(i) {
    const list = entries();
    if (!list.length) return;
    focusIdx = Math.max(0, Math.min(i, list.length - 1));
    list.forEach((e) => e.classList.remove("focused"));
    const el = list[focusIdx];
    el.classList.add("focused");
    el.scrollIntoView({ block: "center", behavior: "smooth" });
  }
  function currentId() {
    const list = entries();
    return list.length ? list[focusIdx].dataset.id : null;
  }
  document.addEventListener("keydown", function (e) {
    if (/^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return;
    if (e.key === "j") { focusEntry(focusIdx + 1); }
    else if (e.key === "k") { focusEntry(focusIdx - 1); }
    else if (e.key === "a" && isEditable()) { const id = currentId(); if (id) postChange(id, "accept"); }
    else if (e.key === "m" && isEditable()) { const id = currentId(); if (id) toggleEdit(id); }
    else if (e.key === "s" && isEditable()) { const id = currentId(); if (id) postChange(id, "skip"); }
  });

  // ---- view-time tracking: log a `viewed` interaction (>=1s) per entry ----
  const viewStart = {};
  const viewIo = new IntersectionObserver(function (ents) {
    ents.forEach(function (it) {
      const id = it.target.dataset.id;
      if (it.isIntersecting) {
        viewStart[id] = performance.now();
      } else if (viewStart[id] != null) {
        const dur = performance.now() - viewStart[id];
        delete viewStart[id];
        if (dur >= 1000 && isEditable()) {
          fetch(`/review/${reviewId}/change/${id}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ action: "viewed", "duration-ms": Math.round(dur) }),
          }).catch(function () {});
        }
      }
    });
  }, { threshold: 0.6 });
  function observeEntries() {
    entries().forEach((e) => viewIo.observe(e));
  }

  // ---- cycle selector ----
  const cycleSel = document.querySelector("#cycle-select");
  if (cycleSel) {
    cycleSel.addEventListener("change", function () {
      location.href = `/review/${reviewId}/changes?cycle=${cycleSel.value}`;
    });
  }

  // ---- Apply ----
  const applyBtn = document.querySelector("#apply-btn");
  if (applyBtn) {
    applyBtn.addEventListener("click", async function () {
      if (applyBtn.disabled) return;
      await fetch(`/review/${reviewId}/apply`, { method: "POST" });
      // STATE.md change will arrive over SSE and flip the lock UI.
    });
  }

  // ---- SSE-driven refresh ----
  async function refreshStatus() {
    const url = `/review/${reviewId}/api/status` + (cycle ? `?cycle=${cycle}` : "");
    const res = await fetch(url);
    if (!res.ok) return;
    const s = await res.json();
    const wasEditable = isEditable();
    body.dataset.editable = s.editable ? "true" : "false";

    const bc = document.querySelector("#breadcrumb");
    if (bc && s.breadcrumb) bc.textContent = s.breadcrumb;
    const ph = document.querySelector("#phase-text");
    if (ph && s.phase) ph.textContent = s.phase;
    const hint = document.querySelector("#hint");
    if (hint && s.hint != null) hint.textContent = s.hint;

    const ind = document.querySelector("#activity-indicator");
    if (ind) {
      ind.classList.toggle("animating", !!s.animating);
      ind.classList.toggle("idle", !s.animating);
      ind.dataset.animating = s.animating ? "true" : "false";
      if (s.phase) ind.dataset.phase = s.phase;
    }
    if (applyBtn) {
      applyBtn.classList.toggle("hidden", !s.can_apply);
      applyBtn.disabled = !s.can_apply;
    }
    // The lock state changed — re-render the body so controls/badges match.
    if (wasEditable !== !!s.editable) refreshBody();
  }

  async function refreshBody() {
    const url = `/review/${reviewId}/changes` + (cycle ? `?cycle=${cycle}` : "");
    const res = await fetch(url);
    if (!res.ok) return;
    const html = await res.text();
    const doc = new DOMParser().parseFromString(html, "text/html");
    const fresh = doc.querySelector("#walker-body");
    const cur = document.querySelector("#walker-body");
    if (fresh && cur) {
      cur.replaceWith(fresh);
      bindActions(document);
      bindBulk(document);
      observeEntries();
    }
  }

  function updateAudited(n) {
    const el = document.querySelector("#audited-count");
    if (el && n != null) el.textContent = n;
  }

  function connectSSE() {
    const es = new EventSource(`/events?review=${reviewId}`);
    es.addEventListener("state", refreshStatus);
    es.addEventListener("leader", refreshStatus);
    es.addEventListener("response", function (ev) {
      const d = safeParse(ev.data);
      if (String(d.cycle) === String(cycle)) refreshBody();
    });
    es.addEventListener("review", function (ev) {
      const d = safeParse(ev.data);
      if (String(d.cycle) === String(cycle)) refreshBody();
    });
    es.addEventListener("audit", function (ev) {
      const d = safeParse(ev.data);
      if (String(d.cycle) === String(cycle)) { updateAudited(d.audited); refreshBody(); }
    });
    es.addEventListener("focus", function (ev) {
      const d = safeParse(ev.data);
      if (!d) return;
      if (d.cycle != null && String(d.cycle) !== String(cycle)) {
        let href = `/review/${reviewId}/changes?cycle=${d.cycle}`;
        if (d.target) href += `#${d.target}`;
        location.href = href;
      } else if (d.target) {
        const el = document.querySelector(`[data-id="${d.target}"]`);
        if (el) { el.scrollIntoView({ block: "center" }); el.classList.add("focused"); }
      }
    });
  }

  function safeParse(s) { try { return JSON.parse(s); } catch (e) { return {}; } }

  // ---- init ----
  bindActions(document);
  bindBulk(document);
  observeEntries();
  focusEntry(0);
  connectSSE();
})();
