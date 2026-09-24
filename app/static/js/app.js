// Progressive enhancements. Served from this origin (CSP, N-04); no dependencies.
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const store = {
  get(key) {
    try { return window.localStorage.getItem(key); } catch { return null; }
  },
  set(key, value) {
    try { window.localStorage.setItem(key, value); } catch { /* private mode: ignore */ }
  },
};

document.addEventListener("DOMContentLoaded", () => {
  initSearch();
  initSelection();
  initFormRows();
  $$("[data-manager-picker]").forEach((root) =>
    initPicker(root, {
      input: $('input[role="combobox"]', root),
      hidden: $('input[name="manager_id"]', root),
      list: $('[role="listbox"]', root),
      exclude: root.dataset.exclude,
      clear: $("[data-clear-manager]", root),
    }),
  );
  $$("[data-contact-picker]").forEach((root) =>
    initPicker(root, {
      input: $("[data-picker-input]", root),
      hidden: $("[data-picker-value]", root),
      list: $("[data-picker-options]", root),
    }),
  );
  initCompanyPicker();
});

// ------------------------------------------------------------------ search (S-05, N-09)

function initSearch() {
  const form = $("[data-search-form]");
  const results = $("[data-results]");
  if (!form || !results) return;
  const input = $("[data-search-input]", form);
  let timer = null;
  let generation = 0;

  const refresh = async () => {
    const params = new URLSearchParams();
    for (const [key, value] of new FormData(form)) if (String(value).trim()) params.append(key, value);
    const current = ++generation;
    const response = await fetch(`/contacts/results?${params}`, { headers: { Accept: "text/html" } });
    if (!response.ok || current !== generation) return; // a newer search is on its way
    results.innerHTML = await response.text();
    history.replaceState(null, "", params.toString() ? `/?${params}` : "/");
    document.dispatchEvent(new CustomEvent("results:updated"));
  };
  const schedule = (delay) => {
    clearTimeout(timer);
    timer = setTimeout(refresh, delay);
  };

  input.addEventListener("input", () => schedule(120));
  form.addEventListener("change", (e) => { if (e.target !== input) schedule(0); });
  form.addEventListener("submit", (e) => { e.preventDefault(); schedule(0); });

  // "/" focuses search from anywhere except text fields.
  document.addEventListener("keydown", (e) => {
    const typing = e.target.closest("input, textarea, select, [contenteditable]");
    if (e.key === "/" && !typing) {
      e.preventDefault();
      input.focus();
      input.select();
    }
  });
}

// ------------------------------------------------------------------ selection & action bar (M-01 to M-03)

function initSelection() {
  const bar = $("[data-action-bar]");
  if (!bar) return;
  const selected = new Map(); // id -> {email, name}; survives live-search refreshes
  const status = $("[data-action-status]", bar);
  const fallback = $("[data-copy-fallback]", bar);
  const fallbackText = $("[data-copy-text]", bar);

  const say = (message) => { status.textContent = message; };
  const rows = () => $$("[data-contact-id]");

  const sync = () => {
    rows().forEach((row) => {
      const box = $(".select-contact", row);
      if (box) box.checked = selected.has(row.dataset.contactId);
    });
    const all = $("[data-select-all]");
    if (all) {
      const visible = rows();
      all.checked = visible.length > 0 && visible.every((r) => selected.has(r.dataset.contactId));
    }
    $("[data-selected-count]", bar).textContent = `${selected.size} selected`;
    bar.hidden = selected.size === 0;
    if (selected.size === 0) closeMenus();
  };

  const toggle = (row, on) => {
    const id = row.dataset.contactId;
    if (on) selected.set(id, { email: row.dataset.email || "", name: row.dataset.name || "" });
    else selected.delete(id);
  };

  document.addEventListener("change", (e) => {
    if (e.target.matches(".select-contact")) {
      toggle(e.target.closest("[data-contact-id]"), e.target.checked);
      sync();
    } else if (e.target.matches("[data-select-all]")) {
      rows().forEach((row) => toggle(row, e.target.checked));
      sync();
    }
  });
  document.addEventListener("results:updated", sync);

  // ---- menus
  const menus = $$(".menu", bar);
  const closeMenus = (except) => menus.forEach((m) => { if (m !== except) m.hidden = true; });
  const openMenu = (menu) => {
    const willOpen = menu.hidden;
    closeMenus(menu);
    menu.hidden = !willOpen;
    if (willOpen) ($("input:not([type=hidden]), button", menu) || menu).focus();
  };
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeMenus(); });
  document.addEventListener("click", (e) => { if (!e.target.closest(".menu-wrap")) closeMenus(); });
  $$("[data-open-menu]", bar).forEach((button) =>
    button.addEventListener("click", () => openMenu(document.getElementById(button.dataset.openMenu))),
  );

  // Selection forms (add to list / add tag) carry the selected ids.
  $$("[data-selection-form]", bar).forEach((form) =>
    form.addEventListener("submit", () => {
      $$('input[name="contact_ids"]', form).forEach((i) => i.remove());
      for (const id of selected.keys()) {
        const hidden = document.createElement("input");
        hidden.type = "hidden";
        hidden.name = "contact_ids";
        hidden.value = id;
        form.appendChild(hidden);
      }
    }),
  );

  $("[data-clear-selection]", bar).addEventListener("click", () => {
    selected.clear();
    say("");
    fallback.hidden = true;
    sync();
  });

  const recipients = () => {
    const people = [...selected.values()];
    return {
      emails: people.filter((p) => p.email).map((p) => p.email),
      skipped: people.filter((p) => !p.email).map((p) => p.name),
    };
  };
  const skippedNote = (skipped) =>
    skipped.length ? ` · ${skipped.length} skipped (no email): ${skipped.join(", ")}` : "";

  // ---- copy emails (M-02, ADR-0009)
  const CLIENTS = { outlook: { sep: "; ", label: "Outlook" }, gmail: { sep: ", ", label: "Gmail" } };
  const copyMenu = $("[data-copy-menu]", bar);

  const copy = async (clientKey) => {
    const { emails, skipped } = recipients();
    closeMenus();
    if (!emails.length) {
      say(`Nobody selected has an email address${skippedNote(skipped)}`);
      return;
    }
    const client = CLIENTS[clientKey];
    const text = emails.join(client ? client.sep : "");
    if (client) store.set("contacts.mailClient", clientKey);
    const what = `${emails.length} address${emails.length === 1 ? "" : "es"}${client ? ` for ${client.label}` : ""}`;
    try {
      await navigator.clipboard.writeText(text);
      fallback.hidden = true;
      say(`Copied ${what}${skippedNote(skipped)}`);
    } catch {
      // N-07: no clipboard access — show the text ready to copy by hand.
      fallbackText.value = text;
      fallback.hidden = false;
      fallbackText.focus();
      fallbackText.select();
      say(`Select and copy ${what}${skippedNote(skipped)}`);
    }
  };

  $("[data-copy-emails]", bar).addEventListener("click", () => {
    const { emails } = recipients();
    if (emails.length <= 1) {
      copy(null); // one address: no separator, no question
      return;
    }
    // Offer the remembered client first.
    const preferred = store.get("contacts.mailClient");
    const buttons = $$("[data-copy-for]", copyMenu);
    buttons.forEach((b) => b.classList.toggle("preferred", b.dataset.copyFor === preferred));
    const first = buttons.find((b) => b.dataset.copyFor === preferred);
    if (first) copyMenu.insertBefore(first, buttons[0]);
    openMenu(copyMenu);
  });
  $$("[data-copy-for]", bar).forEach((b) => b.addEventListener("click", () => copy(b.dataset.copyFor)));

  // ---- compose (M-03, ADR-0009, N-08)
  const composeMenu = $("[data-compose-menu]", bar);
  $("[data-compose]", bar).addEventListener("click", () => openMenu(composeMenu));
  $$("[data-compose-in]", bar).forEach((button) =>
    button.addEventListener("click", () => {
      const { emails, skipped } = recipients();
      closeMenus();
      if (!emails.length) {
        say(`Nobody selected has an email address${skippedNote(skipped)}`);
        return;
      }
      const field = ($('input[name="compose_field"]:checked', bar) || { value: "to" }).value;
      const url = composeUrl(button.dataset.composeIn, emails, field);
      const limit = button.dataset.composeIn === "mailto" ? 2000 : 8000;
      if (url.length > limit) {
        say(`Too many recipients for a link (${emails.length}). Use Copy emails instead.`);
        return;
      }
      store.set("contacts.composeClient", button.dataset.composeIn);
      if (button.dataset.composeIn === "mailto") window.location.href = url;
      else window.open(url, "_blank", "noopener,noreferrer");
      say(`Opening a new email to ${emails.length} ${emails.length === 1 ? "person" : "people"}${skippedNote(skipped)}`);
    }),
  );

  sync();
}

function composeUrl(client, emails, field) {
  const enc = (list, sep) => list.map(encodeURIComponent).join(sep);
  if (client === "gmail") {
    return `https://mail.google.com/mail/?view=cm&fs=1&${field}=${enc(emails, ",")}`;
  }
  if (client === "outlook") {
    return `https://outlook.office.com/mail/deeplink/compose?${field}=${enc(emails, ";")}`;
  }
  return field === "cc" ? `mailto:?cc=${enc(emails, ",")}` : `mailto:${enc(emails, ",")}`;
}

// ------------------------------------------------------------------ contact form

function initFormRows() {
  const renumberPrimary = (container) => {
    $$('input[name="primary_email"]', container).forEach((radio, i) => { radio.value = String(i); });
  };
  $$("[data-add-row]").forEach((button) => {
    button.addEventListener("click", () => {
      const kind = button.dataset.addRow;
      const container = $(`[data-rows="${kind}"]`);
      const row = document.getElementById(`${kind}-row`).content.firstElementChild.cloneNode(true);
      container.appendChild(row);
      renumberPrimary(container);
      if (!$('input[name="primary_email"]:checked', container)) {
        const radio = $('input[name="primary_email"]', row);
        if (radio) radio.checked = true;
      }
      $("input", row).focus();
    });
  });
  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-remove-row]");
    if (!button) return;
    const row = button.closest(".row-item");
    const container = row.parentElement;
    row.remove();
    renumberPrimary(container);
  });
}

// C-14: company dropdown with "add new", and a default for new employees.
function initCompanyPicker() {
  const root = $("[data-company-picker]");
  if (!root) return;
  const select = $("select", root);
  const newBox = $("[data-new-company]", root);
  const newInput = $("input", newBox);
  const NEW = "__new__";
  const showNew = () => {
    newBox.hidden = select.value !== NEW;
    if (!newBox.hidden) newInput.focus();
  };
  newBox.hidden = select.value !== NEW;
  let touched = false;
  select.addEventListener("change", () => { touched = true; showNew(); });

  const type = $("[data-employee-type]");
  if (!type) return;
  const employee = type.dataset.employeeType;
  const home = type.dataset.homeCompany;
  type.addEventListener("change", () => {
    if (!home || touched) return;
    if (type.value === employee && !select.value) select.value = home;
    else if (type.value !== employee && select.value === home) select.value = "";
  });
}

// Search-as-you-type picker over contacts (C-07 manager, L-02 add member).
function initPicker(root, { input, hidden, list, exclude, clear }) {
  if (!input || !hidden || !list) return;
  let timer = null;
  let active = -1;
  let options = [];

  const close = () => {
    list.hidden = true;
    input.setAttribute("aria-expanded", "false");
    active = -1;
  };
  const choose = (item) => {
    hidden.value = String(item.id);
    input.value = item.display_name;
    close();
  };
  const highlight = (index) => {
    $$("li", list).forEach((li, i) => li.setAttribute("aria-selected", String(i === index)));
    active = index;
  };
  const render = (items) => {
    options = items;
    list.replaceChildren();
    items.forEach((item, i) => {
      const li = document.createElement("li");
      li.setAttribute("role", "option");
      li.id = `${list.id}-${i}`;
      const name = document.createElement("strong");
      name.textContent = item.display_name;
      li.appendChild(name);
      const detail = [item.title, item.team, item.company].filter(Boolean).join(" · ");
      if (detail) {
        const span = document.createElement("span");
        span.textContent = ` ${detail}`;
        li.appendChild(span);
      }
      li.addEventListener("mousedown", (e) => {
        e.preventDefault();
        choose(item);
      });
      list.appendChild(li);
    });
    if (!items.length) {
      const li = document.createElement("li");
      li.className = "none";
      li.textContent = "No matches";
      list.appendChild(li);
    }
    list.hidden = false;
    input.setAttribute("aria-expanded", "true");
    highlight(items.length ? 0 : -1);
  };
  const lookup = async () => {
    const q = input.value.trim();
    if (!q) {
      close();
      return;
    }
    const params = new URLSearchParams({ q });
    if (exclude) params.set("exclude", exclude);
    const response = await fetch(`/api/contacts/lookup?${params}`);
    if (response.ok) render(await response.json());
  };

  input.addEventListener("input", () => {
    hidden.value = ""; // typing clears the selection until a suggestion is chosen
    clearTimeout(timer);
    timer = setTimeout(lookup, 150);
  });
  input.addEventListener("keydown", (e) => {
    if (list.hidden) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      highlight(Math.min(active + 1, options.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      highlight(Math.max(active - 1, 0));
    } else if (e.key === "Enter" && active >= 0) {
      e.preventDefault();
      choose(options[active]);
    } else if (e.key === "Escape") {
      close();
    }
  });
  input.addEventListener("blur", () => setTimeout(close, 100));
  if (clear) {
    clear.addEventListener("click", () => {
      hidden.value = "";
      input.value = "";
      input.focus();
    });
  }
}
