// K9Chat — ProjectPanel component
// Owns the Projects list in the sidebar: create/rename-via-instructions/
// delete, file upload/remove, and which project (if any) is "active" for
// the next message. Backed entirely by the server (/projects/*) — unlike
// SessionSidebar's chat history, project data must survive across
// browsers/devices since it's shared context, not a personal transcript,
// so nothing here is cached in localStorage except which project id was
// last selected (a personal UI convenience, not the data itself).

const ProjectPanel = (() => {
  const listEl = document.getElementById("project-list");
  const newBtn = document.getElementById("project-new-btn");
  const newForm = document.getElementById("project-new-form");
  const newInput = document.getElementById("project-new-name");
  const newCreateBtn = document.getElementById("project-new-create");
  const activeBar = document.getElementById("active-project-bar");

  let projects = [];
  let activeProjectId = localStorage.getItem("k9chat_active_project") || null;
  let expandedId = null;

  function setActive(id) {
    activeProjectId = id;
    if (id) {
      localStorage.setItem("k9chat_active_project", id);
    } else {
      localStorage.removeItem("k9chat_active_project");
    }
    renderActiveBar();
    render();
  }

  function findProject(id) {
    return projects.find(p => p.project_id === id) || null;
  }

  function renderActiveBar() {
    const project = activeProjectId ? findProject(activeProjectId) : null;
    if (!project) {
      activeBar.style.display = "none";
      activeBar.innerHTML = "";
      return;
    }
    activeBar.style.display = "flex";
    activeBar.innerHTML = "";

    const label = document.createElement("span");
    label.textContent = `📁 Using project "${project.name}"`;
    activeBar.appendChild(label);

    const clear = document.createElement("button");
    clear.className = "clear-project-btn";
    clear.textContent = "Use no project";
    clear.addEventListener("click", () => setActive(null));
    activeBar.appendChild(clear);
  }

  async function refresh() {
    try {
      const resp = await fetch("/projects");
      const data = await resp.json();
      projects = data.projects || [];
      if (activeProjectId && !findProject(activeProjectId)) {
        setActive(null);
        return;
      }
      render();
      renderActiveBar();
    } catch (err) {
      // Backend unreachable -- app.js's health banner already surfaces this.
    }
  }

  function buildManagePanel(project) {
    const wrap = document.createElement("div");
    wrap.className = "project-manage";

    const label = document.createElement("label");
    label.textContent = "Custom instructions (optional)";
    wrap.appendChild(label);

    const textarea = document.createElement("textarea");
    textarea.value = project.instructions || "";
    textarea.placeholder = "e.g. Always cite the file a fact came from.";
    wrap.appendChild(textarea);

    const saveRow = document.createElement("div");
    saveRow.className = "button-row";
    const saveBtn = document.createElement("button");
    saveBtn.className = "secondary small";
    saveBtn.type = "button";
    saveBtn.textContent = "Save instructions";
    saveBtn.addEventListener("click", async () => {
      saveBtn.textContent = "Saving…";
      try {
        await fetch(`/projects/${project.project_id}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ instructions: textarea.value }),
        });
      } finally {
        saveBtn.textContent = "Save instructions";
        await refresh();
      }
    });
    saveRow.appendChild(saveBtn);
    wrap.appendChild(saveRow);

    const filesLabel = document.createElement("label");
    filesLabel.textContent = `Files (${Object.keys(project.files || {}).length})`;
    wrap.appendChild(filesLabel);

    const fileList = document.createElement("div");
    fileList.className = "project-file-list";
    Object.entries(project.files || {}).forEach(([fileId, meta]) => {
      const row = document.createElement("div");
      row.className = "project-file";

      const name = document.createElement("span");
      name.className = "project-file-name";
      name.title = meta.filename;
      name.textContent = `${meta.filename} (${meta.chunk_count} chunk${meta.chunk_count === 1 ? "" : "s"})`;
      row.appendChild(name);

      const removeBtn = document.createElement("button");
      removeBtn.className = "project-icon-btn danger";
      removeBtn.textContent = "×";
      removeBtn.title = "Remove file";
      removeBtn.addEventListener("click", async () => {
        await fetch(`/projects/${project.project_id}/files/${fileId}`, { method: "DELETE" });
        await refresh();
      });
      row.appendChild(removeBtn);

      fileList.appendChild(row);
    });
    wrap.appendChild(fileList);

    const uploadLabel = document.createElement("label");
    uploadLabel.className = "project-upload-label";
    uploadLabel.textContent = "＋ Add file";
    const uploadInput = document.createElement("input");
    uploadInput.type = "file";
    uploadInput.style.display = "none";
    uploadInput.addEventListener("change", async () => {
      const file = uploadInput.files[0];
      if (!file) return;
      uploadLabel.textContent = "Uploading…";
      const formData = new FormData();
      formData.append("file", file);
      try {
        const resp = await fetch(`/projects/${project.project_id}/files`, {
          method: "POST",
          body: formData,
        });
        if (!resp.ok) {
          const data = await resp.json().catch(() => ({}));
          alert(`Upload failed: ${data.detail || resp.statusText}`);
        }
      } finally {
        uploadLabel.textContent = "＋ Add file";
        uploadInput.value = "";
        await refresh();
      }
    });
    uploadLabel.appendChild(uploadInput);
    wrap.appendChild(uploadLabel);

    const deleteRow = document.createElement("div");
    deleteRow.className = "button-row";
    const deleteBtn = document.createElement("button");
    deleteBtn.className = "secondary small";
    deleteBtn.type = "button";
    deleteBtn.textContent = "Delete project";
    deleteBtn.addEventListener("click", async () => {
      if (!confirm(`Delete project "${project.name}" and all its files? This can't be undone.`)) return;
      await fetch(`/projects/${project.project_id}`, { method: "DELETE" });
      if (activeProjectId === project.project_id) {
        activeProjectId = null;
        localStorage.removeItem("k9chat_active_project");
      }
      expandedId = null;
      await refresh();
    });
    deleteRow.appendChild(deleteBtn);
    wrap.appendChild(deleteRow);

    return wrap;
  }

  function render() {
    listEl.innerHTML = "";
    projects.forEach(project => {
      const item = document.createElement("div");
      item.className = "project-item" + (project.project_id === activeProjectId ? " active" : "");

      const row = document.createElement("div");
      row.className = "project-row";
      row.addEventListener("click", () => {
        setActive(project.project_id === activeProjectId ? null : project.project_id);
      });

      const col = document.createElement("div");
      col.className = "project-col";

      const name = document.createElement("div");
      name.className = "project-name";
      name.textContent = project.name;
      col.appendChild(name);

      const fileCount = Object.keys(project.files || {}).length;
      const meta = document.createElement("div");
      meta.className = "project-meta";
      meta.textContent = fileCount === 0 ? "No files" : `${fileCount} file${fileCount === 1 ? "" : "s"}`;
      col.appendChild(meta);

      row.appendChild(col);

      const manageBtn = document.createElement("button");
      manageBtn.className = "project-icon-btn";
      manageBtn.textContent = "⚙";
      manageBtn.title = "Manage project";
      manageBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        expandedId = expandedId === project.project_id ? null : project.project_id;
        render();
      });
      row.appendChild(manageBtn);

      item.appendChild(row);

      if (expandedId === project.project_id) {
        item.appendChild(buildManagePanel(project));
      }

      listEl.appendChild(item);
    });
  }

  newBtn.addEventListener("click", () => {
    const isOpen = newForm.style.display !== "none";
    newForm.style.display = isOpen ? "none" : "flex";
    if (!isOpen) newInput.focus();
  });

  async function createProject() {
    const name = newInput.value.trim();
    if (!name) return;
    newCreateBtn.disabled = true;
    try {
      const resp = await fetch("/projects", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      const project = await resp.json();
      newInput.value = "";
      newForm.style.display = "none";
      setActive(project.project_id);
      await refresh();
    } finally {
      newCreateBtn.disabled = false;
    }
  }

  newCreateBtn.addEventListener("click", createProject);
  newInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      createProject();
    }
  });

  refresh();

  return {
    get activeProjectId() { return activeProjectId; },
    refresh,
  };
})();
