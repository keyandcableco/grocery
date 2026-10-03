function post(url, body) {
  return fetch(url, { method: "POST", headers: { "X-Requested-With": "fetch" }, body });
}

// Taps update the page at once and the server catches up behind them.
// Each key has at most one request in flight; taps made meanwhile only
// change what gets sent next, so a double tap can't undo itself and the
// last tap always wins. If the server refuses, the page goes back to the
// last state it confirmed.
const syncs = {};
function sync(key, current, want, send, show) {
  const s = syncs[key] || (syncs[key] = { sent: current, busy: false });
  s.want = want;
  show(want);
  if (s.busy) return;
  s.busy = true;
  (async () => {
    while (s.sent !== s.want) {
      const target = s.want;
      let ok = false;
      try { ok = (await send(target)).ok; } catch (err) { ok = false; }
      if (!ok) { show(s.sent); break; }
      s.sent = target;
    }
    delete syncs[key];
  })();
}

function setOnList(id, on) {
  document.querySelectorAll(`[data-toggle="${id}"]`).forEach((tog) => {
    const row = tog.closest(".skim-row, .chip");
    row.classList.toggle("on", on);
    const box = row.querySelector(".box");
    if (box) box.textContent = on ? "✓" : "+";
  });
}

function setChecked(chk, checked) {
  chk.closest(".row").classList.toggle("checked", checked);
  chk.textContent = checked ? "✓" : "";
}

// Hide right away; drop for good once the server agrees, or bring it back.
function removeRow(row, url) {
  if (row.hidden) return;
  row.hidden = true;
  post(url)
    .then((r) => { if (r.ok) row.remove(); else row.hidden = false; })
    .catch(() => { row.hidden = false; });
}

document.addEventListener("click", (e) => {
  // Skim toggle (add/remove from list)
  const tog = e.target.closest("[data-toggle]");
  if (tog) {
    const id = tog.dataset.toggle;
    const on = tog.closest(".skim-row, .chip").classList.contains("on");
    sync("on" + id, on, !on,
      (want) => post(want ? `/list/add/${id}` : `/list/remove/${id}`),
      (state) => setOnList(id, state));
    return;
  }

  // List: check off while shopping
  const chk = e.target.closest("[data-check]");
  if (chk) {
    const id = chk.dataset.check;
    const checked = chk.closest(".row").classList.contains("checked");
    sync("check" + id, checked, !checked,
      (want) => post(`/list/check/${id}`, new URLSearchParams({ checked: want ? "1" : "0" })),
      (state) => setChecked(chk, state));
    return;
  }

  // List: remove row
  const rm = e.target.closest("[data-remove]");
  if (rm) {
    removeRow(rm.closest(".row"), `/list/remove/${rm.dataset.remove}`);
    return;
  }

  // Catalog: soft-delete
  const del = e.target.closest("[data-delitem]");
  if (del) {
    if (del.closest("tr").hidden) return;
    if (!confirm("Remove this item from the catalog?")) return;
    removeRow(del.closest("tr"), `/items/${del.dataset.delitem}/delete`);
    return;
  }
});

// List: quantity edit (debounced on change)
document.addEventListener("change", async (e) => {
  const qty = e.target.closest("[data-qty]");
  if (qty) {
    const id = qty.dataset.qty;
    const body = new URLSearchParams({ qty: qty.value });
    await fetch(`/list/qty/${id}`, { method: "POST", body });
  }
});

// Skim: live text filter
const box = document.getElementById("filter-box");
if (box) {
  box.addEventListener("input", () => {
    const q = box.value.trim().toLowerCase();
    document.querySelectorAll(".skim-row").forEach((row) => {
      row.classList.toggle("hidden", q && !row.dataset.name.includes(q));
    });
  });
}
