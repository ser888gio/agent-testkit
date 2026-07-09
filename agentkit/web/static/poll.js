// Minimal polling helper for in-progress run status fragments (no HTMX/JS build).
// Any element with [data-poll-url] gets its innerHTML refreshed every 2s until
// the fetched fragment no longer contains a [data-run-id] with "Running...".
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-poll-url]").forEach((el) => {
    const url = el.getAttribute("data-poll-url");
    const tick = () => {
      fetch(url)
        .then((r) => r.text())
        .then((html) => {
          el.innerHTML = html;
          if (html.includes("Running...")) {
            setTimeout(tick, 2000);
          }
        });
    };
    tick();
  });
});
