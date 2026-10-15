// CareerPulse Dashboard JavaScript (100% Offline Vanilla JS)

document.addEventListener("DOMContentLoaded", () => {
    initNavigation();
    initTheme();
    loadOverview();
    loadJobs();
    loadCompanies();
    loadFilters();
    loadTelegram();
    loadScheduler();
    setupEventHandlers();

    // Auto-refresh stats and scheduler status every 15s
    setInterval(() => {
        loadScheduler();
        loadOverview();
    }, 15000);
});

// Toast notification helper
function showToast(message, type = "info") {
    const container = document.getElementById("toast-container");
    const toast = document.createElement("div");
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = "0";
        setTimeout(() => toast.remove(), 300);
    }, 3500);
}

// Navigation between tabs
function initNavigation() {
    const navItems = document.querySelectorAll(".nav-item");
    navItems.forEach(item => {
        item.addEventListener("click", () => {
            const tabId = item.getAttribute("data-tab");
            switchTab(tabId);
        });
    });
}

function switchTab(tabId) {
    document.querySelectorAll(".nav-item").forEach(el => el.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach(el => el.classList.remove("active"));

    const targetNav = document.querySelector(`[data-tab="${tabId}"]`);
    const targetPanel = document.getElementById(tabId);
    if (targetNav) targetNav.classList.add("active");
    if (targetPanel) targetPanel.classList.add("active");

    const titles = {
        "tab-overview": "Dashboard Overview",
        "tab-jobs": "Discovered Jobs Feed",
        "tab-companies": "Target Career Portals",
        "tab-filters": "Job Matching Filters",
        "tab-telegram": "Telegram Alerts",
        "tab-scheduler": "Scheduler & Operating Hours",
    };
    document.getElementById("page-title").textContent = titles[tabId] || "CareerPulse";
}

// Dark / Light Theme
function initTheme() {
    const toggle = document.getElementById("theme-toggle");
    const saved = localStorage.getItem("cp_theme") || "dark";
    document.documentElement.setAttribute("data-theme", saved);

    toggle.addEventListener("click", () => {
        const current = document.documentElement.getAttribute("data-theme");
        const next = current === "dark" ? "light" : "dark";
        document.documentElement.setAttribute("data-theme", next);
        localStorage.setItem("cp_theme", next);
    });
}

// OVERVIEW TAB
async function loadOverview() {
    try {
        const [compRes, jobsRes, schedRes] = await Promise.all([
            fetch("/api/companies").then(r => r.json()),
            fetch("/api/jobs?limit=5").then(r => r.json()),
            fetch("/api/scheduler/status").then(r => r.json()),
        ]);

        document.getElementById("stat-companies").textContent = compRes.length;
        document.getElementById("stat-jobs").textContent = jobsRes.total;

        let totalAlerts = 0;
        compRes.forEach(c => totalAlerts += (c.alerts_count || 0));
        document.getElementById("stat-alerts").textContent = totalAlerts;

        // Next run
        if (schedRes.next_run_at) {
            const nextDt = new Date(schedRes.next_run_at);
            document.getElementById("stat-next-run").textContent = nextDt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        } else {
            document.getElementById("stat-next-run").textContent = schedRes.is_running ? "Idle" : "Disabled";
        }

        // Window pill
        const pill = document.getElementById("window-status-pill");
        if (schedRes.in_active_window) {
            pill.className = "badge badge-success";
            pill.textContent = "Operating Window Active";
        } else {
            pill.className = "badge badge-warning";
            pill.textContent = "Outside Operating Hours";
        }

        // Recent Jobs list in overview
        const recentContainer = document.getElementById("overview-recent-jobs");
        if (jobsRes.jobs && jobsRes.jobs.length > 0) {
            recentContainer.innerHTML = jobsRes.jobs.map(j => `
                <div class="window-item mb-2">
                    <div>
                        <strong>${escapeHtml(j.title)}</strong>
                        <div class="subtext text-muted">${escapeHtml(j.company_name)} • ${escapeHtml(j.location || 'Unknown')}</div>
                    </div>
                    <a href="${escapeHtml(j.apply_url)}" target="_blank" class="btn btn-sm btn-primary">Apply →</a>
                </div>
            `).join("");
        }

        // Recent Companies in overview
        const compContainer = document.getElementById("overview-companies-list");
        if (compRes.length > 0) {
            compContainer.innerHTML = compRes.slice(0, 5).map(c => `
                <div class="window-item mb-2">
                    <div>
                        <strong>${escapeHtml(c.name)}</strong>
                        <span class="badge badge-info ml-2">${escapeHtml(c.ats_provider)}</span>
                    </div>
                    <span class="text-muted">${c.job_count || 0} jobs</span>
                </div>
            `).join("");
        }
    } catch (e) {
        console.error("Error loading overview:", e);
    }
}

// JOBS TAB
async function loadJobs() {
    const q = document.getElementById("job-search-input").value;
    const compId = document.getElementById("job-company-filter").value;
    const remoteOnly = document.getElementById("job-remote-only").checked;

    let url = `/api/jobs?limit=50`;
    if (q) url += `&q=${encodeURIComponent(q)}`;
    if (compId) url += `&company_id=${compId}`;
    if (remoteOnly) url += `&is_remote=true`;

    try {
        const res = await fetch(url).then(r => r.json());
        document.getElementById("jobs-count-badge").textContent = `${res.total} jobs`;

        const tbody = document.getElementById("jobs-table-body");
        if (!res.jobs || res.jobs.length === 0) {
            tbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted">No jobs matching current query.</td></tr>`;
            return;
        }

        tbody.innerHTML = res.jobs.map(j => {
            const remoteBadge = j.is_remote
                ? `<span class="badge badge-success">Remote</span>`
                : `<span class="badge badge-neutral">${escapeHtml(j.workplace_type || 'on-site')}</span>`;
            
            const alertBadge = j.alert_status === 'sent'
                ? `<span class="badge badge-success">Alerted</span>`
                : (j.alert_status === 'mock'
                    ? `<span class="badge badge-info">Mock Sent</span>`
                    : `<span class="badge badge-neutral">New</span>`);

            const dateStr = j.first_seen_at ? new Date(j.first_seen_at).toLocaleDateString() : 'Today';

            return `
                <tr>
                    <td><strong>${escapeHtml(j.title)}</strong></td>
                    <td>${escapeHtml(j.company_name)}</td>
                    <td>${escapeHtml(j.location || 'Unknown')}</td>
                    <td>${remoteBadge}</td>
                    <td>${dateStr}</td>
                    <td>${alertBadge}</td>
                    <td>
                        <a href="${escapeHtml(j.apply_url)}" target="_blank" class="btn btn-sm btn-primary">Apply ↗</a>
                    </td>
                </tr>
            `;
        }).join("");
    } catch (e) {
        console.error("Error loading jobs:", e);
    }
}

// COMPANIES TAB
async function loadCompanies() {
    try {
        const companies = await fetch("/api/companies").then(r => r.json());
        const tbody = document.getElementById("companies-table-body");
        const select = document.getElementById("job-company-filter");

        // Populate dropdown
        select.innerHTML = `<option value="">All Companies</option>` + companies.map(c => `
            <option value="${c.id}">${escapeHtml(c.name)}</option>
        `).join("");

        if (!companies || companies.length === 0) {
            tbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted">No target companies added yet.</td></tr>`;
            return;
        }

        tbody.innerHTML = companies.map(c => `
            <tr>
                <td><strong>${escapeHtml(c.name)}</strong></td>
                <td><span class="badge badge-info">${escapeHtml(c.ats_provider)}</span></td>
                <td><a href="${escapeHtml(c.career_url)}" target="_blank" class="btn-text">${escapeHtml(c.career_url.substring(0, 35))}...</a></td>
                <td>${c.job_count || 0}</td>
                <td>${c.alerts_count || 0}</td>
                <td>${c.last_scanned_at ? new Date(c.last_scanned_at).toLocaleTimeString() : 'Never'}</td>
                <td>
                    <button class="btn btn-sm btn-secondary" onclick="scanSingleCompany(${c.id})">Scan</button>
                    <button class="btn btn-sm btn-danger" onclick="deleteCompany(${c.id})">Delete</button>
                </td>
            </tr>
        `).join("");
    } catch (e) {
        console.error("Error loading companies:", e);
    }
}

async function scanSingleCompany(id) {
    showToast("Starting scan for company...", "info");
    try {
        const res = await fetch("/api/scan/trigger", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ company_id: id }),
        }).then(r => r.json());

        showToast(`Scan complete: found ${res.total_jobs_found} jobs, ${res.new_alerts_sent} new alerts!`, "success");
        loadCompanies();
        loadJobs();
        loadOverview();
    } catch (e) {
        showToast(`Scan failed: ${e.message}`, "error");
    }
}

async function deleteCompany(id) {
    if (!confirm("Are you sure you want to delete this company and its jobs?")) return;
    try {
        await fetch(`/api/companies/${id}`, { method: "DELETE" });
        showToast("Company removed", "info");
        loadCompanies();
        loadJobs();
        loadOverview();
    } catch (e) {
        showToast("Failed to delete company", "error");
    }
}

// REGISTRY FUNCTIONS
function renderSuggestions(results) {
    const dropdown = document.getElementById("registry-suggestions");
    if (!dropdown) return;

    if (!Array.isArray(results) || results.length === 0) {
        dropdown.innerHTML = `<div class="suggestion-item text-muted">No matching companies found in registry</div>`;
        dropdown.classList.remove("hidden");
        return;
    }

    dropdown.innerHTML = results.map(c => {
        const ats = (c.ats || 'custom').toUpperCase();
        const badgeClass = c.ats === 'greenhouse' ? 'badge-success' : (c.ats === 'lever' ? 'badge-info' : (c.ats === 'ashby' ? 'badge-warning' : 'badge-neutral'));
        const isAdded = !!c.already_added;
        const itemClass = isAdded ? 'suggestion-item already-added' : 'suggestion-item';
        const addedBadge = isAdded ? `<span class="badge badge-neutral" style="margin-left: 0.5rem; opacity: 0.85;">Already Added ✓</span>` : '';

        return `
            <div class="${itemClass}" data-name="${escapeHtml(c.name)}" data-url="${escapeHtml(c.career_url)}" data-ats="${escapeHtml(c.ats || 'custom')}" data-added="${isAdded}">
                <div class="suggestion-info">
                    <div style="display: flex; align-items: center;">
                        <strong>${escapeHtml(c.name)}</strong>
                        ${addedBadge}
                    </div>
                    <span class="badge ${badgeClass}">${escapeHtml(ats)}</span>
                </div>
                <div class="suggestion-url text-muted">${escapeHtml(c.career_url)}</div>
            </div>
        `;
    }).join("");

    dropdown.querySelectorAll(".suggestion-item").forEach(item => {
        item.addEventListener("click", () => {
            if (item.dataset.added === "true") {
                showToast(`${item.dataset.name} is already in your monitored target list!`, "info");
                return;
            }
            selectRegistryCompany(item);
        });
    });

    dropdown.classList.remove("hidden");
}

function selectRegistryCompany(item) {
    const name = item.dataset ? item.dataset.name : item.name;
    const url = item.dataset ? item.dataset.url : (item.career_url || item.url);
    const ats = (item.dataset ? item.dataset.ats : item.ats) || "custom";

    const compSearchInput = document.getElementById("company-name-search");
    const nameEl = document.getElementById("registry-confirm-name");
    const atsEl = document.getElementById("registry-confirm-ats");
    const urlEl = document.getElementById("registry-confirm-url");
    const cardEl = document.getElementById("registry-confirm-card");
    const dropdown = document.getElementById("registry-suggestions");
    const addBtn = document.getElementById("btn-add-from-registry");

    if (compSearchInput) compSearchInput.value = name;
    if (nameEl) nameEl.textContent = name;
    if (atsEl) {
        atsEl.textContent = ats.toUpperCase();
        atsEl.className = `badge ${ats.toLowerCase() === 'greenhouse' ? 'badge-success' : (ats.toLowerCase() === 'lever' ? 'badge-info' : (ats.toLowerCase() === 'ashby' ? 'badge-warning' : 'badge-neutral'))}`;
    }
    if (urlEl) {
        urlEl.textContent = url;
        urlEl.href = url;
    }

    if (addBtn) {
        addBtn.dataset.name = name;
        addBtn.dataset.url = url;
        addBtn.dataset.ats = ats;
    }

    if (dropdown) dropdown.classList.add("hidden");
    if (cardEl) cardEl.classList.remove("hidden");
}


// FILTERS TAB
async function loadFilters() {
    try {
        const f = await fetch("/api/filters").then(r => r.json());
        document.getElementById("filter-target-titles").value = (f.target_titles || []).join(", ");
        document.getElementById("filter-required-skills").value = (f.required_skills || []).join(", ");
        document.getElementById("filter-skills-mode").value = f.skills_match_mode || "any";
        document.getElementById("filter-neg-titles").value = (f.negative_title_keywords || []).join(", ");
        document.getElementById("filter-neg-desc").value = (f.negative_description_keywords || []).join(", ");
        document.getElementById("filter-preferred-skills").value = (f.preferred_skills || []).join(", ");
        document.getElementById("filter-allowed-locations").value = (f.allowed_locations || []).join(", ");
        document.getElementById("filter-excluded-locations").value = (f.excluded_locations || []).join(", ");
        document.getElementById("filter-remote-only").checked = !!f.remote_only;
    } catch (e) {
        console.error("Error loading filters:", e);
    }
}

async function saveFilters() {
    const parseList = (str) => (str || "").split(",").map(s => s.trim()).filter(s => s.length > 0);
    const body = {
        target_titles: parseList(document.getElementById("filter-target-titles").value),
        required_skills: parseList(document.getElementById("filter-required-skills").value),
        skills_match_mode: document.getElementById("filter-skills-mode").value,
        negative_title_keywords: parseList(document.getElementById("filter-neg-titles").value),
        negative_description_keywords: parseList(document.getElementById("filter-neg-desc").value),
        preferred_skills: parseList(document.getElementById("filter-preferred-skills").value),
        allowed_locations: parseList(document.getElementById("filter-allowed-locations").value),
        excluded_locations: parseList(document.getElementById("filter-excluded-locations").value),
        remote_only: document.getElementById("filter-remote-only").checked,
    };

    try {
        await fetch("/api/filters", {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });
        showToast("Matching filters saved successfully!", "success");
    } catch (e) {
        showToast("Failed to save filters", "error");
    }
}

// TELEGRAM TAB
async function loadTelegram() {
    try {
        const tg = await fetch("/api/telegram/settings").then(r => r.json());
        document.getElementById("tg-bot-token").value = tg.bot_token || "";
        document.getElementById("tg-chat-id").value = tg.chat_id || "";
        document.getElementById("tg-mock-mode").checked = !!tg.mock_mode;
    } catch (e) {
        console.error("Error loading telegram settings:", e);
    }
}

async function saveTelegram() {
    const body = {
        bot_token: document.getElementById("tg-bot-token").value,
        chat_id: document.getElementById("tg-chat-id").value,
        mock_mode: document.getElementById("tg-mock-mode").checked,
    };

    try {
        await fetch("/api/telegram/settings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });
        showToast("Telegram settings saved!", "success");
    } catch (e) {
        showToast("Failed to save Telegram settings", "error");
    }
}

async function testTelegram() {
    const status = document.getElementById("tg-test-status");
    status.textContent = "Sending test alert...";
    status.className = "test-status text-muted";

    try {
        const res = await fetch("/api/telegram/test", { method: "POST" }).then(r => r.json());
        if (res.success) {
            status.textContent = res.mock ? "Mock alert logged successfully!" : "Alert sent to your Telegram chat!";
            status.className = "test-status text-success";
            showToast("Test notification delivered!", "success");
        } else {
            status.textContent = "Failed to deliver";
            status.className = "test-status text-danger";
        }
    } catch (e) {
        status.textContent = `Error: ${e.message}`;
        status.className = "test-status text-danger";
        showToast("Telegram test failed", "error");
    }
}

// SCHEDULER TAB
async function loadScheduler() {
    try {
        const s = await fetch("/api/scheduler/status").then(r => r.json());
        document.getElementById("sched-enabled").checked = !!s.config.enabled;
        document.getElementById("sched-interval").value = s.config.interval_minutes || 60;
        document.getElementById("sched-windows-enabled").checked = !!s.config.time_windows_enabled;

        const statusText = document.getElementById("scheduler-status-text");
        statusText.textContent = s.is_running
            ? (s.in_active_window ? "Scheduler Active" : "Outside Operating Hours")
            : "Scheduler Paused";

        // Render windows
        const wContainer = document.getElementById("windows-list");
        wContainer.innerHTML = (s.config.time_windows || []).map(w => `
            <div class="window-item">
                <span>🕒 Active Window: <strong>${escapeHtml(w.start)}</strong> to <strong>${escapeHtml(w.end)}</strong></span>
                <span class="badge badge-info">Configured</span>
            </div>
        `).join("");
    } catch (e) {
        console.error("Error loading scheduler:", e);
    }
}

async function saveScheduler() {
    const body = {
        enabled: document.getElementById("sched-enabled").checked,
        interval_minutes: parseInt(document.getElementById("sched-interval").value, 10),
        time_windows_enabled: document.getElementById("sched-windows-enabled").checked,
        time_windows: [
            { start: "10:00", end: "18:30" },
            { start: "19:00", end: "02:00" }
        ],
    };

    try {
        await fetch("/api/scheduler/config", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });
        showToast("Scheduler settings saved!", "success");
        loadScheduler();
    } catch (e) {
        showToast("Failed to save scheduler", "error");
    }
}

// EVENT HANDLERS
function setupEventHandlers() {
    // Quick scan all
    document.getElementById("btn-quick-scan").addEventListener("click", async () => {
        const btn = document.getElementById("btn-quick-scan");
        btn.disabled = true;
        btn.querySelector("span").textContent = "Scanning Portals...";
        showToast("Scanning all target portals...", "info");

        try {
            const report = await fetch("/api/scan/trigger", { method: "POST" }).then(r => r.json());
            showToast(`Scan complete: ${report.companies_scanned} portals checked, ${report.total_jobs_found} jobs found, ${report.new_alerts_sent} alerts dispatched!`, "success");
            loadOverview();
            loadJobs();
            loadCompanies();
        } catch (e) {
            showToast(`Scan failed: ${e.message}`, "error");
        } finally {
            btn.disabled = false;
            btn.querySelector("span").textContent = "Scan All Portals Now";
        }
    });

    // Curated Registry Search & Confirm
    const compSearchInput = document.getElementById("company-name-search");
    const regSuggestions = document.getElementById("registry-suggestions");
    const btnAddFromRegistry = document.getElementById("btn-add-from-registry");
    const btnShowManual = document.getElementById("btn-show-manual");
    const manualAddSection = document.getElementById("manual-add-section");

    async function fetchAndRenderSuggestions(query) {
        try {
            const res = await fetch(`/api/companies/registry?q=${encodeURIComponent(query || "")}`).then(r => r.json());
            renderSuggestions(res);
        } catch (e) {
            console.error("Failed to fetch registry suggestions:", e);
        }
    }

    if (compSearchInput) {
        compSearchInput.addEventListener(
            "input",
            debounce(() => {
                const query = compSearchInput.value.trim();
                fetchAndRenderSuggestions(query);
            }, 200)
        );

        compSearchInput.addEventListener("focus", () => {
            const query = compSearchInput.value.trim();
            fetchAndRenderSuggestions(query);
        });

        compSearchInput.addEventListener("keydown", (e) => {
            if (e.key === "Escape") {
                if (regSuggestions) regSuggestions.classList.add("hidden");
            } else if (e.key === "Enter") {
                e.preventDefault();
                if (regSuggestions && !regSuggestions.classList.contains("hidden")) {
                    const firstItem = regSuggestions.querySelector(".suggestion-item[data-name]:not(.already-added)");
                    if (firstItem) selectRegistryCompany(firstItem);
                }
            }
        });

        document.addEventListener("click", (e) => {
            if (regSuggestions && !compSearchInput.contains(e.target) && !regSuggestions.contains(e.target)) {
                regSuggestions.classList.add("hidden");
            }
        });
    }

    if (btnAddFromRegistry) {
        btnAddFromRegistry.addEventListener("click", async () => {
            const name = btnAddFromRegistry.dataset.name;
            const career_url = btnAddFromRegistry.dataset.url;
            if (!name || !career_url) return;

            btnAddFromRegistry.disabled = true;
            try {
                const response = await fetch("/api/companies", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ name, career_url }),
                });
                const res = await response.json();

                if (response.ok && res.id) {
                    showToast(`Added ${res.name} (${res.ats_provider})!`, "success");
                    const confirmCard = document.getElementById("registry-confirm-card");
                    if (confirmCard) confirmCard.classList.add("hidden");
                    if (compSearchInput) compSearchInput.value = "";
                    delete btnAddFromRegistry.dataset.name;
                    delete btnAddFromRegistry.dataset.url;
                    delete btnAddFromRegistry.dataset.ats;
                    await loadCompanies();
                    await loadOverview();
                } else {
                    showToast(res.detail || "Error adding company", "error");
                }
            } catch (e) {
                showToast(`Failed to add company: ${e.message}`, "error");
            } finally {
                btnAddFromRegistry.disabled = false;
            }
        });
    }

    if (btnShowManual && manualAddSection) {
        btnShowManual.addEventListener("click", () => {
            manualAddSection.classList.toggle("hidden");
        });
    }

    // Add company form with auto-detection
    const compUrlInput = document.getElementById("company-url");
    const previewDiv = document.getElementById("detect-preview");

    compUrlInput.addEventListener("input", async () => {
        const url = compUrlInput.value.trim();
        if (url.length > 8) {
            try {
                const det = await fetch("/api/companies/detect", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ url }),
                }).then(r => r.json());

                previewDiv.classList.remove("hidden");
                if (det.detected) {
                    previewDiv.innerHTML = `<span class="badge badge-success">Detected: ${det.provider.toUpperCase()} (${det.identifier})</span>`;
                } else {
                    previewDiv.innerHTML = `<span class="badge badge-warning">Custom portal (Playwright / HTML DOM fallback)</span>`;
                }
            } catch (e) {}
        } else {
            previewDiv.classList.add("hidden");
        }
    });

    document.getElementById("add-company-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        const name = document.getElementById("company-name").value;
        const career_url = compUrlInput.value;

        try {
            const res = await fetch("/api/companies", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name, career_url }),
            }).then(r => r.json());

            if (res.id) {
                showToast(`Added ${name} (${res.ats_provider})!`, "success");
                document.getElementById("add-company-form").reset();
                previewDiv.classList.add("hidden");
                loadCompanies();
                loadOverview();
            } else {
                showToast(res.detail || "Error adding company", "error");
            }
        } catch (e) {
            showToast("Failed to add company", "error");
        }
    });

    // Job search & filters
    document.getElementById("job-search-input").addEventListener("input", debounce(loadJobs, 300));
    document.getElementById("job-company-filter").addEventListener("change", loadJobs);
    document.getElementById("job-remote-only").addEventListener("change", loadJobs);

    // Save buttons
    document.getElementById("btn-save-filters").addEventListener("click", saveFilters);
    document.getElementById("btn-save-telegram").addEventListener("click", saveTelegram);
    document.getElementById("btn-test-telegram").addEventListener("click", testTelegram);
    document.getElementById("btn-save-scheduler").addEventListener("click", saveScheduler);
}

function debounce(func, wait) {
    let timeout;
    return (...args) => {
        clearTimeout(timeout);
        timeout = setTimeout(() => func(...args), wait);
    };
}

function escapeHtml(str) {
    if (!str) return "";
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}
