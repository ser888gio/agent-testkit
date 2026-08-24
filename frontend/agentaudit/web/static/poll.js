// Minimal polling helper for in-progress run status fragments (no HTMX/JS build).
// Any element with [data-poll-url] gets its text refreshed every 2s until the
// fetched status is no longer running.
// Render live run progress beside the status line. The panel is addressed by
// id from the status element so a page without one polls exactly as before.
function renderProgress(el, status) {
  var host = document.getElementById(el.getAttribute("data-progress-target") || "");
  if (!host) {
    return;
  }
  var total = Number(status.tests_total) || 0;
  var done = Number(status.tests_done) || 0;
  var bar = host.querySelector(".progress-fill");
  if (bar) {
    bar.style.width = total > 0 ? Math.round((done / total) * 100) + "%" : "0%";
  }
  var meter = host.querySelector(".progress-meter");
  if (meter && total > 0) {
    meter.setAttribute("aria-valuenow", String(done));
    meter.setAttribute("aria-valuemax", String(total));
  }
  var list = host.querySelector(".progress-list");
  if (!list || !Array.isArray(status.recent)) {
    return;
  }
  list.replaceChildren.apply(
    list,
    status.recent
      .slice()
      .reverse()
      .map(function (entry) {
        var li = document.createElement("li");
        var name = document.createElement("span");
        name.className = "mono";
        name.textContent = String(entry.test_id);
        var badge = document.createElement("span");
        badge.className = "badge badge-" + String(entry.status);
        badge.textContent = String(entry.status);
        li.append(name, badge);
        return li;
      })
  );
  host.hidden = total === 0;
}

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
          renderProgress(el, status);
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
