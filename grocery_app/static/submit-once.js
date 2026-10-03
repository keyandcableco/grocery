// Forms marked data-submit-once ignore repeat submits while the first is in flight.
document.addEventListener('submit', function (e) {
  var form = e.target;
  if (!form.matches('form[data-submit-once]')) return;
  if (form.dataset.submitting === '1') { e.preventDefault(); return; }
  if (e.defaultPrevented) return;
  form.dataset.submitting = '1';
  var btn = e.submitter || form.querySelector('[type=submit]');
  if (btn) {
    btn.dataset.busy = '1';
    btn.style.opacity = '0.6';
    btn.style.cursor = 'wait';
    if (btn.tagName === 'BUTTON') { btn.dataset.label = btn.textContent; btn.textContent = 'Saving…'; }
  }
});
// Reset if the page is restored from the back/forward cache.
window.addEventListener('pageshow', function () {
  document.querySelectorAll('form[data-submitting]').forEach(function (f) { delete f.dataset.submitting; });
  document.querySelectorAll('[data-busy]').forEach(function (b) {
    b.style.opacity = ''; b.style.cursor = '';
    if (b.dataset.label !== undefined) { b.textContent = b.dataset.label; delete b.dataset.label; }
    delete b.dataset.busy;
  });
});
