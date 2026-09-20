function post(url) {
  return fetch(url, { method: "POST", headers: { "X-Requested-With": "fetch" } });
}

document.addEventListener("click", async (e) => {
  // Skim toggle (add/remove from list)
  const tog = e.target.closest("[data-toggle]");
  if (tog) {
    const id = tog.dataset.toggle;
    const row = tog.closest(".skim-row, .chip");
    const isOn = row.classList.contains("on");
    const url = isOn ? `/list/remove/${id}` : `/list/add/${id}`;
    const r = await post(url);
    if (r.ok) {
      row.classList.toggle("on");
      const box = row.querySelector(".box");
      if (box) box.textContent = row.classList.contains("on") ? "✓" : "+";
    }
    return;
  }

  // List: check off while shopping
  const chk = e.target.closest("[data-check]");
  if (chk) {
    const id = chk.dataset.check;
    const r = await post(`/list/check/${id}`);
    if (r.ok) {
      const { checked } = await r.json();
      const row = chk.closest(".row");
      row.classList.toggle("checked", checked);
      chk.textContent = checked ? "✓" : "";
    }
    return;
  }

  // List: remove row
  const rm = e.target.closest("[data-remove]");
  if (rm) {
    const id = rm.dataset.remove;
    const r = await post(`/list/remove/${id}`);
    if (r.ok) rm.closest(".row").remove();
    return;
  }

  // Catalog: soft-delete
  const del = e.target.closest("[data-delitem]");
  if (del) {
    if (!confirm("Remove this item from the catalog?")) return;
    const id = del.dataset.delitem;
    const r = await post(`/items/${id}/delete`);
    if (r.ok) del.closest("tr").remove();
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
