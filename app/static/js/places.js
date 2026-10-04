// Local time (C-23), directions (M-06) and the contact map (S-13), ADR-0023.
// Served from this origin (CSP, N-04). The map needs the vendored Leaflet, loaded on its page.
"use strict";

(() => {
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

  // ------------------------------------------------------------------ local time (C-23)

  const REACH = { work: "Working hours", edge: "Early or late", weekend: "Weekend", night: "Night" };

  const partsIn = (zone, date) => {
    const parts = {};
    new Intl.DateTimeFormat("en-US", {
      timeZone: zone, hourCycle: "h23", weekday: "short", year: "numeric", month: "2-digit",
      day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit",
    }).formatToParts(date).forEach((p) => { parts[p.type] = p.value; });
    return parts;
  };

  // Minutes the zone is ahead of UTC at this moment.
  const offsetMinutes = (zone, date) => {
    const p = partsIn(zone, date);
    const asUtc = Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour % 24, +p.minute, +p.second);
    return Math.round((asUtc - (date.getTime() - date.getMilliseconds())) / 60000);
  };

  const reachAt = (weekday, hour) => {
    if (weekday === "Sat" || weekday === "Sun") return hour >= 9 && hour < 21 ? "weekend" : "night";
    if (hour >= 9 && hour < 17) return "work";
    return (hour >= 8 && hour < 9) || (hour >= 17 && hour < 21) ? "edge" : "night";
  };

  const span = (minutes) => {
    const h = Math.floor(minutes / 60);
    const m = minutes % 60;
    const hours = h ? `${h} hour${h === 1 ? "" : "s"}` : "";
    const mins = m ? `${m} min` : "";
    return [hours, mins].filter(Boolean).join(" ");
  };

  const relative = (zone, now) => {
    const diff = offsetMinutes(zone, now) + now.getTimezoneOffset(); // theirs - mine
    if (diff === 0) return "same time as you";
    return `${span(Math.abs(diff))} ${diff > 0 ? "ahead of" : "behind"} you`;
  };

  const updateLocalTimes = () => {
    const now = new Date();
    $$("[data-local-time]").forEach((el) => {
      const zone = el.dataset.tz;
      try {
        const clock = new Intl.DateTimeFormat("en-US", { timeZone: zone, hour: "numeric", minute: "2-digit" });
        const abbr = new Intl.DateTimeFormat("en-US", { timeZone: zone, timeZoneName: "short" })
          .formatToParts(now).find((p) => p.type === "timeZoneName");
        const p = partsIn(zone, now);
        const reach = reachAt(p.weekday, +p.hour % 24);
        $("[data-clock]", el).textContent = clock.format(now);
        if (abbr) $("[data-tz-abbr]", el).textContent = abbr.value;
        const dot = $("[data-reach]", el);
        dot.className = `reach reach-${reach}`;
        $("[data-reach-label]", el).textContent = REACH[reach];
        const off = $("[data-tz-offset]", el);
        if (off) off.textContent = ` · ${relative(zone, now)}`;
      } catch { /* an unknown zone: keep what the server rendered */ }
    });
  };

  // ------------------------------------------------------------------ directions (M-06)

  const MAX_STOPS = 11; // Google in a desktop browser: origin + 9 waypoints + destination

  const directionsUrl = (stops, provider) => {
    if (provider === "apple" && stops.length <= 2) {
      const q = new URLSearchParams();
      if (stops.length === 2) q.set("saddr", stops[0]);
      q.set("daddr", stops[stops.length - 1]);
      q.set("dirflg", "d");
      return `https://maps.apple.com/?${q}`;
    }
    const q = new URLSearchParams({ api: "1" });
    if (stops.length >= 2) q.set("origin", stops[0]);
    q.set("destination", stops[stops.length - 1]);
    q.set("travelmode", "driving");
    if (stops.length > 2) q.set("waypoints", stops.slice(1, -1).join("|"));
    return `https://www.google.com/maps/dir/?${q}`;
  };

  const initSelectionPlaces = () => {
    const bar = $("[data-action-bar]");
    if (!bar) return;
    const status = $("[data-action-status]", bar);
    const people = () => [...(bar.selection || new Map()).entries()];

    const mapLink = $("[data-map-selection]", bar);
    if (mapLink) {
      mapLink.addEventListener("click", () => {
        const ids = people().map(([id]) => id).join(",");
        mapLink.href = `/?view=map&ids=${encodeURIComponent(ids)}`;
      });
    }
    const button = $("[data-directions]", bar);
    if (!button) return;
    button.addEventListener("click", () => {
      const chosen = people().map(([, p]) => p);
      const withAddress = chosen.filter((p) => p.address);
      const missing = chosen.filter((p) => !p.address).map((p) => p.name);
      const note = missing.length ? ` · ${missing.length} without an address left out: ${missing.join(", ")}` : "";
      if (!withAddress.length) {
        status.textContent = `Nobody selected has an address${note}`;
        return;
      }
      if (withAddress.length > MAX_STOPS) {
        status.textContent = `A route can have at most ${MAX_STOPS} stops; ${withAddress.length} people with an address are selected.`;
        return;
      }
      const provider = withAddress.length > 2 ? "google" : bar.dataset.mapsProvider || "google";
      const url = directionsUrl(withAddress.map((p) => p.address), provider);
      window.open(url, "_blank", "noopener,noreferrer");
      const what = withAddress.length === 1 ? `Directions to ${withAddress[0].name} from where you are`
        : withAddress.length === 2 ? `Directions from ${withAddress[0].name} to ${withAddress[1].name}`
        : `A route through ${withAddress.length} stops, in the order you chose them (a phone shows the first 5)`;
      status.textContent = `${what}${note}`;
    });
  };

  // ------------------------------------------------------------------ the map (S-13)

  // Tokens use light-dark(), which SVG understands but canvas does not (it falls back to
  // black), so read the colour the browser actually resolves for the current theme.
  const cssVar = (name, fallback) => {
    if (!getComputedStyle(document.documentElement).getPropertyValue(name).trim()) return fallback;
    const probe = document.createElement("span");
    probe.style.color = `var(${name})`;
    document.body.appendChild(probe);
    const colour = getComputedStyle(probe).color;
    probe.remove();
    return colour || fallback;
  };

  const element = (tag, attrs = {}, text = "") => {
    const el = document.createElement(tag);
    Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, v));
    if (text) el.textContent = text;
    return el;
  };

  const popupFor = (p) => {
    const box = element("div", { class: "map-popup" });
    const name = element("a", { href: p.url }, p.name);
    box.append(element("p", { class: "map-popup-name" }));
    box.lastChild.append(name);
    const where = [p.label && `${p.label[0].toUpperCase()}${p.label.slice(1)}`, p.place].filter(Boolean).join(" · ");
    if (where) box.append(element("p", { class: "muted" }, where));
    if (p.time) box.append(element("p", {}, `Local time ${p.time}`));
    if (p.directions) {
      box.append(element("p"));
      box.lastChild.append(element("a", { href: p.directions, target: "_blank", rel: "noopener noreferrer" }, "Directions from here"));
    }
    return box;
  };

  const initMap = async () => {
    const el = $("[data-map]");
    if (!el || !window.L || !window.topojson) return;
    const status = $("[data-map-status]");
    const L = window.L;
    const map = L.map(el, { zoomSnap: 0.5, minZoom: 2, maxZoom: 13, worldCopyJump: true });
    map.attributionControl.setPrefix("Leaflet");
    map.setView([39.5, -98.35], 4);

    const [world, states] = await Promise.all([
      fetch("/static/vendor/geo/countries-110m.json").then((r) => r.json()),
      fetch("/static/vendor/geo/states-10m.json").then((r) => r.json()),
    ]);
    const land = cssVar("--map-land", "#eef1f4");
    const line = cssVar("--map-line", "#9aa5b1");
    const fill = cssVar("--accent", "#0b5cad");
    let counts = { states: {}, countries: {} };
    const shade = (n, max) => (n ? 0.15 + 0.55 * Math.sqrt(n / Math.max(1, max)) : 0);

    const countryLayer = L.geoJSON(window.topojson.feature(world, world.objects.countries), {
      style: (f) => {
        const n = counts.countries[String(Number(f.id))] || 0;
        const max = Math.max(1, ...Object.values(counts.countries));
        const us = String(Number(f.id)) === "840";
        return { color: line, weight: 0.6, fillColor: n && !us ? fill : land, fillOpacity: n && !us ? shade(n, max) : 1 };
      },
      onEachFeature: (f, layer) => layer.bindTooltip(() => {
        const n = counts.countries[String(Number(f.id))] || 0;
        return `${f.properties.name}${n ? ` · ${n} ${n === 1 ? "person" : "people"}` : ""}`;
      }, { sticky: true }),
    }).addTo(map);
    const stateLayer = L.geoJSON(window.topojson.feature(states, states.objects.states), {
      style: (f) => {
        const n = counts.states[f.properties.name] || 0;
        const max = Math.max(1, ...Object.values(counts.states));
        return { color: line, weight: 0.8, fillColor: n ? fill : land, fillOpacity: n ? shade(n, max) : 1 };
      },
      onEachFeature: (f, layer) => {
        layer.bindTooltip(() => {
          const n = counts.states[f.properties.name] || 0;
          return `${f.properties.name} · ${n} ${n === 1 ? "person" : "people"}`;
        }, { sticky: true });
        layer.on("click", () => map.fitBounds(layer.getBounds(), { padding: [20, 20] }));
      },
    }).addTo(map);

    const clusters = L.markerClusterGroup({
      showCoverageOnHover: false,
      maxClusterRadius: 40,
      iconCreateFunction: (cluster) => L.divIcon({
        html: `<span>${cluster.getChildCount()}</span>`, className: "map-cluster", iconSize: [34, 34],
      }),
    }).addTo(map);
    const nearLayer = L.layerGroup().addTo(map); // S-14: the "near" circle and its centre

    // County outlines for orientation once zoomed in (0.8 MB, so fetched on first need and
    // drawn on a canvas: 3,000+ shapes are too many for SVG).
    const COUNTY_ZOOM = 6;
    const stateNames = {};
    states.objects.states.geometries.forEach((g) => { stateNames[g.id] = g.properties.name; });
    let countyLayer = null;
    let countyData = null;
    const showCounties = async () => {
      const wanted = map.getZoom() >= COUNTY_ZOOM;
      if (!wanted) {
        if (countyLayer && map.hasLayer(countyLayer)) map.removeLayer(countyLayer);
        return;
      }
      if (!countyLayer) {
        countyData = countyData || fetch("/static/vendor/geo/counties-10m.json").then((r) => r.json());
        const topo = await countyData;
        if (countyLayer) return; // another zoom got here first
        // Leaflet stacks canvases under SVG, so the counties get a pane of their own above the
        // shaded states; otherwise they show only mid-pan and vanish when the states redraw.
        map.createPane("counties").style.zIndex = 450;
        countyLayer = L.geoJSON(window.topojson.feature(topo, topo.objects.counties), {
          pane: "counties",
          renderer: L.canvas({ padding: 0.5, pane: "counties" }),
          style: { color: line, weight: 0.6, opacity: 0.9, fill: true, fillOpacity: 0 },
          // The counties now sit over the states, so their tooltip carries the state's count too.
          onEachFeature: (f, layer) => layer.bindTooltip(() => {
            const state = stateNames[String(f.id).slice(0, 2)] || "";
            const n = counts.states[state] || 0;
            return `${f.properties.name} · ${state} · ${n} ${n === 1 ? "person" : "people"}`;
          }, { sticky: true }),
        });
      }
      if (map.getZoom() >= COUNTY_ZOOM && !map.hasLayer(countyLayer)) countyLayer.addTo(map);
    };
    map.on("zoomend", () => { showCounties(); });

    const form = $("[data-search-form]");
    const dataUrl = () => {
      if (!form) return el.dataset.mapSrc;
      const q = new URLSearchParams(new FormData(form));
      [...q.keys()].forEach((k) => { if (!q.get(k)) q.delete(k); });
      q.set("view", "map");
      const addr = new URLSearchParams(window.location.search).get("addr");
      if (addr) q.set("addr", addr);
      return `/map/data?${q}`;
    };

    let first = true;
    const load = async () => {
      status.textContent = "Loading the map…";
      const data = await fetch(dataUrl(), { headers: { Accept: "application/json" } }).then((r) => r.json());
      counts = { states: data.states, countries: data.countries };
      stateLayer.setStyle(stateLayer.options.style);
      countryLayer.setStyle(countryLayer.options.style);
      clusters.clearLayers();
      const markers = data.points.map((p) => L.marker([p.lat, p.lon], {
        icon: L.divIcon({ className: `map-dot precision-${p.precision}`, iconSize: [14, 14] }),
        title: p.name,
        keyboard: true,
      }).bindPopup(() => popupFor(p)));
      clusters.addLayers(markers);
      nearLayer.clearLayers();
      if (data.near) {
        const centre = [data.near.lat, data.near.lon];
        L.circle(centre, { radius: data.near.miles * 1609.34, color: fill, weight: 1.5, fillOpacity: 0.04, dashArray: "4 4", interactive: false }).addTo(nearLayer);
        L.marker(centre, { icon: L.divIcon({ className: "map-centre", iconSize: [12, 12] }), interactive: false })
          .bindTooltip(`${data.near.label} · ${data.near.miles} mi`, { permanent: true, direction: "top", offset: [0, -8], className: "map-centre-label" })
          .addTo(nearLayer);
      }
      const placed = new Set(data.points.map((p) => p.id)).size;
      status.textContent = `${data.people} ${data.people === 1 ? "person" : "people"} · ${placed} on the map`;
      if (data.unplaced) {
        const q = new URLSearchParams(dataUrl().split("?")[1]);
        q.delete("view");
        q.set("unplaced", "1");
        status.append(" · ");
        status.append(element("a", { href: `/?${q}`, "data-testid": "map-unplaced", title: "No address, or one without a ZIP, city or state" }, `${data.unplaced} not on the map`));
      }
      if (first && data.near) {
        map.fitBounds(L.latLng(data.near.lat, data.near.lon).toBounds(data.near.miles * 2 * 1609.34), { padding: [20, 20] });
      } else if (first && markers.length) {
        map.fitBounds(L.featureGroup(markers).getBounds(), { padding: [30, 30], maxZoom: 9 });
      }
      first = false;
    };
    await load();
    await showCounties();
    document.addEventListener("results:updated", () => { load(); });
  };

  let pending = null;
  const soon = () => { clearTimeout(pending); pending = setTimeout(updateLocalTimes, 50); };

  document.addEventListener("DOMContentLoaded", () => {
    initSelectionPlaces();
    initMap().catch(() => {
      const status = $("[data-map-status]");
      if (status) status.textContent = "The map could not be drawn.";
    });
    updateLocalTimes();
    setInterval(updateLocalTimes, 30000);
    // Live search and the preview pane add new times; our own clock updates are not new.
    new MutationObserver((records) => {
      const added = records.some((r) => [...r.addedNodes].some((n) =>
        n.nodeType === 1 && !n.closest("[data-local-time]") &&
        (n.matches("[data-local-time]") || n.querySelector("[data-local-time]"))));
      if (added) soon();
    }).observe(document.body, { childList: true, subtree: true });
  });
})();
