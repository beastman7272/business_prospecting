// ── State ──────────────────────────────────────────────────────────────────
let map, centerMarker, radiusCircle;
const DEFAULT_CENTER_LAT = 33.749;
const DEFAULT_CENTER_LNG = -84.388;
const DEFAULT_RADIUS_MI = 5;
const DEFAULT_MAX_RESULTS = 25;
const DEFAULT_ZOOM = 12;
let centerLat = DEFAULT_CENTER_LAT, centerLng = DEFAULT_CENTER_LNG; // Default: Atlanta, GA
let currentPage = 1;
const pageSize = 25;
let searchResults = [];
let placeTypeOptions = [];
let selectedPrimaryTypes = [];
let visiblePrimaryTypeMatches = [];
let highlightedPrimaryTypeIndex = -1;

// ── Map init ───────────────────────────────────────────────────────────────
function initMap() {
  map = L.map("map").setView([centerLat, centerLng], DEFAULT_ZOOM);

  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "© OpenStreetMap contributors",
    maxZoom: 19,
  }).addTo(map);

  centerMarker = L.marker([centerLat, centerLng], { draggable: true }).addTo(map);
  radiusCircle = L.circle([centerLat, centerLng], { radius: milesToMeters(DEFAULT_RADIUS_MI), color: "#3b82f6", fillOpacity: 0.08 }).addTo(map);

  map.on("click", (e) => {
    centerLat = e.latlng.lat;
    centerLng = e.latlng.lng;
    centerMarker.setLatLng([centerLat, centerLng]);
    updateCircle();
  });

  centerMarker.on("dragend", (e) => {
    centerLat = e.target.getLatLng().lat;
    centerLng = e.target.getLatLng().lng;
    updateCircle();
  });
}

function milesToMeters(mi) { return mi * 1609.34; }

function normalizePrimaryType(value) {
  return (value || "").trim().toLowerCase().replace(/[-\s]+/g, "_");
}

function getPrimaryTypeInput() {
  return document.getElementById("primary-type-input");
}

function getPrimaryTypeMenu() {
  return document.getElementById("primary-type-suggestions");
}

function renderSelectedPrimaryTypes() {
  const container = document.getElementById("selected-primary-types");
  container.innerHTML = selectedPrimaryTypes.map((value) => {
    const option = placeTypeOptions.find((item) => item.value === value);
    const label = option?.label || value;
    return `
      <span class="multi-select-tag">
        ${label}
        <button type="button" aria-label="Remove ${label}" onclick="removePrimaryType('${value}')">×</button>
      </span>
    `;
  }).join("");
}

function getPrimaryTypeMatches(query = "") {
  const normalizedQuery = normalizePrimaryType(query);
  return placeTypeOptions
    .filter((option) => !selectedPrimaryTypes.includes(option.value))
    .filter((option) => {
      if (!normalizedQuery) return true;
      return option.value.includes(normalizedQuery) || option.label.toLowerCase().includes(query.toLowerCase());
    })
    .slice(0, 12);
}

function hidePrimaryTypeSuggestions() {
  getPrimaryTypeMenu().classList.add("hidden");
  visiblePrimaryTypeMatches = [];
  highlightedPrimaryTypeIndex = -1;
}

function renderPrimaryTypeSuggestions(query = getPrimaryTypeInput().value.trim()) {
  const menu = getPrimaryTypeMenu();
  visiblePrimaryTypeMatches = getPrimaryTypeMatches(query);

  if (!visiblePrimaryTypeMatches.length) {
    menu.innerHTML = query
      ? `<div class="multi-select-option-empty">No matching place types.</div>`
      : "";
    if (menu.innerHTML) {
      menu.classList.remove("hidden");
    } else {
      menu.classList.add("hidden");
    }
    highlightedPrimaryTypeIndex = -1;
    return;
  }

  if (highlightedPrimaryTypeIndex < 0 || highlightedPrimaryTypeIndex >= visiblePrimaryTypeMatches.length) {
    highlightedPrimaryTypeIndex = 0;
  }

  menu.innerHTML = visiblePrimaryTypeMatches.map((option, idx) => `
    <div
      class="multi-select-option ${idx === highlightedPrimaryTypeIndex ? "active" : ""}"
      data-value="${option.value}"
      onclick="addPrimaryType('${option.value}')"
    >
      ${option.label} (${option.value})
    </div>
  `).join("");
  menu.classList.remove("hidden");
}

function addPrimaryType(value) {
  if (!selectedPrimaryTypes.includes(value)) {
    selectedPrimaryTypes.push(value);
  }
  getPrimaryTypeInput().value = "";
  renderSelectedPrimaryTypes();
  renderPrimaryTypeSuggestions("");
  getPrimaryTypeInput().focus();
}

function removePrimaryType(value) {
  selectedPrimaryTypes = selectedPrimaryTypes.filter((item) => item !== value);
  renderSelectedPrimaryTypes();
  renderPrimaryTypeSuggestions(getPrimaryTypeInput().value.trim());
}

function commitPrimaryTypeInput() {
  const input = getPrimaryTypeInput();
  const rawValue = input.value.trim();
  if (!rawValue) return true;

  const normalizedValue = normalizePrimaryType(rawValue);
  const exactMatch = placeTypeOptions.find((option) => option.value === normalizedValue);
  if (exactMatch) {
    addPrimaryType(exactMatch.value);
    return true;
  }

  const firstMatch = getPrimaryTypeMatches(rawValue)[0];
  if (firstMatch) {
    addPrimaryType(firstMatch.value);
    return true;
  }

  showToast(`Unknown place type "${rawValue}"`, "error");
  return false;
}

async function loadPlaceTypeOptions() {
  const resp = await fetch("/api/place-types");
  const data = await resp.json();
  if (!resp.ok) throw new Error(data.error || "Failed to load place types");
  placeTypeOptions = data.place_types || [];
  renderSelectedPrimaryTypes();
}

function updateCircle() {
  const r = milesToMeters(parseFloat(document.getElementById("radius-num").value) || DEFAULT_RADIUS_MI);
  radiusCircle.setLatLng([centerLat, centerLng]).setRadius(r);
}

// ── Radius sync ────────────────────────────────────────────────────────────
document.getElementById("radius-slider").addEventListener("input", (e) => {
  document.getElementById("radius-num").value = e.target.value;
  updateCircle();
});
document.getElementById("radius-num").addEventListener("input", (e) => {
  document.getElementById("radius-slider").value = e.target.value;
  updateCircle();
});

// ── Search ─────────────────────────────────────────────────────────────────
document.getElementById("search-btn").addEventListener("click", async () => {
  if (!commitPrimaryTypeInput()) return;
  if (!selectedPrimaryTypes.length) {
    showToast("Choose at least one primary type.", "error");
    getPrimaryTypeInput().focus();
    return;
  }

  const fieldMask = [...document.querySelectorAll('input[name="field"]:checked')].map(cb => cb.value);
  const body = {
    primary_types: selectedPrimaryTypes,
    center_lat:   centerLat,
    center_lng:   centerLng,
    radius_m:     milesToMeters(parseFloat(document.getElementById("radius-num").value)),
    max_results:  parseInt(document.getElementById("max-results").value),
    field_mask:   fieldMask,
  };

  setSearchLoading(true);
  try {
    const resp = await fetch("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || "Search failed");
    currentPage = 1;
    searchResults = data.businesses || [];
    refreshResultsView();
    showToast(`Found ${data.count ?? "?"} businesses`, "success");
  } catch (err) {
    showToast(err.message, "error");
  } finally {
    setSearchLoading(false);
  }
});

document.getElementById("clear-btn").addEventListener("click", () => {
  getPrimaryTypeInput().value = "";
  selectedPrimaryTypes = [];
  renderSelectedPrimaryTypes();
  hidePrimaryTypeSuggestions();
  document.getElementById("radius-num").value = DEFAULT_RADIUS_MI;
  document.getElementById("radius-slider").value = DEFAULT_RADIUS_MI;
  document.getElementById("max-results").value = DEFAULT_MAX_RESULTS;
  document.querySelectorAll('input[name="field"]').forEach(cb => cb.checked = true);
  document.getElementById("filter-status").value = "";
  document.getElementById("filter-enriched").value = "";
  document.getElementById("filter-text").value = "";
  document.getElementById("enrich-status").textContent = "";

  centerLat = DEFAULT_CENTER_LAT;
  centerLng = DEFAULT_CENTER_LNG;
  centerMarker.setLatLng([centerLat, centerLng]);
  map.setView([centerLat, centerLng], DEFAULT_ZOOM);
  updateCircle();

  searchResults = [];
  currentPage = 1;
  renderEmptyState("Run a search to see results.");
  renderPagination(0);
  renderMapMarkers([]);

  document.getElementById("detail-drawer").classList.add("hidden");
  delete document.getElementById("detail-drawer").dataset.businessId;
});

function setSearchLoading(loading) {
  document.getElementById("search-btn").disabled = loading;
  document.getElementById("search-btn").textContent = loading ? "Searching…" : "Search";
}

function getFilteredBusinesses() {
  const status   = document.getElementById("filter-status").value;
  const enriched = document.getElementById("filter-enriched").value;
  const q        = document.getElementById("filter-text").value.trim();

  return searchResults.filter((b) => {
    if (status && b.status !== status) return false;
    if (enriched === "true" && !b.enriched) return false;
    if (enriched === "false" && b.enriched) return false;
    if (q) {
      const haystack = `${b.name || ""} ${b.formatted_address || ""}`.toLowerCase();
      if (!haystack.includes(q.toLowerCase())) return false;
    }
    return true;
  });
}

function refreshResultsView() {
  const filteredBusinesses = getFilteredBusinesses();
  const total = filteredBusinesses.length;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  if (currentPage > totalPages) {
    currentPage = totalPages;
  }

  const start = (currentPage - 1) * pageSize;
  const pageBusinesses = filteredBusinesses.slice(start, start + pageSize);

  renderTable(pageBusinesses);
  renderPagination(total);
  renderMapMarkers(pageBusinesses);
}

function renderEmptyState(message) {
  document.getElementById("business-tbody").innerHTML =
    `<tr><td colspan="6" class="empty-msg">${message}</td></tr>`;
}

function updateBusinessInResults(updatedBusiness) {
  const idx = searchResults.findIndex((b) => b.id === updatedBusiness.id);
  if (idx === -1) return;

  searchResults[idx] = { ...searchResults[idx], ...updatedBusiness };
  refreshResultsView();
}

function getBusinessFromResults(id) {
  return searchResults.find((b) => b.id === id);
}

// ── Table rendering ────────────────────────────────────────────────────────
function renderTable(businesses) {
  const tbody = document.getElementById("business-tbody");
  if (!businesses.length) {
    renderEmptyState("No results found.");
    return;
  }
  tbody.innerHTML = businesses.map(b => `
    <tr data-id="${b.id}" class="business-row">
      <td>${b.name || "—"}</td>
      <td>${b.formatted_address || "—"}</td>
      <td>${b.website ? `<a href="${b.website}" target="_blank">Link</a>` : "—"}</td>
      <td><span class="status-badge status-${slugify(b.status)}">${b.status || "New"}</span></td>
      <td>${b.enriched ? "✅" : "—"}</td>
      <td>
        <div class="action-btns">
          <button class="btn-sm" onclick="openDrawer(${b.id})">View</button>
          <button class="btn-sm btn-enrich" onclick="enrichOne(${b.id}, this)">${b.enriched ? "Re-run" : "Enrich"}</button>
        </div>
      </td>
    </tr>
  `).join("");
}

function slugify(s) { return (s || "new").toLowerCase().replace(/\s+/g, "-"); }

// ── Map markers ────────────────────────────────────────────────────────────
let businessMarkers = [];
function renderMapMarkers(businesses) {
  businessMarkers.forEach(m => m.remove());
  businessMarkers = [];
  businesses.forEach(b => {
    if (!b.lat || !b.lng) return;
    const m = L.marker([b.lat, b.lng])
      .addTo(map)
      .bindPopup(`<strong>${b.name}</strong><br>${b.formatted_address || ""}`);
    businessMarkers.push(m);
  });
}

// ── Pagination ─────────────────────────────────────────────────────────────
function renderPagination(total) {
  const pages = Math.ceil(total / pageSize);
  const el = document.getElementById("pagination");
  if (pages <= 1) { el.innerHTML = ""; return; }
  el.innerHTML = `
    <button onclick="goPage(${currentPage - 1})" ${currentPage === 1 ? "disabled" : ""}>‹</button>
    ${[...Array(pages)].map((_, i) => `<button class="${i+1===currentPage?"active":""}" onclick="goPage(${i+1})">${i+1}</button>`).join("")}
    <button onclick="goPage(${currentPage + 1})" ${currentPage === pages ? "disabled" : ""}>›</button>
  `;
}

function goPage(p) { currentPage = p; refreshResultsView(); }

// ── Filters ────────────────────────────────────────────────────────────────
["filter-status", "filter-enriched", "filter-text"].forEach(id => {
  document.getElementById(id).addEventListener("change", () => {
    currentPage = 1;
    refreshResultsView();
  });
});

// ── Detail Drawer ──────────────────────────────────────────────────────────
async function openDrawer(id) {
  try {
    const resp = await fetch(`/api/businesses/${id}`);
    const b = await resp.json();
    if (!resp.ok) throw new Error(b.error || "Failed to load business");
    document.getElementById("detail-drawer").dataset.businessId = String(b.id);

    const intel = b.intel || {};
    document.getElementById("drawer-content").innerHTML = `
      <h2>${b.name}</h2>
      <p class="detail-meta">${b.formatted_address || ""} ${b.phone ? "· " + b.phone : ""}</p>
      ${b.website ? `<p><a href="${b.website}" target="_blank">${b.website}</a></p>` : ""}

      <div class="detail-status-row">
        <label>Status
          <select id="drawer-status">
            ${["New","Qualified","Contacted","Not a fit"].map(s => `<option ${b.status===s?"selected":""}>${s}</option>`).join("")}
          </select>
        </label>
        <button onclick="saveStatus(${b.id})">Save Status</button>
      </div>

      <div class="intel-section">
        ${intelField("Summary", intel.company_summary)}
        ${intelField("Products / Services", intel.products_services)}
        ${intelField("Estimated Size", intel.estimated_size)}
        ${intelField("Target Customers", intel.target_customers)}
        ${intelField("Key Contacts", intel.key_contacts)}
        ${intelField("Technologies", intel.technologies_used)}
        ${intelField("Pain Points", intel.potential_pain_points)}
        ${intelField("Outreach Angle", intel.outreach_angle, true)}
        ${intelField("Recent News", intel.recent_news)}
      </div>

      <div class="drawer-actions">
        <button onclick="enrichOne(${b.id}, this)" id="drawer-enrich-btn">${b.enriched ? "Re-run Enrich" : "Enrich"}</button>
      </div>

      <div class="contacts-section" id="contacts-section">
        <div class="contacts-header">
          <h4>Contacts</h4>
          <button class="btn-sm" id="discover-btn" onclick="discoverContacts(${b.id}, this)">Discover</button>
        </div>
        <div id="contacts-list"><p class="empty-msg">Loading contacts…</p></div>
      </div>

      <div class="notes-section">
        <h4>Notes</h4>
        ${(b.notes || []).map(n => `<p class="note-item">${n.body}</p>`).join("") || "<p class='empty-msg'>No notes yet.</p>"}
        <textarea id="new-note" rows="3" placeholder="Add a note..."></textarea>
        <button onclick="saveNote(${b.id})">Save Note</button>
      </div>
    `;
    document.getElementById("detail-drawer").classList.remove("hidden");
    loadContacts(b.id);
  } catch (err) {
    showToast(err.message, "error");
  }
}

function intelField(label, value, copyable = false) {
  if (!value) return "";
  return `
    <div class="intel-field">
      <strong>${label}:</strong>
      <span>${value}</span>
      ${copyable ? `<button class="btn-copy" onclick="copyText('${escapeAttr(value)}')">Copy</button>` : ""}
    </div>`;
}

function escapeAttr(s) { return (s || "").replace(/'/g, "\\'"); }
function copyText(text) { navigator.clipboard.writeText(text).then(() => showToast("Copied!", "success")); }

document.getElementById("drawer-close").addEventListener("click", () => {
  document.getElementById("detail-drawer").classList.add("hidden");
  delete document.getElementById("detail-drawer").dataset.businessId;
});

// ── Status save ────────────────────────────────────────────────────────────
async function saveStatus(id) {
  const status = document.getElementById("drawer-status").value;
  try {
    const resp = await fetch(`/api/businesses/${id}/status`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });
    if (!resp.ok) throw new Error("Failed to save status");
    showToast("Status updated", "success");
    updateBusinessInResults({ id, status });
    if (document.getElementById("detail-drawer").dataset.businessId === String(id)) {
      openDrawer(id);
    }
  } catch (err) {
    showToast(err.message, "error");
  }
}

// ── Notes ──────────────────────────────────────────────────────────────────
async function saveNote(id) {
  const body = document.getElementById("new-note").value.trim();
  if (!body) return;
  try {
    const resp = await fetch(`/api/businesses/${id}/notes`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ body }),
    });
    if (!resp.ok) throw new Error("Failed to save note");
    showToast("Note saved", "success");
    openDrawer(id);
  } catch (err) {
    showToast(err.message, "error");
  }
}

// ── Enrich ─────────────────────────────────────────────────────────────────
async function enrichOne(id, btn) {
  const original = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Enriching…";
  try {
    const resp = await fetch(`/api/enrich/${id}`, { method: "POST" });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || "Enrichment failed");
    const business = getBusinessFromResults(id);
    updateBusinessInResults({ id, enriched: true });
    showToast(`✓ Enriched "${business?.name || "business"}"`, "success");
    if (document.getElementById("detail-drawer").dataset.businessId === String(id)) {
      openDrawer(id);
    }
    btn.disabled = false;
    btn.textContent = original;
  } catch (err) {
    showToast(`⚠ ${err.message}`, "error");
    btn.disabled = false;
    btn.textContent = original;
  }
}

document.getElementById("enrich-all-btn").addEventListener("click", async () => {
  const rows = [...document.querySelectorAll(".business-row")];
  const ids = rows.map(r => parseInt(r.dataset.id));
  const statusEl = document.getElementById("enrich-status");
  for (let i = 0; i < ids.length; i++) {
    statusEl.textContent = `Enriching ${i + 1} / ${ids.length}…`;
    const btn = document.querySelector(`tr[data-id="${ids[i]}"] .btn-enrich`);
    await enrichOne(ids[i], btn || document.createElement("button"));
  }
  statusEl.textContent = "";
});

// ── Toast ──────────────────────────────────────────────────────────────────
function showToast(message, type = "info") {
  const container = document.getElementById("toast-container");
  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 3500);
}

function initPrimaryTypeSelector() {
  const input = getPrimaryTypeInput();
  const selector = document.getElementById("primary-type-selector");

  input.addEventListener("focus", () => renderPrimaryTypeSuggestions(input.value.trim()));
  input.addEventListener("input", () => renderPrimaryTypeSuggestions(input.value.trim()));
  input.addEventListener("keydown", (e) => {
    if (e.key === "Backspace" && !input.value && selectedPrimaryTypes.length) {
      removePrimaryType(selectedPrimaryTypes[selectedPrimaryTypes.length - 1]);
      return;
    }

    if (e.key === "ArrowDown" && visiblePrimaryTypeMatches.length) {
      e.preventDefault();
      highlightedPrimaryTypeIndex = Math.min(highlightedPrimaryTypeIndex + 1, visiblePrimaryTypeMatches.length - 1);
      renderPrimaryTypeSuggestions(input.value.trim());
      return;
    }

    if (e.key === "ArrowUp" && visiblePrimaryTypeMatches.length) {
      e.preventDefault();
      highlightedPrimaryTypeIndex = Math.max(highlightedPrimaryTypeIndex - 1, 0);
      renderPrimaryTypeSuggestions(input.value.trim());
      return;
    }

    if (e.key === "Enter") {
      e.preventDefault();
      if (visiblePrimaryTypeMatches[highlightedPrimaryTypeIndex]) {
        addPrimaryType(visiblePrimaryTypeMatches[highlightedPrimaryTypeIndex].value);
      } else {
        commitPrimaryTypeInput();
      }
      return;
    }

    if (e.key === "Escape") {
      hidePrimaryTypeSuggestions();
    }
  });

  document.addEventListener("click", (e) => {
    if (!selector.contains(e.target)) {
      hidePrimaryTypeSuggestions();
    }
  });
}

// ── Contacts (Stage 2) & Dossier (Stage 3) ──────────────────────────────────
function confidenceBadge(level) {
  const l = (level || "low").toLowerCase();
  return `<span class="conf-badge conf-${l}">${l}</span>`;
}

function escapeHtml(s) {
  return (s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

async function loadContacts(businessId) {
  const list = document.getElementById("contacts-list");
  if (!list) return;
  try {
    const resp = await fetch(`/api/businesses/${businessId}/contacts`);
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || "Failed to load contacts");
    renderContacts(data.contacts || []);
  } catch (err) {
    list.innerHTML = `<p class="empty-msg">${escapeHtml(err.message)}</p>`;
  }
}

async function discoverContacts(businessId, btn) {
  const original = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Discovering…";
  document.getElementById("contacts-list").innerHTML =
    `<p class="empty-msg">Searching Brave + extracting contacts… this can take a bit.</p>`;
  try {
    const resp = await fetch(`/api/businesses/${businessId}/discover-contacts`, { method: "POST" });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || "Discovery failed");
    renderContacts(data.contacts || []);
    (data.warnings || []).forEach(w => showToast(`⚠ ${w}`, "info"));
    showToast(`Found ${data.count ?? "?"} contacts`, "success");
  } catch (err) {
    showToast(`⚠ ${err.message}`, "error");
    document.getElementById("contacts-list").innerHTML =
      `<p class="empty-msg">${escapeHtml(err.message)}</p>`;
  } finally {
    btn.disabled = false;
    btn.textContent = original;
  }
}

function renderContacts(contacts) {
  const list = document.getElementById("contacts-list");
  if (!list) return;
  if (!contacts.length) {
    list.innerHTML = `<p class="empty-msg">No contacts yet. Click Discover to find them.</p>`;
    return;
  }
  list.innerHTML = contacts.map(c => `
    <div class="contact-card" data-contact-id="${c.id}">
      <div class="contact-head">
        <div>
          <strong>${escapeHtml(c.name)}</strong>
          ${c.title ? `<span class="contact-title">${escapeHtml(c.title)}</span>` : ""}
        </div>
        ${confidenceBadge(c.confidence)}
      </div>
      ${c.why_relevant ? `<p class="contact-why">${escapeHtml(c.why_relevant)}</p>` : ""}
      <div class="contact-actions">
        <button class="btn-sm" onclick="buildDossier(${c.id}, this)">
          ${c.has_dossier ? "View Dossier" : "Deep-Dive"}
        </button>
        ${c.has_dossier ? `<button class="btn-sm btn-secondary" onclick="rebuildDossier(${c.id}, this)" title="Rebuild from scratch with the latest contact info and active profile">Rebuild</button>` : ""}
      </div>
      <div class="dossier-panel" id="dossier-panel-${c.id}"></div>
    </div>
  `).join("");

  // Auto-load any dossier already on disk so "View Dossier" shows instantly.
  contacts.filter(c => c.has_dossier).forEach(c => loadDossier(c.id));
}

async function loadDossier(contactId) {
  try {
    const resp = await fetch(`/api/contacts/${contactId}/dossier`);
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || "Failed to load dossier");
    if (data.dossier) renderDossier(contactId, data.dossier);
  } catch (err) {
    /* silent: panel stays collapsed until the user builds it */
  }
}

async function buildDossier(contactId, btn) {
  const panel = document.getElementById(`dossier-panel-${contactId}`);
  // If already rendered, toggle it closed.
  if (panel.dataset.loaded === "true" && panel.innerHTML) {
    panel.classList.toggle("hidden");
    return;
  }
  const original = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Researching…";
  panel.innerHTML = `<p class="empty-msg">Running the gate, reach, background, engagement & org tracks…</p>`;
  panel.classList.remove("hidden");
  try {
    const resp = await fetch(`/api/contacts/${contactId}/dossier`, { method: "POST" });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || "Dossier build failed");
    renderDossier(contactId, data.dossier);
    btn.textContent = "View Dossier";
    showToast("Dossier ready", "success");
  } catch (err) {
    panel.innerHTML = `<p class="empty-msg">${escapeHtml(err.message)}</p>`;
    btn.textContent = original;
    showToast(`⚠ ${err.message}`, "error");
  } finally {
    btn.disabled = false;
  }
}

async function rebuildDossier(contactId, btn) {
  // Forces a POST rebuild even when a dossier is already saved -- e.g. after
  // the contact's info changed, or after a scoring/profile change made the
  // stored gate verdict stale.
  const panel = document.getElementById(`dossier-panel-${contactId}`);
  const original = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Rebuilding…";
  panel.innerHTML = `<p class="empty-msg">Rebuilding dossier — rerunning the gate, reach, background, engagement & org tracks…</p>`;
  panel.classList.remove("hidden");
  try {
    const resp = await fetch(`/api/contacts/${contactId}/dossier`, { method: "POST" });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || "Dossier rebuild failed");
    renderDossier(contactId, data.dossier);
    showToast("Dossier rebuilt", "success");
  } catch (err) {
    panel.innerHTML = `<p class="empty-msg">${escapeHtml(err.message)}</p>`;
    showToast(`⚠ ${err.message}`, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = original;
  }
}

function provLink(url) {
  if (!url) return "";
  return `<a href="${url}" target="_blank" rel="noopener" class="prov-link" title="${escapeHtml(url)}">source</a>`;
}

function renderDossier(contactId, d) {
  const panel = document.getElementById(`dossier-panel-${contactId}`);
  if (!panel) return;
  const gate = d.gate || {};
  const currency = gate.currency || "uncertain";

  const gateHtml = `
    <div class="gate-row">
      <span class="currency-badge currency-${slugify(currency)}">${currency.replace(/_/g, " ")}</span>
      <span class="gate-meta">seniority ${gate.seniority_score ?? "?"}</span>
      ${gate.worth_deepdive ? "" : `<span class="gate-flag">short-circuited</span>`}
    </div>
    ${gate.rationale ? `<p class="gate-rationale">${escapeHtml(gate.rationale)}</p>` : ""}
  `;

  const reachHtml = (d.reach || []).map(r => `
    <li>
      <span class="reach-kind">${escapeHtml(r.kind)}</span>
      <span class="reach-val">${escapeHtml(r.value)}</span>
      ${confidenceBadge(r.confidence)}
      <span class="how">${escapeHtml(r.how_obtained || "")}</span>
      ${provLink(r.source_url)}
      ${r.note ? `<span class="reach-note">${escapeHtml(r.note)}</span>` : ""}
    </li>`).join("");

  const bgHtml = (d.background || []).map(f => `
    <li>${escapeHtml(f.claim)} ${confidenceBadge(f.confidence)}
      ${f.date ? `<span class="how">${escapeHtml(f.date)}</span>` : ""} ${provLink(f.source_url)}</li>`).join("");

  const engHtml = (d.engagement || []).map(e => `
    <li>
      <strong>${escapeHtml(e.title || e.kind || "item")}</strong>
      ${e.date ? `<span class="how">${escapeHtml(e.date)}</span>` : ""}
      <span class="id-conf">id: ${confidenceBadge(e.identity_confidence)}</span>
      ${e.summary ? `<div class="eng-summary">${escapeHtml(e.summary)}</div>` : ""}
      ${e.relevance ? `<div class="eng-rel">${escapeHtml(e.relevance)}</div>` : ""}
      ${provLink(e.url)}
    </li>`).join("");

  const orgHtml = (d.org_inferences || []).map(o => `
    <li>${escapeHtml(o.claim)} ${confidenceBadge(o.confidence)}
      ${(o.basis || []).map(b => provLink(b)).join(" ")}</li>`).join("");

  const section = (label, inner, emptyNote) =>
    `<div class="dossier-block"><h5>${label}</h5>${inner ? `<ul class="dossier-list">${inner}</ul>` : `<p class="empty-msg">${emptyNote}</p>`}</div>`;

  const warnHtml = (d.warnings || []).length
    ? `<div class="dossier-warnings">${(d.warnings || []).map(w => `<div>⚠ ${escapeHtml(w)}</div>`).join("")}</div>`
    : "";

  panel.innerHTML = `
    <div class="dossier">
      ${gateHtml}
      ${section("Reach", reachHtml, "No reach info found.")}
      ${section("Background", bgHtml, "No background facts.")}
      ${section("Engagement", engHtml, "No public engagement found.")}
      ${section("Org inference (low confidence)", orgHtml, "No cited inferences.")}
      ${warnHtml}
    </div>
  `;
  panel.dataset.loaded = "true";
  panel.classList.remove("hidden");
}

// ── Boot ───────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", async () => {
  initMap();
  initPrimaryTypeSelector();
  try {
    await loadPlaceTypeOptions();
  } catch (err) {
    showToast(err.message, "error");
  }
});
