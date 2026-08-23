// Minimal polling helper for in-progress run status fragments (no HTMX/JS build).
// Any element with [data-poll-url] gets its text refreshed every 2s until the
// fetched status is no longer running.
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".filter-bar").forEach((form) => {
    let timer;
    const submit = () => {
      if (typeof form.requestSubmit === "function") {
        form.requestSubmit();
      } else {
        form.submit();
      }
    };

    form.querySelectorAll("select").forEach((select) => {
      select.addEventListener("change", submit);
    });

    form.querySelectorAll('input[type="search"]').forEach((input) => {
      input.addEventListener("input", () => {
        window.clearTimeout(timer);
        timer = window.setTimeout(submit, 350);
      });
    });
  });

  document.querySelectorAll("[data-poll-url]").forEach((el) => {
    const url = el.getAttribute("data-poll-url");
    let failures = 0;
    const tick = () => {
      fetch(url, { headers: { Accept: "application/json" } })
        .then((r) => r.json())
        .then((status) => {
          failures = 0;
          if (typeof status.run_id === "string" && status.run_id.length > 0) {
            el.setAttribute("data-run-id", status.run_id);
            // A queued job has no run until the worker finishes one; follow it.
            const redirect = el.getAttribute("data-poll-redirect");
            if (redirect) {
              window.location.assign(redirect + encodeURIComponent(status.run_id));
              return;
            }
          }
          el.setAttribute("aria-live", "polite");
          el.textContent = typeof status.message === "string" ? status.message : "";
          if (status.running === true) {
            setTimeout(tick, 2000);
          }
        })
        .catch(() => {
          failures += 1;
          el.setAttribute("aria-live", "polite");
          if (failures >= 3) {
            el.textContent = "Status temporarily unavailable. Retrying...";
          }
          setTimeout(tick, Math.min(10000, 2000 * failures));
        });
    };
    tick();
  });
});

// Show only the selected pack's tests in the run form's picker. The form posts
// one pack, so offering another pack's tests invites a selection the server
// must reject. Progressive enhancement: with JS off every group stays visible
// and the server still validates the ids against the pack it loads.
document.addEventListener("DOMContentLoaded", function () {
  var packSelect = document.querySelector('select[name="packs"]');
  var groups = document.querySelectorAll(".test-picker-group");
  if (!packSelect || groups.length === 0) {
    return;
  }
  var sync = function () {
    groups.forEach(function (group) {
      var mine = group.getAttribute("data-pack") === packSelect.value;
      group.hidden = !mine;
      if (!mine) {
        // Uncheck what is no longer offered, so switching packs cannot submit
        // a stale selection the user can no longer see.
        group.querySelectorAll('input[type="checkbox"]').forEach(function (box) {
          box.checked = false;
        });
      }
    });
  };
  packSelect.addEventListener("change", sync);
  sync();
});
