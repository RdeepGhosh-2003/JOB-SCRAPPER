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
    loadLogs();
    loadPipeline();
    setupEventHandlers();

    // Auto-refresh stats, scheduler status, and logs every 15s
    setInterval(() => {
        loadScheduler();
        loadOverview();
        loadLogs();
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
        "tab-pipeline": "Live Pipeline Monitor",
        "tab-jobs": "Discovered Jobs Feed",
        "tab-companies": "Target Career Portals",
        "tab-filters": "Job Matching Filters",
        "tab-telegram": "Telegram Alerts",
        "tab-scheduler": "Scheduler & Operating Hours",
        "tab-logs": "Activity Logs",
    };
    document.getElementById("page-title").textContent = titles[tabId] || "CareerPulse";

    if (tabId === "tab-pipeline") {
        loadPipeline();
    }
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
        const [compRes, jobsRes, schedRes, statsRes] = await Promise.all([
            fetch("/api/companies").then(r => r.json()),
            fetch("/api/jobs?limit=5&matched_only=true").then(r => r.json()),
            fetch("/api/scheduler/status").then(r => r.json()),
            fetch("/api/overview/stats").then(r => r.json()),
        ]);

        // 1. Matched Today
        const elMatchedToday = document.getElementById("stat-matched-today");
        if (elMatchedToday) elMatchedToday.textContent = statsRes.matched_today || 0;

        // 2. Rejected
        const elRejected = document.getElementById("stat-rejected");
        if (elRejected) elRejected.textContent = statsRes.jobs_rejected || 0;

        // 3. Last Scan (Company + Time)
        const elLastScanComp = document.getElementById("stat-last-scan-company");
        const elLastScanTime = document.getElementById("stat-last-scan-time");
        if (elLastScanComp && elLastScanTime) {
            if (statsRes.last_scan && statsRes.last_scan.company_name && statsRes.last_scan.company_name !== "None") {
                elLastScanComp.textContent = statsRes.last_scan.company_name;
                elLastScanTime.textContent = formatRelativeTime(statsRes.last_scan.scanned_at);
            } else {
                elLastScanComp.textContent = "—";
                elLastScanTime.textContent = "Never";
            }
        }

        // 4. Match Rate
        const elMatchRate = document.getElementById("stat-match-rate");
        if (elMatchRate) {
            const rate = typeof statsRes.match_rate === "number" ? statsRes.match_rate.toFixed(1) : "0.0";
            elMatchRate.textContent = `${rate}%`;
        }

        // Window pill
        const pill = document.getElementById("window-status-pill");
        if (pill) {
            if (schedRes.in_active_window) {
                pill.className = "badge badge-success";
                pill.textContent = "Operating Window Active";
            } else {
                pill.className = "badge badge-warning";
                pill.textContent = "Outside Operating Hours";
            }
        }

        // Recent Matching Jobs panel
        const recentContainer = document.getElementById("overview-recent-jobs");
        if (recentContainer) {
            if (jobsRes.jobs && jobsRes.jobs.length > 0) {
                recentContainer.innerHTML = jobsRes.jobs.map(j => `
                    <div class="window-item mb-2" style="display: flex; justify-content: space-between; align-items: center;">
                        <div>
                            <strong>${escapeHtml(j.title)}</strong>
                            <div class="subtext text-muted">${escapeHtml(j.company_name)} • ${escapeHtml(j.location || 'Unknown')}</div>
                        </div>
                        <a href="${escapeHtml(j.apply_url || j.url)}" target="_blank" class="btn btn-sm btn-primary">Apply →</a>
                    </div>
                `).join("");
            } else {
                recentContainer.innerHTML = `<p class="text-muted">No matched jobs yet — run a scan to see results here.</p>`;
            }
        }

        // Last Scan Summary: Max 6 companies ordered by last_scanned_at DESC
        const compContainer = document.getElementById("overview-companies-list");
        if (compContainer) {
            if (compRes && compRes.length > 0) {
                const sorted = [...compRes].sort((a, b) => {
                    const tA = a.last_scanned_at ? new Date(a.last_scanned_at.endsWith("Z") ? a.last_scanned_at : a.last_scanned_at + "Z").getTime() : 0;
                    const tB = b.last_scanned_at ? new Date(b.last_scanned_at.endsWith("Z") ? b.last_scanned_at : b.last_scanned_at + "Z").getTime() : 0;
                    return tB - tA;
                });
                const top6 = sorted.slice(0, 6);

                compContainer.innerHTML = top6.map(c => {
                    let statusBadge = `<span class="badge badge-neutral">—</span>`;
                    if (c.last_scanned_at) {
                        if (c.scan_status === 'success') {
                            statusBadge = `<span class="badge badge-success" title="Scan succeeded">✅</span>`;
                        } else if (c.scan_status === 'failed') {
                            statusBadge = `<span class="badge badge-danger" title="${escapeHtml(c.last_error || 'Scan failed')}">❌</span>`;
                        }
                    }
                    const relativeTime = formatRelativeTime(c.last_scanned_at);
                    const jobsCount = c.job_count || 0;
                    const jobsText = `${jobsCount} ${jobsCount === 1 ? 'job' : 'jobs'} found`;

                    return `
                        <div class="window-item mb-2" style="display: flex; justify-content: space-between; align-items: center; padding: 0.6rem 0.85rem;">
                            <div style="display: flex; flex-direction: column; gap: 0.2rem; min-width: 0;">
                                <div style="display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap;">
                                    <strong>${escapeHtml(c.name)}</strong>
                                    <span class="badge badge-info">${escapeHtml((c.ats_provider || 'custom').toUpperCase())}</span>
                                    ${statusBadge}
                                </div>
                                <div class="subtext text-muted" style="font-size: 0.78rem;">
                                    Scanned ${escapeHtml(relativeTime)}
                                </div>
                            </div>
                            <div style="text-align: right; white-space: nowrap; font-size: 0.85rem; font-weight: 500;">
                                <span class="text-muted">${escapeHtml(jobsText)}</span>
                            </div>
                        </div>
                    `;
                }).join("");
            } else {
                compContainer.innerHTML = `<p class="text-muted">No monitored portals registered yet.</p>`;
            }
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
                        <div class="flex-gap">
                            <a href="${escapeHtml(j.apply_url)}" target="_blank" class="btn btn-sm btn-primary">Apply ↗</a>
                            <button class="btn btn-sm btn-danger" onclick="deleteJob(${j.id}, this)">Delete</button>
                        </div>
                    </td>
                </tr>
            `;
        }).join("");
    } catch (e) {
        console.error("Error loading jobs:", e);
    }
}

async function deleteJob(id, btnElement) {
    const row = btnElement ? btnElement.closest("tr") : null;
    if (row) {
        row.style.opacity = "0.3";
        row.style.pointerEvents = "none";
    }

    try {
        const res = await fetch(`/api/jobs/${id}`, { method: "DELETE" }).then(r => r.json());
        if (res.success) {
            showToast("Job removed", "info");
            loadJobs();
            loadOverview();
        } else {
            if (row) {
                row.style.opacity = "1";
                row.style.pointerEvents = "auto";
            }
            showToast(res.detail || "Failed to delete job", "error");
        }
    } catch (e) {
        if (row) {
            row.style.opacity = "1";
            row.style.pointerEvents = "auto";
        }
        showToast("Failed to delete job", "error");
    }
}

async function clearAllJobs() {
    const compFilter = document.getElementById("job-company-filter").value;
    const msg = compFilter
        ? "Are you sure you want to delete all discovered jobs for the selected company?"
        : "Are you sure you want to delete ALL discovered jobs?";
    if (!confirm(msg)) return;

    try {
        let url = "/api/jobs";
        if (compFilter) url += `?company_id=${compFilter}`;
        const res = await fetch(url, { method: "DELETE" }).then(r => r.json());
        showToast(`Deleted ${res.deleted_count || 0} job listings`, "info");
        loadJobs();
        loadOverview();
        loadCompanies();
    } catch (e) {
        showToast("Failed to clear jobs", "error");
    }
}

// COMPANIES TAB
let cachedCompanies = [];

function sortCompanies(companies, sortBy) {
    const list = [...companies];
    switch (sortBy) {
        case "name_asc":
            return list.sort((a, b) => (a.name || "").localeCompare(b.name || "", undefined, { sensitivity: "base" }));
        case "name_desc":
            return list.sort((a, b) => (b.name || "").localeCompare(a.name || "", undefined, { sensitivity: "base" }));
        case "jobs_desc":
            return list.sort((a, b) => (b.job_count || 0) - (a.job_count || 0));
        case "jobs_asc":
            return list.sort((a, b) => (a.job_count || 0) - (b.job_count || 0));
        case "alerts_desc":
            return list.sort((a, b) => (b.alerts_count || 0) - (a.alerts_count || 0));
        case "alerts_asc":
            return list.sort((a, b) => (a.alerts_count || 0) - (b.alerts_count || 0));
        case "last_scan_desc":
            return list.sort((a, b) => {
                const timeA = a.last_scanned_at ? new Date(a.last_scanned_at).getTime() : 0;
                const timeB = b.last_scanned_at ? new Date(b.last_scanned_at).getTime() : 0;
                return timeB - timeA;
            });
        case "last_scan_asc":
            return list.sort((a, b) => {
                const timeA = a.last_scanned_at ? new Date(a.last_scanned_at).getTime() : 0;
                const timeB = b.last_scanned_at ? new Date(b.last_scanned_at).getTime() : 0;
                return timeA - timeB;
            });
        case "recent":
        default:
            return list.sort((a, b) => {
                const timeA = a.created_at ? new Date(a.created_at).getTime() : (a.id || 0);
                const timeB = b.created_at ? new Date(b.created_at).getTime() : (b.id || 0);
                return timeB - timeA;
            });
    }
}

function renderCompaniesTable() {
    const tbody = document.getElementById("companies-table-body");
    const countBadge = document.getElementById("companies-count-badge");
    const sortSelect = document.getElementById("company-sort-by");
    const sortBy = sortSelect ? sortSelect.value : "recent";

    if (countBadge) {
        countBadge.textContent = `${cachedCompanies.length} ${cachedCompanies.length === 1 ? 'company' : 'companies'}`;
    }

    if (!cachedCompanies || cachedCompanies.length === 0) {
        tbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted">No target companies added yet.</td></tr>`;
        return;
    }

    const sorted = sortCompanies(cachedCompanies, sortBy);

    tbody.innerHTML = sorted.map(c => `
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
}

async function loadCompanies() {
    try {
        const companies = await fetch("/api/companies").then(r => r.json());
        cachedCompanies = Array.isArray(companies) ? companies : [];

        // Populate dropdown on jobs tab
        const select = document.getElementById("job-company-filter");
        if (select) {
            select.innerHTML = `<option value="">All Companies</option>` + cachedCompanies.map(c => `
                <option value="${c.id}">${escapeHtml(c.name)}</option>
            `).join("");
        }

        renderCompaniesTable();
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
            loadPipeline();
            const report = await fetch("/api/scan/trigger", { method: "POST" }).then(r => r.json());
            showToast(`Scan complete: ${report.companies_scanned} portals checked, ${report.total_jobs_found} jobs found, ${report.new_alerts_sent} alerts dispatched!`, "success");
            loadOverview();
            loadJobs();
            loadCompanies();
            loadPipeline();
        } catch (e) {
            showToast(`Scan failed: ${e.message}`, "error");
            loadPipeline();
        } finally {
            btn.disabled = false;
            btn.querySelector("span").textContent = "Scan All Portals Now";
        }
    });

    // Inline pipeline scan trigger
    const btnPipelineScan = document.getElementById("btn-pipeline-run-scan");
    if (btnPipelineScan) {
        btnPipelineScan.addEventListener("click", async () => {
            btnPipelineScan.disabled = true;
            btnPipelineScan.querySelector("span").textContent = "Running Pipeline...";
            showToast("Executing live parallel pipeline scan across all portals...", "info");
            try {
                loadPipeline();
                const report = await fetch("/api/scan/trigger", { method: "POST" }).then(r => r.json());
                showToast(`Pipeline scan complete: ${report.companies_scanned} portals checked, ${report.total_jobs_found} jobs found, ${report.new_alerts_sent} alerts sent!`, "success");
                loadOverview();
                loadJobs();
                loadCompanies();
                loadPipeline();
            } catch (e) {
                showToast(`Pipeline scan failed: ${e.message}`, "error");
                loadPipeline();
            } finally {
                btnPipelineScan.disabled = false;
                btnPipelineScan.querySelector("span").textContent = "Run Pipeline Now";
            }
        });
    }

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

    const btnClearJobs = document.getElementById("btn-clear-jobs");
    if (btnClearJobs) {
        btnClearJobs.addEventListener("click", clearAllJobs);
    }

    // Company sort dropdown & table header sorting
    const companySortSelect = document.getElementById("company-sort-by");
    if (companySortSelect) {
        companySortSelect.addEventListener("change", () => {
            renderCompaniesTable();
        });
    }

    document.querySelectorAll(".sortable-th").forEach(th => {
        th.addEventListener("click", () => {
            const field = th.dataset.sort;
            if (!companySortSelect) return;

            const current = companySortSelect.value;
            let nextSort = "recent";

            if (field === "name") {
                nextSort = current === "name_asc" ? "name_desc" : "name_asc";
            } else if (field === "jobs") {
                nextSort = current === "jobs_desc" ? "jobs_asc" : "jobs_desc";
            } else if (field === "alerts") {
                nextSort = current === "alerts_desc" ? "alerts_asc" : "alerts_desc";
            } else if (field === "last_scan") {
                nextSort = current === "last_scan_desc" ? "last_scan_asc" : "last_scan_desc";
            }

            companySortSelect.value = nextSort;
            renderCompaniesTable();
        });
    });

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

function formatRelativeTime(dateStr) {
    if (!dateStr) return "Never";
    let date = new Date(dateStr.endsWith("Z") ? dateStr : dateStr + "Z");
    if (isNaN(date.getTime())) {
        date = new Date(dateStr);
        if (isNaN(date.getTime())) return "Never";
    }
    const diffSec = Math.floor((Date.now() - date.getTime()) / 1000);
    if (diffSec < 0 || diffSec < 60) return "Just now";
    const diffMin = Math.floor(diffSec / 60);
    if (diffMin < 60) return `${diffMin} min ago`;
    const diffHours = Math.floor(diffMin / 60);
    if (diffHours < 24) return `${diffHours} hr${diffHours > 1 ? 's' : ''} ago`;
    const diffDays = Math.floor(diffHours / 24);
    return `${diffDays} day${diffDays > 1 ? 's' : ''} ago`;
}

// ACTIVITY LOGS TAB
async function loadLogs() {
    const tbody = document.getElementById("logs-table-body");
    if (!tbody) return;

    try {
        const logs = await fetch("/api/logs?limit=100").then(r => r.json());
        if (!logs || logs.length === 0) {
            tbody.innerHTML = `<tr><td colspan="8" class="text-center text-muted py-4">No scan activity recorded yet. Run a scan to see logs.</td></tr>`;
            return;
        }

        tbody.innerHTML = logs.map(l => {
            let rowClass = "log-row-info";
            let statusBadge = `<span class="badge badge-info">ℹ Info</span>`;
            let titleAttr = "";

            if (l.status === "failed") {
                rowClass = "log-row-error";
                statusBadge = `<span class="badge badge-danger">❌ Failed</span>`;
                if (l.error_message) {
                    titleAttr = ` title="${escapeHtml(l.error_message)}"`;
                }
            } else if (l.status === "warning") {
                rowClass = "log-row-warning";
                statusBadge = `<span class="badge badge-warning">⚠ Warning</span>`;
                if (l.error_message) {
                    titleAttr = ` title="${escapeHtml(l.error_message)}"`;
                }
            } else if (l.status === "success") {
                if (l.jobs_matched > 0) {
                    rowClass = "log-row-success";
                } else {
                    rowClass = "log-row-info";
                }
                statusBadge = `<span class="badge badge-success">✅ Success</span>`;
            }

            const dateStr = l.scanned_at ? new Date(l.scanned_at).toLocaleString() : "-";
            const durationStr = `${Number(l.duration_seconds || 0).toFixed(1)}s`;

            return `
                <tr class="${rowClass}"${titleAttr}>
                    <td>${escapeHtml(dateStr)}</td>
                    <td><strong>${escapeHtml(l.company_name)}</strong></td>
                    <td><span class="badge badge-info">${escapeHtml((l.provider || 'custom').toUpperCase())}</span></td>
                    <td>${Number(l.jobs_found || 0)}</td>
                    <td><strong>${Number(l.jobs_matched || 0)}</strong></td>
                    <td>${Number(l.alerts_sent || 0)}</td>
                    <td>${durationStr}</td>
                    <td>${statusBadge}</td>
                </tr>
            `;
        }).join("");
    } catch (err) {
        console.error("Error loading scan logs:", err);
        tbody.innerHTML = `<tr><td colspan="8" class="text-center text-muted py-4">Error loading activity logs. Check console.</td></tr>`;
    }
}

// LIVE PIPELINE FLOWCHART TAB
let pipelinePollTimer = null;
let currentPipelineLayout = localStorage.getItem("cp_pipeline_layout") || "vertical";

function setPipelineLayout(layout) {
    currentPipelineLayout = layout === "horizontal" ? "horizontal" : "vertical";
    localStorage.setItem("cp_pipeline_layout", currentPipelineLayout);

    const btnVert = document.getElementById("btn-layout-vertical");
    const btnHoriz = document.getElementById("btn-layout-horizontal");
    if (btnVert) btnVert.classList.toggle("active", currentPipelineLayout === "vertical");
    if (btnHoriz) btnHoriz.classList.toggle("active", currentPipelineLayout === "horizontal");

    const flowContainer = document.getElementById("pipeline-flow");
    if (flowContainer) {
        flowContainer.className = `pipeline-flow ${currentPipelineLayout}`;
        const arrow = currentPipelineLayout === "horizontal" ? "→" : "↓";
        flowContainer.querySelectorAll(".pipeline-connector").forEach(el => {
            el.textContent = arrow;
        });
    }
}

function toggleFailingPortals(btn) {
    const drawer = btn.nextElementSibling;
    if (!drawer) return;
    const isHidden = drawer.classList.contains("hidden");
    if (isHidden) {
        drawer.classList.remove("hidden");
        btn.textContent = btn.textContent.replace("▾", "▴");
    } else {
        drawer.classList.add("hidden");
        btn.textContent = btn.textContent.replace("▴", "▾");
    }
}

function renderMetaChips(key, meta) {
    if (!meta) return "";
    const chips = [];
    if (key === "scheduler") {
        if (meta.interval_minutes) chips.push(`<span class="meta-chip">Interval: <strong>${meta.interval_minutes}m</strong></span>`);
        chips.push(`<span class="meta-chip">Window: <strong>${meta.in_active_window ? "Active" : "Outside"}</strong></span>`);
        if (meta.total_runs !== undefined) chips.push(`<span class="meta-chip">Runs: <strong>${meta.total_runs}</strong></span>`);
        if (meta.next_run_at) {
            const nextTime = new Date(meta.next_run_at).toLocaleTimeString();
            chips.push(`<span class="meta-chip">Next: <strong>${nextTime}</strong></span>`);
        }
    } else if (key === "companies") {
        if (meta.total !== undefined) chips.push(`<span class="meta-chip">Total: <strong>${meta.total}</strong></span>`);
        if (meta.active !== undefined) chips.push(`<span class="meta-chip">Active: <strong>${meta.active}</strong></span>`);
        if (meta.failed !== undefined) chips.push(`<span class="meta-chip" style="${meta.failed > 0 ? 'color: var(--danger);' : ''}">Failing: <strong>${meta.failed}</strong></span>`);
    } else if (key === "adapter") {
        chips.push(`<span class="meta-chip">Protocols: <strong>5 Active</strong></span>`);
        if (meta.total_found !== undefined) chips.push(`<span class="meta-chip">Yield: <strong>${meta.total_found} Jobs</strong></span>`);
    } else if (key === "matcher") {
        if (meta.match_rate !== undefined) chips.push(`<span class="meta-chip">Match Rate: <strong>${meta.match_rate}%</strong></span>`);
        if (meta.matched_today !== undefined) chips.push(`<span class="meta-chip">Matched: <strong>${meta.matched_today}</strong></span>`);
        if (meta.jobs_rejected !== undefined) chips.push(`<span class="meta-chip">Filtered: <strong>${meta.jobs_rejected}</strong></span>`);
    } else if (key === "database") {
        chips.push(`<span class="meta-chip">Mode: <strong>WAL Active</strong></span>`);
        if (meta.total_jobs !== undefined) chips.push(`<span class="meta-chip">Indexed: <strong>${meta.total_jobs} Jobs</strong></span>`);
        chips.push(`<span class="meta-chip">Dedup: <strong>Active</strong></span>`);
    } else if (key === "telegram") {
        chips.push(`<span class="meta-chip">Mode: <strong>${meta.mock_mode ? 'Mock Sink' : 'Live Bot'}</strong></span>`);
        chips.push(`<span class="meta-chip">Token: <strong>${meta.has_token ? 'Configured' : 'Missing'}</strong></span>`);
        if (meta.total_alerts !== undefined) chips.push(`<span class="meta-chip">Sent: <strong>${meta.total_alerts}</strong></span>`);
    }
    return chips.length ? `<div class="pipeline-meta-chips">${chips.join("")}</div>` : "";
}

function renderActionBtn(key) {
    const actions = {
        scheduler: { label: "Adjust Hours & Schedule →", tab: "tab-scheduler" },
        companies: { label: "Manage Company Portals →", tab: "tab-companies" },
        adapter: { label: "Inspect Activity Logs →", tab: "tab-logs" },
        matcher: { label: "Tune Filter Keywords →", tab: "tab-filters" },
        database: { label: "Browse Indexed Jobs →", tab: "tab-jobs" },
        telegram: { label: "Configure Telegram Alerts →", tab: "tab-telegram" },
    };
    const act = actions[key];
    if (!act) return "";
    return `<button type="button" class="node-action-btn" onclick="switchTab('${act.tab}')">${act.label}</button>`;
}

function renderNodeCard(key, node, isScanning) {
    if (!node) return "";
    const state = isScanning ? "running" : (node.state || "idle").toLowerCase();
    const nodeClass = `pipeline-node node-${state}`;
    const errorHtml = node.error
        ? `<div class="node-error-msg">⚠️ <strong>Failure:</strong> ${escapeHtml(node.error)}</div>`
        : "";

    // Multi-error expandable drawer for company portals
    let failedDrawerHtml = "";
    if (key === "companies" && node.meta && node.meta.failed_companies && node.meta.failed_companies.length > 0) {
        const fcList = node.meta.failed_companies;
        const items = fcList.map(fc => `
            <div class="failing-portal-item">
                <span class="failing-portal-name">${escapeHtml(fc.name)}</span>
                <span class="failing-portal-ats">${escapeHtml(fc.ats || 'custom')}</span>
                <span class="failing-portal-err">${escapeHtml(fc.error)}</span>
            </div>
        `).join("");

        failedDrawerHtml = `
            <div>
                <button type="button" class="failing-portals-toggle" onclick="toggleFailingPortals(this)">
                    ⚠️ View all ${fcList.length} failing portals ▾
                </button>
                <div class="failing-portals-drawer hidden">
                    ${items}
                </div>
            </div>
        `;
    }

    const metaChipsHtml = renderMetaChips(key, node.meta);
    const actionBtnHtml = renderActionBtn(key);

    return `
        <div class="${nodeClass}">
            <div class="pipeline-node-header">
                <div class="pipeline-node-title-group">
                    <span class="pipeline-node-dot"></span>
                    <strong class="pipeline-node-title">${escapeHtml(node.label || key)}</strong>
                </div>
                <span class="pipeline-state-badge state-${state}">${escapeHtml(state.toUpperCase())}</span>
            </div>
            <div class="pipeline-node-detail">${escapeHtml(node.detail || "")}</div>
            ${errorHtml}
            ${failedDrawerHtml}
            ${metaChipsHtml}
            ${actionBtnHtml}
        </div>
    `;
}

function renderAdapterFanOut(breakdown, isScanning) {
    if (!breakdown) return "";
    const adapters = [
        { id: "greenhouse", name: "Greenhouse API" },
        { id: "lever", name: "Lever API" },
        { id: "ashby", name: "Ashby API" },
        { id: "workday", name: "Workday API" },
        { id: "fallback", name: "Fallback Scraper" },
    ];

    const cards = adapters.map(ad => {
        const item = breakdown[ad.id] || { state: "idle", portals: 0, jobs_found: 0, failures: [] };
        const state = isScanning ? "running" : (item.state || "idle");
        const dotColor = state === "success" ? "var(--success)" : state === "error" ? "var(--danger)" : state === "warning" ? "var(--warning)" : state === "running" ? "var(--primary)" : "var(--text-muted)";
        const pulseClass = state === "running" ? "pulse" : "";

        return `
            <div class="adapter-subcard sub-${state}">
                <div class="adapter-subcard-header">
                    <span>${escapeHtml(ad.name)}</span>
                    <span class="adapter-subcard-dot ${pulseClass}" style="background-color: ${dotColor};"></span>
                </div>
                <div class="adapter-subcard-stats">
                    <span>${item.portals || 0} Portals</span>
                    <strong>${item.jobs_found || 0} jobs</strong>
                </div>
            </div>
        `;
    });

    return `<div class="adapter-fanout-grid">${cards.join("")}</div>`;
}

function renderSummaryBar(lastCycle) {
    const summaryContainer = document.getElementById("pipeline-cycle-summary");
    if (!summaryContainer) return;

    if (!lastCycle) {
        summaryContainer.innerHTML = `
            <div class="pipeline-summary-group">
                <span class="summary-pill">⚡ <span>Scan Engine:</span> <strong>5 Parallel Workers</strong></span>
                <span class="summary-pill">🕒 <span>Status:</span> <strong>Standing by for first cycle</strong></span>
            </div>
            <span class="badge badge-info">IDLE</span>
        `;
        return;
    }

    const durationStr = `${Number(lastCycle.duration_seconds || 0).toFixed(1)}s`;
    const healthyBadge = (lastCycle.errors_count || 0) > 0
        ? `<span class="badge badge-warning">⚠️ ${lastCycle.errors_count} Warnings</span>`
        : `<span class="badge badge-success">✅ Cycle Healthy</span>`;

    summaryContainer.innerHTML = `
        <div class="pipeline-summary-group">
            <span class="summary-pill">⏱ <span>Runtime:</span> <strong>${durationStr}</strong></span>
            <span class="summary-pill">🏢 <span>Portals:</span> <strong>${lastCycle.companies_scanned}</strong></span>
            <span class="summary-pill">🔍 <span>Found:</span> <strong>${lastCycle.total_jobs_found}</strong></span>
            <span class="summary-pill">🎯 <span>Matched:</span> <strong>${lastCycle.total_jobs_matched}</strong></span>
            <span class="summary-pill">✈️ <span>Alerts:</span> <strong>${lastCycle.new_alerts_sent}</strong></span>
        </div>
        <div>
            ${healthyBadge}
        </div>
    `;
}

async function loadPipeline() {
    const flowContainer = document.getElementById("pipeline-flow");
    const scanBadge = document.getElementById("pipeline-scan-badge");
    const refreshText = document.getElementById("pipeline-refresh-text");
    const refreshDot = document.getElementById("pipeline-refresh-dot");

    // Sync layout toggle buttons with saved state
    const btnVert = document.getElementById("btn-layout-vertical");
    const btnHoriz = document.getElementById("btn-layout-horizontal");
    if (btnVert) btnVert.classList.toggle("active", currentPipelineLayout === "vertical");
    if (btnHoriz) btnHoriz.classList.toggle("active", currentPipelineLayout === "horizontal");

    try {
        const res = await fetch("/api/pipeline/state");
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();

        // 1. Update dynamic scan badge (#pipeline-scan-badge)
        if (scanBadge) {
            if (data.is_scanning) {
                scanBadge.className = "badge badge-primary pulse";
                scanBadge.textContent = "SCANNING";
            } else {
                scanBadge.className = "badge badge-info";
                scanBadge.textContent = "IDLE";
            }
        }

        // 2. Render Telemetry Summary Bar
        renderSummaryBar(data.last_cycle);

        // 3. Render DAG Flowchart with Parallel Branches
        if (flowContainer && data.nodes) {
            flowContainer.className = `pipeline-flow ${currentPipelineLayout}`;
            const arrow = currentPipelineLayout === "horizontal" ? "→" : "↓";
            const fragments = [];

            // Stage 1: Scheduler
            fragments.push(renderNodeCard("scheduler", data.nodes.scheduler, data.is_scanning));
            fragments.push(`<div class="pipeline-connector">${arrow}</div>`);

            // Stage 2: Company Portals
            fragments.push(renderNodeCard("companies", data.nodes.companies, data.is_scanning));

            // Fan-out connector to parallel ATS adapters
            fragments.push(`
                <div class="pipeline-branch-header">⚡ Parallel ATS Extraction (Fan-Out)</div>
                <div class="pipeline-connector">${arrow}</div>
            `);

            // Stage 3: ATS Adapters & Parallel Fan-out Grid
            const adapterCard = renderNodeCard("adapter", data.nodes.adapter, data.is_scanning);
            const adaptersBreakdown = (data.nodes.adapter && data.nodes.adapter.meta) ? data.nodes.adapter.meta.adapters_breakdown : null;
            const fanOutHtml = renderAdapterFanOut(adaptersBreakdown, data.is_scanning);
            fragments.push(`
                <div style="width: 100%; display: flex; flex-direction: column; gap: 0.65rem;">
                    ${adapterCard}
                    ${fanOutHtml}
                </div>
            `);

            // Fan-in connector to Job Matcher
            fragments.push(`
                <div class="pipeline-branch-header">⚡ Unified Matching (Fan-In)</div>
                <div class="pipeline-connector">${arrow}</div>
            `);

            // Stage 4: Job Matcher
            fragments.push(renderNodeCard("matcher", data.nodes.matcher, data.is_scanning));

            // Dual output fork connector
            fragments.push(`
                <div class="pipeline-branch-header">⚡ Parallel Dual Output (Persistence & Alerting)</div>
                <div class="pipeline-connector">${arrow}</div>
            `);

            // Stage 5: Parallel Dual Output Fork (SQLite Database & Telegram Alerts)
            const dbCard = renderNodeCard("database", data.nodes.database, data.is_scanning);
            const tgCard = renderNodeCard("telegram", data.nodes.telegram, data.is_scanning);
            fragments.push(`
                <div class="pipeline-dag-fork">
                    ${dbCard}
                    ${tgCard}
                </div>
            `);

            flowContainer.innerHTML = fragments.join("");
        }

        // 4. Dynamic polling: 3s if is_scanning: true, falling back to 15s when idle
        const nextInterval = data.is_scanning ? 3000 : 15000;
        if (refreshText) {
            refreshText.textContent = data.is_scanning ? "Live Scan Polling: 3s" : "Auto-refresh: 15s";
        }
        if (refreshDot) {
            refreshDot.className = data.is_scanning ? "status-dot green pulse" : "status-dot green";
        }

        if (pipelinePollTimer) clearTimeout(pipelinePollTimer);
        pipelinePollTimer = setTimeout(loadPipeline, nextInterval);
    } catch (err) {
        console.error("Error loading pipeline flowchart:", err);
        if (flowContainer && (!flowContainer.children.length || flowContainer.querySelector(".text-muted"))) {
            flowContainer.innerHTML = `<p class="text-danger text-center py-4">⚠️ Unable to load pipeline state. Retrying in 15s...</p>`;
        }
        if (pipelinePollTimer) clearTimeout(pipelinePollTimer);
        pipelinePollTimer = setTimeout(loadPipeline, 15000);
    }
}
