import { useState, useEffect, useCallback } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { FileTree } from "./FileTree";
import { checkHealth, getSystemStatus, syncDocument } from "../../api/imbutoClient";
import type { HealthResponse, SystemStatusResponse } from "../../api/imbutoClient";
import { useFileStore } from "../../../store/useFileStore";
import { useModelStore, MODELS } from "../../../store/useModelStore";

/* ── Types ─────────────────────────────────────────────────────────── */

interface NavItem {
    icon: string;        // Google Material Symbol name
    label: string;
    path: string;
}

/* ── Static data ───────────────────────────────────────────────────── */

const NAV_ITEMS: NavItem[] = [
    { icon: "edit_note", label: "Editor", path: "/editor" },
    { icon: "search", label: "Query", path: "/query" },
    { icon: "hub", label: "Graph", path: "/graph" },
    { icon: "download", label: "Ingest", path: "/ingest" },
];

/* ── Component ─────────────────────────────────────────────────────── */

export function Sidebar() {
    const [vaultOpen, setVaultOpen] = useState(true);
    const activeModel = useModelStore((state) => state.selectedModel);
    const setActiveModel = useModelStore((state) => state.setSelectedModel);
    const [isCreating, setIsCreating] = useState(false);

    /* Health + Status polling state */
    const [health, setHealth] = useState<HealthResponse | null>(null);
    const [status, setStatus] = useState<SystemStatusResponse | null>(null);

    const location = useLocation();
    const navigate = useNavigate();
    const triggerFileRefresh = useFileStore((state) => state.triggerFileRefresh);
    const startSyncPolling = useFileStore((state) => state.startSyncPolling);

    /* ── Polling logic ────────────────────────────────────────────────── */

    const fetchStatus = useCallback(() => {
        checkHealth()
            .then(setHealth)
            .catch(() => setHealth(null));

        getSystemStatus()
            .then(setStatus)
            .catch(() => setStatus(null));
    }, []);

    useEffect(() => {
        fetchStatus();
        const intervalId = setInterval(fetchStatus, 30000); // 30s
        return () => clearInterval(intervalId);
    }, [fetchStatus]);

    /* ── New Entry logic ──────────────────────────────────────────────── */

    const handleNewEntry = async () => {
        if (isCreating) return;
        setIsCreating(true);
        try {
            const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
            const filename = `Untitled_${timestamp}.md`;

            startSyncPolling();
            await syncDocument(filename, ""); // Save empty file
            triggerFileRefresh();
            navigate(`/editor/${encodeURIComponent(filename)}`);
        } catch (err) {
            console.error("Failed to create new entry:", err);
        } finally {
            setIsCreating(false);
        }
    };

    return (
        <aside
            className="fixed top-0 left-0 z-40 flex h-screen w-[240px] flex-col
                 border-r border-[#2a2d3a] bg-[#13151c]"
        >
            {/* ── Header ──────────────────────────────────────────────── */}
            <div className="flex items-center gap-2 border-b border-[#2a2d3a] px-4 py-3">
                <span className="material-symbols-outlined text-[#6366f1]">
                    hub
                </span>
                <div className="min-w-0">
                    <p className="truncate text-sm font-semibold text-[#e2e4ea]">
                        IMBUTO
                    </p>
                    <p className="truncate text-[10px] uppercase tracking-widest text-[#565a6e]">
                        Synthetic Architect
                    </p>
                </div>
            </div>

            {/* ── New Entry ───────────────────────────────────────────── */}
            <div className="px-3 pt-3">
                <button
                    onClick={handleNewEntry}
                    disabled={isCreating}
                    className="flex w-full items-center justify-center gap-2 rounded-lg
                     bg-[#6366f1] px-3 py-2 text-sm font-medium text-white
                     transition hover:bg-[#5558e6] active:scale-[0.98]
                     disabled:opacity-50 disabled:cursor-not-allowed"
                >
                    <span className="material-symbols-outlined text-[18px]">
                        {isCreating ? "hourglass_top" : "add"}
                    </span>
                    {isCreating ? "Creating..." : "New Entry"}
                </button>
            </div>

            {/* ── Navigation ──────────────────────────────────────────── */}
            <nav className="mt-4 space-y-0.5 px-3">
                <p className="mb-2 px-2 text-[10px] font-semibold uppercase tracking-widest text-[#565a6e]">
                    Navigation
                </p>
                {NAV_ITEMS.map((item) => {
                    const isActive = location.pathname === item.path;
                    return (
                        <NavLink
                            key={item.path}
                            to={item.path}
                            className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm
                transition-colors
                ${isActive
                                    ? "border-l-2 border-[#6366f1] bg-[rgba(99,102,241,0.12)] text-[#c0c1ff]"
                                    : "border-l-2 border-transparent text-[#8b8fa3] hover:bg-[#1e2030] hover:text-[#e2e4ea]"
                                }`}
                        >
                            <span className="material-symbols-outlined text-[20px]">
                                {item.icon}
                            </span>
                            {item.label}
                        </NavLink>
                    );
                })}
            </nav>

            {/* ── File Tree (scrollable) ───────────────────────────────── */}
            <div className="mt-3 flex-1 overflow-y-auto border-t border-[#2a2d3a] px-3 pt-3">
                <FileTree />
            </div>

            {/* ── Vault Status (collapsible) ──────────────────────────── */}
            <div className="border-t border-[#2a2d3a] px-3 py-3">
                <button
                    onClick={() => setVaultOpen(!vaultOpen)}
                    className="flex w-full items-center justify-between rounded px-2 py-1.5
                     text-[10px] font-semibold uppercase tracking-widest
                     text-[#565a6e] transition hover:text-[#8b8fa3]"
                >
                    Vault Status
                    <span className="material-symbols-outlined text-[16px]">
                        {vaultOpen ? "expand_less" : "expand_more"}
                    </span>
                </button>

                {vaultOpen && (
                    <div className="mt-1 space-y-1.5 px-2">
                        <div className="flex items-center justify-between text-xs">
                            <span className="text-[#8b8fa3]">ChromaDB</span>
                            {health?.vector_db && !health.vector_db.includes("disconnected") ? (
                                <span className="flex items-center gap-1 text-[#22c55e]">
                                    <span className="inline-block h-1.5 w-1.5 rounded-full bg-[#22c55e]" />
                                    Connected
                                </span>
                            ) : (
                                <span className="flex items-center gap-1 text-[#ef4444]">
                                    <span className="inline-block h-1.5 w-1.5 rounded-full bg-[#ef4444]" />
                                    Offline
                                </span>
                            )}
                        </div>
                        <div className="flex items-center justify-between text-xs">
                            <span className="text-[#8b8fa3]">Documents</span>
                            <span className="text-[#e2e4ea]">
                                {status ? status.document_count : "—"}
                            </span>
                        </div>
                        <div className="flex items-center justify-between text-xs">
                            <span className="text-[#8b8fa3]">Last Sync</span>
                            <span className="text-[#e2e4ea] truncate max-w-[100px] text-right"
                                title={status?.last_sync_time || ""}>
                                {status?.last_sync_time
                                    ? new Date(status.last_sync_time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
                                    : "—"}
                            </span>
                        </div>
                    </div>
                )}
            </div>

            {/* ── Active Model ────────────────────────────────────────── */}
            <div className="border-t border-[#2a2d3a] px-3 py-3">
                <p className="mb-1.5 px-2 text-[10px] font-semibold uppercase tracking-widest text-[#565a6e]">
                    Active Model
                </p>
                <select
                    value={activeModel}
                    onChange={(e) => setActiveModel(e.target.value)}
                    className="w-full rounded-md border border-[#2a2d3a] bg-[#1e2030] px-2 py-1.5
                     text-xs text-[#e2e4ea] outline-none
                     focus:border-[#6366f1] focus:ring-1 focus:ring-[#6366f1]/30"
                >
                    {MODELS.map((m) => (
                        <option key={m} value={m}>
                            {m}
                        </option>
                    ))}
                </select>
            </div>
        </aside>
    );
}
