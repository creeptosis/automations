/* Budget · shared front-end helpers: nav shell, formatting, api, toast, skeletons */

const $ = id => document.getElementById(id);

const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));

const fmt = v => {
  const a = Math.abs(v);
  const s = "RM " + (a % 1 > 0.004
    ? a.toLocaleString("en-MY", {minimumFractionDigits: 2, maximumFractionDigits: 2})
    : a.toLocaleString("en-MY", {maximumFractionDigits: 0}));
  return (v < 0 ? "−" : "") + s;
};
const pc = v => v == null ? "–" : v.toFixed(1) + "%";
const sgn = v => (v >= 0 ? "+" : "−") + fmt(Math.abs(v));

const ICON = {
  chev: '<svg width="11" height="11" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M6 3.5 10.5 8 6 12.5"/></svg>',
  pen: '<svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M11.3 2.4a1.6 1.6 0 0 1 2.3 2.3L6.1 12.2l-3.3.9.9-3.3z"/></svg>',
  x: '<svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M4 4l8 8M12 4l-8 8"/></svg>',
  plus: '<svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M8 3v10M3 8h10"/></svg>',
};

const LOGO = '<svg width="20" height="20" viewBox="0 0 32 32" fill="none" aria-hidden="true"><defs><linearGradient id="lg" x1="0" y1="0" x2="32" y2="32"><stop stop-color="#3ecf8e"/><stop offset="1" stop-color="#4f7cf0"/></linearGradient></defs><rect width="32" height="32" rx="9" fill="url(#lg)"/><rect x="7" y="17" width="4.5" height="8" rx="2" fill="#fff" opacity=".8"/><rect x="13.75" y="12" width="4.5" height="13" rx="2" fill="#fff" opacity=".9"/><rect x="20.5" y="7" width="4.5" height="18" rx="2" fill="#fff"/></svg>';

(function mountNav() {
  // brand is the logo alone — the first tab already reads "Budget"
  const links = [["/", "Budget", "home"], ["/plan", "Plan", "plan"],
                 ["/upcoming", "Upcoming", "radar"], ["/savings", "Savings", "savings"]];
  const here = document.body.dataset.page;
  $("top").innerHTML = '<div class="nav-inner"><a class="brand" href="/">' + LOGO + "</a><nav>" +
    links.map(([href, label, key]) =>
      `<a href="${href}"${key === here ? ' class="on"' : ""}>${label}</a>`).join("") +
    "</nav></div>";
})();

function toast(msg) {
  let el = $("toast");
  if (!el) {
    el = document.createElement("div");
    el.id = "toast";
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.remove("show"), 3500);
}

async function api(method, path, body) {
  const r = await fetch(path, {
    method,
    headers: body ? {"Content-Type": "application/json"} : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (r.status === 401) { location.href = "/login"; throw new Error("login required"); }
  const j = await r.json().catch(() => ({}));
  if (!r.ok) { toast(j.error || "something went wrong"); throw new Error(j.error || String(r.status)); }
  return j;
}
const getJSON = path => api("GET", path);

function unskel() { document.querySelectorAll(".skelwrap").forEach(e => e.remove()); }
function skelFail() {
  document.querySelectorAll(".skelwrap").forEach(e => {
    e.outerHTML = '<div class="empty">could not load — refresh to retry</div>';
  });
}
