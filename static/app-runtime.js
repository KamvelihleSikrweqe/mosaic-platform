(() => {
  const state = { app: null, orgId: null, activePage: 0, records: {}, editing: null };
  const $ = (selector) => document.querySelector(selector);
  const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[char]));
  const toast = (message) => {
    const node = $("#runtimeToast");
    node.textContent = message;
    node.classList.add("visible");
    window.setTimeout(() => node.classList.remove("visible"), 2800);
  };
  const api = async (path, options = {}) => {
    const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
    const session = sessionStorage.getItem("mosaic.oidc.session");
    if (session) {
      try {
        const tokens = JSON.parse(session);
        if (tokens.accessToken && Number(tokens.expiresAt) > Date.now()) {
          headers.Authorization = "Bearer " + tokens.accessToken;
        }
      } catch (_) { /* Ignore malformed local session state. */ }
    }
    if (state.orgId) headers["X-Organisation-ID"] = state.orgId;
    const response = await fetch("/api/v1" + path, {
      ...options, credentials: "same-origin", headers
    });
    const data = response.status === 204 ? null : await response.json().catch(() => ({}));
    if (!response.ok) {
      if (response.status === 401) throw new Error("Your session is not authenticated. Return to MOSAIC and sign in, then open the application again.");
      throw new Error(data.detail || "Request failed (" + response.status + ")");
    }
    return data;
  };
  const pageList = () => state.app.pages.length ? state.app.pages : [{ name: "Dashboard", type: "dashboard" }];
  const objectFor = (page) => state.app.objects[page.dataSource] || null;
  const loadRecords = async (object) => {
    if (!object) return [];
    if (!state.records[object.id]) {
      state.records[object.id] = await api("/objects/" + encodeURIComponent(object.id) + "/records?limit=100");
    }
    return state.records[object.id];
  };
  const refreshObject = async (object) => {
    if (!object) return;
    state.records[object.id] = await api("/objects/" + encodeURIComponent(object.id) + "/records?limit=100");
  };
  const renderNavigation = () => {
    const pages = pageList();
    $("#runtimeNav").innerHTML = pages.map((page, index) =>
      '<button type="button" class="' + (index === state.activePage ? "active" : "") +
      '" data-page="' + index + '">' + escapeHtml(page.name || "Page " + (index + 1)) + "</button>"
    ).join("");
  };
  const renderDashboard = async () => {
    const objects = Object.values(state.app.objects);
    const counts = await Promise.all(objects.map(async (object) => ({
      object, rows: await loadRecords(object)
    })));
    return '<div class="runtime-cards">' + counts.map(({ object, rows }) =>
      '<article class="metric-card"><span>' + escapeHtml(object.label) +
      '</span><strong>' + rows.length + '</strong><small>Business records</small></article>'
    ).join("") + '<article class="metric-card"><span>APPLICATION STATUS</span><strong class="status-text">' +
      escapeHtml(state.app.status.toUpperCase()) + '</strong><small>Version ' + state.app.version +
      '</small></article></div><section class="welcome-panel"><div class="eyebrow">YOUR WORKSPACE</div><h2>' +
      escapeHtml(state.app.name) + '</h2><p>' + escapeHtml(state.app.description ||
      "Your organisation application is ready to use.") +
      '</p><p class="muted">Choose a page from the navigation to work with your organisation data.</p></section>';
  };
  const schemaFields = (object) => {
    const schema = object.schema || {};
    const properties = schema.properties || {};
    const required = new Set(schema.required || []);
    return Object.entries(properties).map(([key, spec]) => ({ key, spec, required: required.has(key) }));
  };
  const openRecordForm = (object, record = null) => {
    state.editing = record;
    $("#recordDialogTitle").textContent = record ? "Edit " + object.label : "New " + object.label;
    $("#recordFields").innerHTML = schemaFields(object).map(({ key, spec, required }) => {
      const value = record?.data?.[key] ?? "";
      const type = spec.format === "email" ? "email" : spec.format === "date" ? "date" :
        spec.type === "integer" || spec.type === "number" ? "number" : "text";
      if (spec.type === "boolean") return '<label class="check-field"><input name="' +
        escapeHtml(key) + '" type="checkbox" ' + (value ? "checked" : "") + '> ' +
        escapeHtml(spec.title || key.replaceAll("_", " ")) + '</label>';
      if (Array.isArray(spec.enum)) return '<label>' + escapeHtml(spec.title || key.replaceAll("_", " ")) +
        '<select name="' + escapeHtml(key) + '" ' + (required ? "required" : "") + '><option value="">Choose…</option>' +
        spec.enum.map(option => '<option value="' + escapeHtml(option) + '" ' +
          (String(value) === String(option) ? "selected" : "") + '>' + escapeHtml(option) +
          '</option>').join("") + '</select></label>';
      return '<label>' + escapeHtml(spec.title || key.replaceAll("_", " ")) +
        '<input name="' + escapeHtml(key) + '" type="' + type + '" value="' + escapeHtml(value) +
        '" ' + (required ? "required" : "") + ' placeholder="' + escapeHtml(spec.description || "") +
        '"></label>';
    }).join("") || '<p class="muted">This data model has no fields. Add properties to its JSON Schema first.</p>';
    $("#recordDialog").showModal();
  };
  const renderDataList = async (page) => {
    const object = objectFor(page);
    if (!object) return '<div class="empty-state">This page references a data model that is not available in this workspace.</div>';
    const rows = await loadRecords(object);
    const fields = schemaFields(object).slice(0, 4);
    return '<section class="data-panel"><div class="panel-heading"><div><div class="eyebrow">' +
      escapeHtml(object.label.toUpperCase()) + '</div><h2>' + escapeHtml(page.title || page.name || object.label) +
      '</h2><p>' + escapeHtml(page.description || "Browse and manage records in this data model.") +
      '</p></div><button class="primary" type="button" data-new-record="' + escapeHtml(object.key) +
      '">＋ New record</button></div>' +
      (rows.length ? '<div class="table-scroll"><table><thead><tr>' +
        fields.map(field => '<th>' + escapeHtml(field.spec.title || field.key.replaceAll("_", " ")) + '</th>').join("") +
        '<th>Created</th><th></th></tr></thead><tbody>' + rows.map(record =>
          '<tr>' + fields.map(field => '<td>' + escapeHtml(record.data[field.key] ?? "—") + '</td>').join("") +
          '<td>' + new Date(record.created_at).toLocaleDateString() + '</td><td class="row-actions">' +
          '<button type="button" data-edit-record="' + escapeHtml(record.id) + '" data-object="' +
          escapeHtml(object.key) + '">Edit</button><button type="button" class="danger-link" data-delete-record="' +
          escapeHtml(record.id) + '" data-object="' + escapeHtml(object.key) + '">Delete</button></td></tr>'
        ).join("") + '</tbody></table></div>' :
        '<div class="empty-state">No records yet. Create the first record to start using this application.</div>') +
      '</section>';
  };
  const renderDataForm = (page) => {
    const object = objectFor(page);
    if (!object) return '<div class="empty-state">This page references a data model that is not available in this workspace.</div>';
    return '<section class="data-panel form-page"><div class="eyebrow">' + escapeHtml(object.label.toUpperCase()) +
      '</div><h2>' + escapeHtml(page.title || page.name || "Create " + object.label) + '</h2><p>' +
      escapeHtml(page.description || "Add a new record to your organisation workspace.") +
      '</p><button class="primary" type="button" data-new-record="' + escapeHtml(object.key) +
      '">＋ Create ' + escapeHtml(object.label) + '</button><div class="form-page-note">Your entries are validated against the data model schema and stored in this organisation.</div></section>';
  };
  const renderPage = async () => {
    const page = pageList()[state.activePage] || pageList()[0];
    $("#runtimePageTitle").textContent = page.name || "Application";
    renderNavigation();
    const content = $("#runtimeContent");
    content.innerHTML = '<div class="loading">Loading page…</div>';
    try {
      if (page.type === "dashboard") content.innerHTML = await renderDashboard();
      else if (page.type === "data-list") content.innerHTML = await renderDataList(page);
      else if (page.type === "data-form") content.innerHTML = renderDataForm(page);
      else content.innerHTML = '<div class="empty-state">This page type is not supported by the current runtime.</div>';
    } catch (error) {
      content.innerHTML = '<div class="error-panel">' + escapeHtml(error.message) + '</div>';
    }
  };
  const submitRecord = async (event) => {
    event.preventDefault();
    const objectKey = $("#recordForm").dataset.object;
    const object = state.app.objects[objectKey];
    if (!object) return;
    const data = {};
    for (const { key, spec } of schemaFields(object)) {
      const input = $("#recordFields").querySelector('[name="' + CSS.escape(key) + '"]');
      if (!input) continue;
      data[key] = spec.type === "boolean" ? input.checked :
        spec.type === "integer" ? (input.value === "" ? undefined : Number.parseInt(input.value, 10)) :
        spec.type === "number" ? (input.value === "" ? undefined : Number(input.value)) :
        input.value === "" ? undefined : input.value;
      if (data[key] === undefined) delete data[key];
    }
    try {
      if (state.editing) await api("/records/" + encodeURIComponent(state.editing.id), {
        method: "PUT", body: JSON.stringify({ data })
      });
      else await api("/objects/" + encodeURIComponent(object.id) + "/records", {
        method: "POST", body: JSON.stringify({ data })
      });
      await refreshObject(object);
      $("#recordDialog").close();
      await renderPage();
      toast(state.editing ? "Record updated." : "Record created.");
      state.editing = null;
    } catch (error) { toast(error.message); }
  };
  const boot = async () => {
    const match = location.pathname.match(/^\/apps\/([^/]+)\/preview$/);
    if (!match) throw new Error("Application preview URL is invalid.");
    state.orgId = new URLSearchParams(location.search).get("org_id");
    if (!state.orgId) throw new Error("No organisation was selected. Return to the platform and open Preview from an organisation workspace.");
    state.app = await api("/apps/" + encodeURIComponent(decodeURIComponent(match[1])) + "/runtime");
    if (state.app.organisation.id !== state.orgId) throw new Error("Organisation context mismatch.");
    document.title = state.app.name + " · MOSAIC";
    $("#runtimeOrg").textContent = state.app.organisation.name;
    $("#runtimeAppName").textContent = "MOSAIC APPLICATION";
    $("#runtimeDescription").textContent = state.app.description || "Organisation application";
    $("#runtimeVersion").textContent = "v" + state.app.version;
    if (state.app.status !== "published") {
      $("#runtimeNotice").hidden = false;
      $("#runtimeNotice").textContent = "Preview mode · This application has not been published.";
    }
    renderNavigation();
    await renderPage();
  };
  document.addEventListener("click", async (event) => {
    const page = event.target.closest("[data-page]");
    if (page) { state.activePage = Number(page.dataset.page); await renderPage(); return; }
    const create = event.target.closest("[data-new-record]");
    if (create) {
      const object = state.app.objects[create.dataset.newRecord];
      if (object) { $("#recordForm").dataset.object = object.key; openRecordForm(object); }
      return;
    }
    const edit = event.target.closest("[data-edit-record]");
    if (edit) {
      const object = state.app.objects[edit.dataset.object];
      const record = (await loadRecords(object)).find(row => row.id === edit.dataset.editRecord);
      if (record) { $("#recordForm").dataset.object = object.key; openRecordForm(object, record); }
      return;
    }
    const remove = event.target.closest("[data-delete-record]");
    if (remove) {
      const object = state.app.objects[remove.dataset.object];
      if (!object || !window.confirm("Delete this record? This cannot be undone.")) return;
      try {
        await api("/records/" + encodeURIComponent(remove.dataset.deleteRecord), { method: "DELETE" });
        await refreshObject(object); await renderPage(); toast("Record deleted.");
      } catch (error) { toast(error.message); }
    }
  });
  $("#recordForm").addEventListener("submit", submitRecord);
  $("#recordClose").addEventListener("click", () => $("#recordDialog").close());
  $("#recordCancel").addEventListener("click", () => $("#recordDialog").close());
  boot().catch(error => {
    $("#runtimePageTitle").textContent = "Application unavailable";
    $("#runtimeContent").innerHTML = '<div class="error-panel">' + escapeHtml(error.message) +
      '<p><a href="/">Return to MOSAIC platform</a></p></div>';
  });
})();