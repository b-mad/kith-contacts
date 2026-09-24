// Small progressive enhancements. Served from this origin (CSP, N-04); no dependencies.
"use strict";

document.addEventListener("DOMContentLoaded", () => {
  // Filters submit when changed.
  document.querySelectorAll("form[data-autosubmit]").forEach((form) => {
    form.addEventListener("change", () => form.submit());
  });

  // Repeating email / phone rows.
  const renumberPrimary = (container) => {
    container.querySelectorAll('input[name="primary_email"]').forEach((radio, i) => {
      radio.value = String(i);
    });
  };
  document.querySelectorAll("[data-add-row]").forEach((button) => {
    button.addEventListener("click", () => {
      const kind = button.dataset.addRow;
      const container = document.querySelector(`[data-rows="${kind}"]`);
      const template = document.getElementById(`${kind}-row`);
      const row = template.content.firstElementChild.cloneNode(true);
      container.appendChild(row);
      renumberPrimary(container);
      if (!container.querySelector('input[name="primary_email"]:checked')) {
        const radio = row.querySelector('input[name="primary_email"]');
        if (radio) radio.checked = true;
      }
      row.querySelector("input").focus();
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

  // Manager picker: search-as-you-type over contacts (C-07).
  document.querySelectorAll("[data-manager-picker]").forEach((picker) => {
    const input = picker.querySelector('input[role="combobox"]');
    const hidden = picker.querySelector('input[name="manager_id"]');
    const list = picker.querySelector('[role="listbox"]');
    const exclude = picker.dataset.exclude;
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
      const items = list.querySelectorAll("li");
      items.forEach((li, i) => li.setAttribute("aria-selected", String(i === index)));
      active = index;
    };
    const render = (items) => {
      options = items;
      list.replaceChildren();
      items.forEach((item, i) => {
        const li = document.createElement("li");
        li.setAttribute("role", "option");
        li.id = `manager-option-${i}`;
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
      if (items.length === 0) {
        const li = document.createElement("li");
        li.className = "none";
        li.textContent = "No matches";
        list.appendChild(li);
      }
      list.hidden = false;
      input.setAttribute("aria-expanded", "true");
      highlight(items.length ? 0 : -1);
    };
    const search = async () => {
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
      timer = setTimeout(search, 150);
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
    picker.querySelector("[data-clear-manager]").addEventListener("click", () => {
      hidden.value = "";
      input.value = "";
      input.focus();
    });
  });
});
