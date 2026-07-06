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

const _i = p => `<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">${p}</svg>`;

const ICON = {
  chev: '<svg width="11" height="11" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M6 3.5 10.5 8 6 12.5"/></svg>',
  pen: '<svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M11.3 2.4a1.6 1.6 0 0 1 2.3 2.3L6.1 12.2l-3.3.9.9-3.3z"/></svg>',
  x: '<svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M4 4l8 8M12 4l-8 8"/></svg>',
  plus: '<svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M8 3v10M3 8h10"/></svg>',
  info: _i('<circle cx="8" cy="8" r="5.6"/><path d="M8 7.4v3.2"/><path d="M8 5.2h.01"/>'),
  home: _i('<path d="M3 7.6 8 3.3l5 4.3"/><path d="M4.4 7V12.7h7.2V7"/>'),
  sliders: _i('<path d="M3 5.2h5M11.6 5.2H13M3 10.8h1.4M7.6 10.8H13"/><circle cx="9.8" cy="5.2" r="1.6"/><circle cx="5.2" cy="10.8" r="1.6"/>'),
  clock: _i('<circle cx="8" cy="8" r="5.6"/><path d="M8 5.2V8l2.2 1.5"/>'),
  chart: _i('<path d="M3 3v10h10"/><path d="M5.5 9.6 8 7l1.8 1.8L13 4.9"/>'),
  compass: _i('<circle cx="8" cy="8" r="5.6"/><path d="m10.3 5.7-1.5 3.1-3.1 1.5 1.5-3.1z"/>'),
  wallet: _i('<rect x="2.4" y="4.4" width="11.2" height="8" rx="1.8"/><path d="M2.4 6.9h11.2"/><path d="M11 9.7h.01"/>'),
  flag: _i('<path d="M4 13.6V2.8"/><path d="M4 3.2h6.8L9.2 5.9l1.6 2.7H4"/>'),
  trend: _i('<path d="M2.5 11.5 6.5 7.4l2.5 2.5 4.5-5"/><path d="M10.3 4.9h3.2v3.2"/>'),
  cal: _i('<rect x="2.8" y="3.4" width="10.4" height="9.6" rx="1.6"/><path d="M2.8 6.6h10.4M5.8 2.2v2M10.2 2.2v2"/>'),
  tag: _i('<path d="M2.6 7V3.4a.8.8 0 0 1 .8-.8H7a1 1 0 0 1 .7.3l5.3 5.3a1 1 0 0 1 0 1.4l-3.7 3.7a1 1 0 0 1-1.4 0L2.9 7.7a1 1 0 0 1-.3-.7z"/><path d="M5.7 5.7h.01"/>'),
  banknote: _i('<rect x="2.2" y="4.6" width="11.6" height="6.8" rx="1.4"/><circle cx="8" cy="8" r="1.7"/><path d="M4.5 8h.01M11.5 8h.01"/>'),
  cart: _i('<path d="M2.6 3.4h1.6l1.5 6.6h5.9l1.8-4.9H4.8"/><circle cx="6.3" cy="12.7" r=".9"/><circle cx="10.9" cy="12.7" r=".9"/>'),
  check: _i('<path d="m3.4 8.6 2.9 2.9 6.3-7"/>'),
  scales: _i('<path d="M5.3 12.6V3.4M5.3 3.4 3.2 5.5M5.3 3.4l2.1 2.1"/><path d="M10.7 3.4v9.2m0 0 2.1-2.1m-2.1 2.1-2.1-2.1"/>'),
  upload: _i('<path d="M8 10.6V3.2M8 3.2 5.4 5.8M8 3.2l2.6 2.6"/><path d="M3 12.8h10"/>'),
  list: _i('<path d="M5.8 4.4h7.4M5.8 8h7.4M5.8 11.6h7.4"/><path d="M2.8 4.4h.01M2.8 8h.01M2.8 11.6h.01"/>'),
  filter: _i('<path d="M2.6 3.4h10.8L9.6 8.3v3.8l-3.2 1.5V8.3z"/>'),
  file: _i('<path d="M4 2.6h4.9L12 5.7v7.7H4z"/><path d="M8.7 2.8V6h3.1"/>'),
  layers: _i('<path d="m8 2.8 5.6 3L8 8.8l-5.6-3z"/><path d="M2.4 9.2 8 12.2l5.6-3"/>'),
  lock: _i('<rect x="3.8" y="7" width="8.4" height="6" rx="1.4"/><path d="M5.6 7V5.4a2.4 2.4 0 0 1 4.8 0V7"/>'),
  bank: _i('<path d="M2.6 6.2 8 3l5.4 3.2"/><path d="M3.7 6.5v4.3M8 6.5v4.3M12.3 6.5v4.3"/><path d="M2.6 13h10.8"/>'),
  droplet: _i('<path d="M8 2.8c2.1 2.5 3.6 4.3 3.6 6.1a3.6 3.6 0 1 1-7.2 0C4.4 7.1 5.9 5.3 8 2.8z"/>'),
};

// ⓘ + hover card; content is inline HTML (used next to section headings)
const infoTip = html =>
  `<span class="tip" tabindex="0">${ICON.info}<span class="tipbox">${html}</span></span>`;

// shared explainers, mounted wherever a heading carries data-tip="key"
const TIP = {
  goals: "A <b>goal</b> is a finite pot with a deadline — save RM X by date Y " +
    "(house cash, a car, a trip), log contributions until it's done. " +
    "Standing routes like the EPF drip or the S&P cut aren't goals: give them an " +
    "<b>investment</b> row with a rhythm instead — a goal that never finishes always reads as behind.",
};

const LOGO = '<svg width="20" height="20" viewBox="0 0 32 32" fill="none" aria-hidden="true"><defs><linearGradient id="lg" x1="0" y1="0" x2="32" y2="32"><stop stop-color="#3ecf8e"/><stop offset="1" stop-color="#4f7cf0"/></linearGradient></defs><rect width="32" height="32" rx="9" fill="url(#lg)"/><rect x="7" y="17" width="4.5" height="8" rx="2" fill="#fff" opacity=".8"/><rect x="13.75" y="12" width="4.5" height="13" rx="2" fill="#fff" opacity=".9"/><rect x="20.5" y="7" width="4.5" height="18" rx="2" fill="#fff"/></svg>';

(function mountNav() {
  // brand is the logo alone — the first tab already reads "Budget"
  const links = [["/", "Budget", "home", "home"], ["/plan", "Plan", "plan", "sliders"],
                 ["/upcoming", "Upcoming", "radar", "clock"], ["/savings", "Savings", "savings", "chart"],
                 ["/strategy", "Strategy", "strategy", "compass"]];
  const here = document.body.dataset.page;
  $("top").innerHTML = '<div class="nav-inner"><a class="brand" href="/">' + LOGO + "</a><nav>" +
    links.map(([href, label, key, icon]) =>
      `<a href="${href}"${key === here ? ' class="on"' : ""}>${ICON[icon]}<span>${label}</span></a>`).join("") +
    "</nav></div>";
  // static pages tag headings with data-i="iconname" / data-tip="key"
  document.querySelectorAll("[data-i]").forEach(el =>
    el.insertAdjacentHTML("afterbegin", ICON[el.dataset.i] || ""));
  document.querySelectorAll("[data-tip]").forEach(el => {
    if (TIP[el.dataset.tip]) el.innerHTML = infoTip(TIP[el.dataset.tip]);
  });
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
