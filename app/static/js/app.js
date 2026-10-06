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
  initPresenting();
  initPalette();
  initShortcuts();
  initFilterChips();
  initMultiChips();
  initPhotoView();
  initThemeSwitch();
  initLogPrompt();
  initSearch();
  initSelection();
  initImportReview();
  initPreview();
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
  const selected = new Map(); // id -> {email, name, address}; survives live-search refreshes
  // places.js reads it for "Show on map" and Directions (S-13, M-06), in the order chosen.
  bar.selection = selected;
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
    if (on) {
      selected.set(id, {
        email: row.dataset.email || "", name: row.dataset.name || "", address: row.dataset.address || "",
        slack: row.dataset.slack || "",
      });
    }
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

  // N-09: "c" copies the selected people's emails (outside text fields).
  document.addEventListener("keydown", (e) => {
    if (e.key !== "c" || e.ctrlKey || e.metaKey || e.altKey || e.shiftKey || selected.size === 0) return;
    if (e.target.closest("textarea, select, [contenteditable], input:not([type=checkbox])")) return;
    e.preventDefault();
    $("[data-copy-emails]", bar).click();
  });

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
  // P-06: while presenting only work addresses reach the page; say how many were left out.
  const presentingNow = document.body.classList.contains("is-presenting");
  const skippedNote = (skipped) =>
    !skipped.length ? ""
      : presentingNow ? ` · ${skipped.length} left out (no work address): ${skipped.join(", ")}`
      : ` · ${skipped.length} skipped (no email): ${skipped.join(", ")}`;
  const nobody = presentingNow ? "Nobody selected has a work email address" : "Nobody selected has an email address";

  // ---- copy emails (M-02, ADR-0009)
  const CLIENTS = { outlook: { sep: "; ", label: "Outlook" }, gmail: { sep: ", ", label: "Gmail" } };
  const copyMenu = $("[data-copy-menu]", bar);

  const copy = async (clientKey) => {
    const { emails, skipped } = recipients();
    closeMenus();
    if (!emails.length) {
      say(`${nobody}${skippedNote(skipped)}`);
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

  // ---- copy Slack handles (M-07, ADR-0029): Slack has no group-message link, so paste them there
  $("[data-copy-slack]", bar).addEventListener("click", async () => {
    const people = [...selected.values()];
    const handles = [...new Set(people.filter((p) => p.slack).map((p) => p.slack))];
    const skipped = people.filter((p) => !p.slack).map((p) => p.name);
    const note = skipped.length ? ` · ${skipped.length} skipped (no Slack handle): ${skipped.join(", ")}` : "";
    closeMenus();
    if (!handles.length) {
      say(`Nobody selected has a Slack handle${note}`);
      return;
    }
    const text = handles.join(", ");
    const what = `${handles.length} Slack handle${handles.length === 1 ? "" : "s"}`;
    try {
      await navigator.clipboard.writeText(text);
      fallback.hidden = true;
      say(`Copied ${what}${note}`);
    } catch {
      // N-07: no clipboard access, so show the text ready to copy by hand.
      fallbackText.value = text;
      fallback.hidden = false;
      fallbackText.focus();
      fallbackText.select();
      say(`Select and copy ${what}${note}`);
    }
  });

  // ---- compose (M-03, ADR-0009, N-08)
  const composeMenu = $("[data-compose-menu]", bar);
  $("[data-compose]", bar).addEventListener("click", () => openMenu(composeMenu));
  $$("[data-compose-in]", bar).forEach((button) =>
    button.addEventListener("click", () => {
      const { emails, skipped } = recipients();
      closeMenus();
      if (!emails.length) {
        say(`${nobody}${skippedNote(skipped)}`);
        return;
      }
      const field = ($('input[name="compose_field"]:checked', bar) || { value: "to" }).value;
      const url = composeUrl(button.dataset.composeIn, emails, field);
      if (button.dataset.composeIn === "teams" && emails.length > 250) {
        say("Teams group chats hold at most 250 people.");
        return;
      }
      const limit = button.dataset.composeIn === "mailto" ? 2000 : 8000;
      if (url.length > limit) {
        say(`Too many recipients for a link (${emails.length}). Use Copy emails instead.`);
        return;
      }
      store.set("contacts.composeClient", button.dataset.composeIn);
      if (button.dataset.composeIn === "mailto") window.location.href = url;
      else window.open(url, "_blank", "noopener,noreferrer");
      const what = button.dataset.composeIn === "teams" ? "a Teams chat with" : "a new email to";
      say(`Opening ${what} ${emails.length} ${emails.length === 1 ? "person" : "people"}${skippedNote(skipped)}`);
      // C-17: offer to log the email (or Teams message) for everyone who received it.
      const reached = [...selected.entries()].filter(([, p]) => p.email);
      document.dispatchEvent(new CustomEvent("compose:opened", {
        detail: {
          ids: reached.map(([id]) => id),
          names: reached.map(([, p]) => p.name),
          kind: button.dataset.composeIn === "teams" ? "message" : "email",
        },
      }));
    }),
  );

  sync();
}

function composeUrl(client, emails, field) {
  const enc = (list, sep) => list.map(encodeURIComponent).join(sep);
  if (client === "teams") {
    // M-05: Teams group chat with everyone selected (To/Cc does not apply).
    return `https://teams.microsoft.com/l/chat/0/0?users=${enc(emails, ",")}`;
  }
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

// ------------------------------------------------------------------ theme switch (A-01, ADR-0015)

// The header switch is an ordinary form that works without JavaScript. Here it applies the
// choice at once and saves it in the background; if saving fails, the form posts normally.
function initThemeSwitch() {
  const form = $("[data-theme-switch]");
  if (!form) return;
  form.addEventListener("change", async (e) => {
    const input = e.target;
    if (!(input instanceof HTMLInputElement) || input.name !== "theme") return;
    document.documentElement.dataset.theme = input.value;
    try {
      const res = await fetch(form.action, {
        method: "POST",
        body: new FormData(form),
        headers: { Accept: "application/json" },
        credentials: "same-origin",
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
    } catch {
      form.submit();
    }
  });
}

// ------------------------------------------------------------------ log prompt (C-17, ADR-0016)

// After Email or Call opens the mail or phone app, offer to log the interaction in one click,
// so keep-in-touch reminders count from it. Without JavaScript the prompt simply never shows.
function initLogPrompt() {
  const form = $("[data-log-prompt]");
  if (!form) return;
  const text = $("[data-log-prompt-text]", form);
  const setPeople = (ids) => {
    $$('input[name="contact_ids"]', form).forEach((i) => i.remove());
    ids.forEach((id) => {
      const hidden = document.createElement("input");
      hidden.type = "hidden";
      hidden.name = "contact_ids";
      hidden.value = id;
      form.appendChild(hidden);
    });
  };
  document.addEventListener("compose:opened", (e) => {
    const { ids, names, kind } = e.detail;
    if (!ids.length) return;
    const message = kind === "message";
    setPeople(ids);
    form.action = "/selection/log";
    $("[data-log-prompt-kind]", form).value = kind;
    $("[data-log-prompt-summary]", form).value = message ? "Messaged on Teams" : "Emailed";
    const who = ids.length === 1 ? names[0] : `${ids.length} people`;
    text.textContent = `Log ${message ? "a Teams message" : "an email"} with ${who} today?`;
    form.hidden = false;
  });
  document.addEventListener("click", (e) => {
    const link = e.target.closest("a[data-log-kind]");
    if (!link || !/^\d+$/.test(link.dataset.logContact || "")) return;
    const call = link.dataset.logKind === "call";
    setPeople([]);
    form.action = `/contacts/${link.dataset.logContact}/activities`;
    $("[data-log-prompt-kind]", form).value = call ? "call" : "email";
    $("[data-log-prompt-summary]", form).value = call ? "Called" : "Emailed";
    text.textContent = `Log ${call ? "a call" : "an email"} with ${link.dataset.logName} today?`;
    form.hidden = false;
  });
  $("[data-log-prompt-dismiss]", form).addEventListener("click", () => {
    form.hidden = true;
  });
}

// ------------------------------------------------------------------ presenting mode (P-01)

function initPresenting() {
  // ⇧P anywhere outside a text field turns presenting on or off (the header form does the work).
  document.addEventListener("keydown", (e) => {
    if (e.key !== "P" || !e.shiftKey || e.ctrlKey || e.metaKey || e.altKey || e.repeat) return;
    if (e.target.closest("input, textarea, select, [contenteditable]")) return;
    const form = $("[data-present-form]");
    if (!form) return;
    e.preventDefault();
    form.requestSubmit();
  });
}

// ------------------------------------------------------------------ preview pane (S-02, ADR-0015)

// On wide screens a chosen result opens in the preview pane instead of navigating; choosing it
// again (or "Open full card") opens the card. Narrow screens and modified clicks navigate as usual.
function initPreview() {
  const layout = $("[data-search-layout]");
  const pane = $("[data-preview-pane]");
  const results = $("[data-results]");
  if (!layout || !pane || !results) return;
  const wide = window.matchMedia("(min-width: 62.5rem)");
  const empty = pane.innerHTML;
  let current = null;
  let generation = 0;

  const enable = () => {
    pane.hidden = !wide.matches;
    layout.classList.toggle("with-preview", wide.matches);
  };
  enable();
  wide.addEventListener("change", enable);

  const mark = () => {
    $$("[data-contact-id]", results).forEach((row) => {
      const on = row.dataset.contactId === current;
      row.classList.toggle("previewing", on);
      const link = $("[data-preview-link]", row);
      if (link && on) link.setAttribute("aria-current", "true");
      else if (link) link.removeAttribute("aria-current");
    });
  };

  const show = async (id) => {
    if (id === current) return;
    current = id;
    mark();
    const mine = ++generation;
    const response = await fetch(`/contacts/${id}/preview`, { headers: { Accept: "text/html" } });
    if (mine !== generation) return; // a newer choice is on its way
    if (!response.ok) {
      pane.innerHTML = empty;
      current = null;
      mark();
      return;
    }
    pane.innerHTML = await response.text();
    pane.scrollTop = 0;
  };
  const rowId = (link) => link.closest("[data-contact-id]").dataset.contactId;

  results.addEventListener("click", (e) => {
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    let link = e.target.closest("a[data-preview-link]");
    if (!link) {
      // A click anywhere else on a result card (not its checkbox or another link) acts on the name.
      const card = e.target.closest(".result-card");
      if (!card || e.target.closest("a, input, button, label, select")) return;
      link = $("a[data-preview-link]", card);
      if (!link) return;
      if (!wide.matches || rowId(link) === current) {
        window.location.assign(link.href);
        return;
      }
    }
    if (!wide.matches) return;
    if (rowId(link) === current) return; // already previewed: open the card
    e.preventDefault();
    link.focus({ preventScroll: true }); // so ↑ ↓ carry on from here (Safari doesn't focus links on click)
    show(rowId(link));
  });

  // N-09: ↓ from the search box or ↑ ↓ on a name move between people, previewing each;
  // space selects the person for Copy emails and the other bulk actions.
  const links = () => $$("a[data-preview-link]", results);
  const go = (link) => {
    if (!link) return;
    link.focus();
    if (wide.matches) show(rowId(link));
  };
  const input = $("[data-search-input]");
  if (input) {
    input.addEventListener("keydown", (e) => {
      if (e.key !== "ArrowDown") return;
      e.preventDefault();
      go(links()[0]);
    });
  }
  // ↑ ↓ also work after clicking a card, from its checkbox, or with nothing focused.
  document.addEventListener("keydown", (e) => {
    if ((e.key !== "ArrowDown" && e.key !== "ArrowUp") || e.altKey || e.ctrlKey || e.metaKey) return;
    if (e.target.closest("a[data-preview-link]") || typingIn(e.target)) return;
    if (document.querySelector("dialog[open]")) return;
    const inResults = results.contains(e.target);
    if (!inResults && e.target !== document.body && e.target !== document.documentElement) return;
    const all = links();
    if (!all.length) return;
    const card = e.target.closest("[data-contact-id]");
    const from = card ? card.dataset.contactId : current;
    const i = all.findIndex((l) => rowId(l) === from);
    e.preventDefault();
    if (i === -1) go(all[e.key === "ArrowDown" ? 0 : all.length - 1]);
    else go(all[Math.min(all.length - 1, Math.max(0, i + (e.key === "ArrowDown" ? 1 : -1)))]);
  });
  results.addEventListener("keydown", (e) => {
    const link = e.target.closest("a[data-preview-link]");
    if (!link) return;
    const all = links();
    const i = all.indexOf(link);
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (e.key === "ArrowUp" && i === 0 && input) input.focus();
      else go(all[i + (e.key === "ArrowDown" ? 1 : -1)]);
    } else if (e.key === " ") {
      e.preventDefault();
      const box = $(".select-contact", link.closest("[data-contact-id]"));
      if (box) box.click();
    }
  });
  document.addEventListener("results:updated", mark);

  // "More filters" is a small popover: a click elsewhere or Escape closes it.
  const more = $("[data-more-filters]");
  if (more) {
    document.addEventListener("click", (e) => { if (!more.contains(e.target)) more.open = false; });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && more.open) {
        more.open = false;
        $("summary", more).focus();
      }
    });
  }
}

// ------------------------------------------------------------------ filter chips (S-04, ADR-0017)

// A chosen filter chip shows a ×; it clears the filter. Without JavaScript the × submits
// clear=<filter> and the server drops that filter.
function initFilterChips() {
  $$("[data-chip]").forEach((chip) => {
    const select = $("select", chip);
    const clear = $("[data-chip-clear]", chip);
    if (!select || !clear) return;
    const sync = () => {
      const on = select.value !== "";
      chip.classList.toggle("on", on);
      clear.hidden = !on;
    };
    select.addEventListener("change", sync);
    clear.addEventListener("click", (e) => {
      e.preventDefault();
      select.value = "";
      sync();
      select.dispatchEvent(new Event("change", { bubbles: true }));
      select.focus();
    });
  });
}

// S-15: Company, Team, Tag and List chips hold several values. Each is a popover of checkboxes
// that works without JavaScript; this keeps the summary and × in step, adds a find box to long
// lists, and closes the popover on a click elsewhere or Escape.
function initMultiChips() {
  const chips = $$("[data-multi]");
  chips.forEach((chip) => {
    const details = $("[data-multi-details]", chip);
    const summary = $("[data-multi-summary]", chip);
    const clear = $("[data-chip-clear]", chip);
    const options = $("[data-multi-options]", chip);
    const label = chip.dataset.label;
    const boxes = () => $$('[data-multi-options] input[type="checkbox"]', chip);
    const sync = () => {
      const names = boxes().filter((box) => box.checked).map((box) => box.dataset.name || box.value);
      const text = names.length === 0 ? label
        : names.length === 1 ? `${label}: ${names[0]}` : `${label}: ${names.length} selected`;
      summary.textContent = text;
      summary.title = names.join(", ");
      chip.classList.toggle("on", names.length > 0);
      summary.classList.toggle("on", names.length > 0);
      clear.hidden = names.length === 0;
    };
    chip.addEventListener("change", (e) => { if (e.target.matches('input[type="checkbox"]')) sync(); });
    clear.addEventListener("click", (e) => {
      e.preventDefault();
      boxes().forEach((box) => { box.checked = false; });
      sync();
      details.open = false;
      options.dispatchEvent(new Event("change", { bubbles: true }));
      summary.focus();
    });
    { // a find box: type to narrow a long list (over 100 companies), then tick what you want
      const find = document.createElement("input");
      find.type = "search";
      find.className = "multi-find";
      find.placeholder = `Type to find a ${label.toLowerCase()}…`;
      find.autocomplete = "off";
      find.setAttribute("aria-label", `Find a ${label.toLowerCase()}`);
      const none = document.createElement("li");
      none.className = "muted small multi-none";
      none.textContent = "No matches";
      none.hidden = true;
      options.append(none);
      const narrow = () => {
        const needle = find.value.trim().toLowerCase();
        let shown = 0;
        $$("li:not(.multi-none)", options).forEach((li) => {
          const hide = needle !== "" && !li.textContent.toLowerCase().includes(needle);
          li.hidden = hide;
          if (!hide) shown += 1;
        });
        none.hidden = shown > 0;
      };
      find.addEventListener("input", narrow);
      find.addEventListener("keydown", (e) => {
        if (e.key === "Enter") e.preventDefault(); // Enter must not submit the whole form
        if (e.key === "Escape" && find.value) { e.stopPropagation(); find.value = ""; narrow(); }
      });
      details.addEventListener("toggle", () => { if (!details.open) { find.value = ""; narrow(); } });
      options.before(find);
    }
    details.addEventListener("toggle", () => {
      if (!details.open) return;
      chips.forEach((other) => { const d = $("[data-multi-details]", other); if (d !== details) d.open = false; });
      const find = $(".multi-find", chip);
      if (find) find.focus();
    });
  });
  document.addEventListener("click", (e) => {
    chips.forEach((chip) => { const d = $("[data-multi-details]", chip); if (d.open && !chip.contains(e.target)) d.open = false; });
  });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    const open = chips.find((chip) => $("[data-multi-details]", chip).open);
    if (!open) return;
    $("[data-multi-details]", open).open = false;
    $("[data-multi-summary]", open).focus();
  });
}

// ------------------------------------------------------------------ photo view (C-24)

function initPhotoView() {
  const dialog = $("[data-photo-view]");
  if (!dialog || typeof dialog.showModal !== "function") return;
  const fill = (selector, text) => {
    const node = $(selector, dialog);
    node.textContent = text || "";
    node.hidden = !text;
  };
  // Capture phase: a photo sits inside a result row and a preview, whose own clicks must not run.
  document.addEventListener("click", (e) => {
    const trigger = e.target.closest("[data-photo-zoom]");
    if (!trigger) return;
    e.preventDefault();
    e.stopPropagation();
    const img = $("[data-photo-view-img]", dialog);
    img.src = trigger.dataset.photoSrc;
    img.alt = `Photo of ${trigger.dataset.name}`;
    fill("[data-photo-view-name]", trigger.dataset.name);
    fill("[data-photo-view-title]", trigger.dataset.title);
    fill("[data-photo-view-company]", trigger.dataset.company);
    dialog.showModal();
  }, true);
  dialog.addEventListener("click", (e) => { if (e.target === dialog) dialog.close(); }); // backdrop
  dialog.addEventListener("close", () => { $("[data-photo-view-img]", dialog).removeAttribute("src"); });
}

// ------------------------------------------------------------------ shortcuts (N-09) and palette (S-12)

const isMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
const typingIn = (target) =>
  Boolean(target.closest && target.closest("input:not([type=checkbox]):not([type=radio]), textarea, select, [contenteditable]"));

function initShortcuts() {
  const dialog = $("[data-shortcuts]");
  if (!dialog) return;
  document.addEventListener("keydown", (e) => {
    if (e.key !== "?" || e.ctrlKey || e.metaKey || e.altKey || typingIn(e.target)) return;
    if (document.querySelector("dialog[open]")) return;
    e.preventDefault();
    dialog.showModal();
  });
}

function initPalette() {
  const dialog = $("[data-cmdk]");
  if (!dialog) return;
  const input = $("[data-palette-input]", dialog);
  const list = $("[data-palette-list]", dialog);
  const actions = $$("[data-palette-actions] li", dialog).map((li) => ({
    label: li.textContent.trim(),
    html: li.innerHTML,
    words: `${li.textContent} ${li.dataset.words || ""}`.toLowerCase(),
    href: li.dataset.href,
    action: li.dataset.action,
  }));
  if (isMac) $$("[data-palette-key]").forEach((k) => { k.textContent = "⌘ K"; });

  let items = [];
  let active = 0;
  let generation = 0;
  let timer = null;

  const esc = (text) => String(text).replace(/[&<>"']/g, (ch) => `&#${ch.charCodeAt(0)};`);
  const render = () => {
    list.innerHTML = "";
    let group = null;
    items.forEach((item, i) => {
      if (item.group !== group) {
        group = item.group;
        const head = document.createElement("li");
        head.className = "palette-group";
        head.setAttribute("role", "presentation");
        head.textContent = group;
        list.appendChild(head);
      }
      const li = document.createElement("li");
      li.id = `palette-item-${i}`;
      li.className = "palette-item";
      li.setAttribute("role", "option");
      li.setAttribute("aria-selected", i === active ? "true" : "false");
      li.dataset.index = String(i);
      li.innerHTML = item.html || `<span>${esc(item.label)}</span>${item.sub ? ` <span class="muted small">${esc(item.sub)}</span>` : ""}`;
      list.appendChild(li);
    });
    if (!items.length) {
      const none = document.createElement("li");
      none.className = "palette-empty muted";
      none.setAttribute("role", "presentation");
      none.textContent = "Nothing found.";
      list.appendChild(none);
    }
    input.setAttribute("aria-activedescendant", items.length ? `palette-item-${active}` : "");
    const current = $(`#palette-item-${active}`, list);
    if (current) current.scrollIntoView({ block: "nearest" });
  };

  const matchActions = (q) => {
    const words = q.toLowerCase().split(/\s+/).filter(Boolean);
    return actions
      .filter((a) => words.every((w) => a.words.includes(w)))
      .map((a) => ({ ...a, group: "Actions" }));
  };

  const update = async () => {
    const q = input.value.trim();
    const mine = ++generation;
    let found = [];
    if (q) {
      try {
        const response = await fetch(`/palette?q=${encodeURIComponent(q)}`, { headers: { Accept: "application/json" } });
        if (response.ok) {
          const data = await response.json();
          found = [
            ...data.people.map((p) => ({ label: p.name, sub: p.sub, href: p.url, group: "People" })),
            ...data.lists.map((l) => ({ label: l.name, href: l.url, group: "Lists" })),
            ...data.tags.map((t) => ({ label: t.name, sub: `${t.count} ${t.count === 1 ? "person" : "people"}`, href: t.url, group: "Tags" })),
            ...data.saved.map((s) => ({ label: s.name, href: s.url, group: "Saved searches" })),
          ];
        }
      } catch { /* offline: actions only */ }
    }
    if (mine !== generation) return;
    items = [
      ...found,
      ...matchActions(q),
      ...(q ? [{ label: `Search contacts for “${q}”`, href: `/?q=${encodeURIComponent(q)}`, group: "Search" }] : []),
    ];
    active = 0;
    render();
  };

  const run = (item) => {
    if (!item) return;
    dialog.close();
    if (item.href) {
      window.location.assign(item.href);
    } else if (item.action === "present") {
      const form = $("[data-present-form]");
      if (form) form.requestSubmit();
    } else if (item.action && item.action.startsWith("theme-")) {
      const radio = $(`[data-theme-switch] input[value="${item.action.slice(6)}"]`);
      if (radio) radio.click();
    } else if (item.action === "shortcuts") {
      const help = $("[data-shortcuts]");
      if (help) help.showModal();
    }
  };

  const open = () => {
    if (dialog.open) return;
    $$("dialog[open]").forEach((d) => d.close());
    input.value = "";
    items = matchActions("");
    active = 0;
    render();
    dialog.showModal();
    input.focus();
  };

  document.addEventListener("keydown", (e) => {
    if (e.key.toLowerCase() === "k" && (e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey) {
      e.preventDefault();
      if (dialog.open) dialog.close();
      else open();
    }
  });
  $$("[data-palette-open]").forEach((link) =>
    link.addEventListener("click", (e) => {
      e.preventDefault();
      open();
    }),
  );
  input.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(update, 90);
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!items.length) return;
      active = (active + (e.key === "ArrowDown" ? 1 : items.length - 1)) % items.length;
      render();
    } else if (e.key === "Enter") {
      e.preventDefault();
      run(items[active]);
    }
  });
  list.addEventListener("mousemove", (e) => {
    const li = e.target.closest("[data-index]");
    if (li && Number(li.dataset.index) !== active) {
      active = Number(li.dataset.index);
      render();
    }
  });
  list.addEventListener("click", (e) => {
    const li = e.target.closest("[data-index]");
    if (li) run(items[Number(li.dataset.index)]);
  });
  dialog.addEventListener("click", (e) => { if (e.target === dialog) dialog.close(); }); // backdrop
}

// D-07: import review. Keeps the "N selected" counts live and lets the header box tick the page.
// Without JavaScript the buttons under "Choose what to import" do the same on the server.
function initImportReview() {
  const form = $("[data-import-form]");
  if (!form) return;
  const elsewhere = Number(form.dataset.selectedElsewhere || 0);
  const boxes = () => $$(".import-pick", form).filter((box) => !box.disabled);
  const header = $("[data-import-page]", form);
  const sync = () => {
    const mine = boxes();
    const total = mine.filter((box) => box.checked).length + elsewhere;
    $$("[data-import-count]", form).forEach((el) => { el.textContent = String(total); });
    if (header) header.checked = mine.length > 0 && mine.every((box) => box.checked);
  };
  form.addEventListener("change", (e) => {
    if (e.target.matches("[data-import-page]")) {
      boxes().forEach((box) => { box.checked = e.target.checked; });
    }
    if (e.target.matches(".import-pick, [data-import-page]")) sync();
  });
  sync();
}
