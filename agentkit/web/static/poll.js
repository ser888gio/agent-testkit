// Minimal polling helper for in-progress run status fragments (no HTMX/JS build).
// Any element with [data-poll-url] gets its text refreshed every 2s until the
// fetched status is no longer running.
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-poll-url]").forEach((el) => {
    const url = el.getAttribute("data-poll-url");
    const tick = () => {
      fetch(url, { headers: { Accept: "application/json" } })
        .then((r) => r.json())
        .then((status) => {
          if (typeof status.run_id === "string" && status.run_id.length > 0) {
            el.setAttribute("data-run-id", status.run_id);
          }
          el.textContent = typeof status.message === "string" ? status.message : "";
          if (status.running === true) {
            setTimeout(tick, 2000);
          }
        });
    };
    tick();
  });
});
