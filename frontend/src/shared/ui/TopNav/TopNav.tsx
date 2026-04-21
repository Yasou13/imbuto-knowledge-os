import { useNavigate, useLocation } from "react-router-dom";
import { useFileStore } from "../../../store/useFileStore";

/* ── Component ─────────────────────────────────────────────────────── */

export function TopNav() {
    const openFiles = useFileStore((state) => state.openFiles);
    const closeFile = useFileStore((state) => state.closeFile);
    const dirtyFiles = useFileStore((state) => state.dirtyFiles);
    const navigate = useNavigate();
    const location = useLocation();

    /* Active path derived from URL */
    const activePath = location.pathname.replace(/^\/editor\/?/, "") || "";

    /* ── Tab click ─────────────────────────────────────────────────── */

    const activateTab = (filePath: string) => {
        navigate(`/editor/${encodeURIComponent(filePath)}`);
    };

    /* ── Tab close ─────────────────────────────────────────────────── */

    const handleClose = (e: React.MouseEvent, filePath: string) => {
        e.stopPropagation();

        /* Guard: Prevent accidental data loss */
        if (dirtyFiles.has(filePath)) {
            const confirmed = window.confirm(
                "You have unsaved changes. Are you sure you want to close this tab?",
            );
            if (!confirmed) return;
        }

        closeFile(filePath);

        /* If we just closed the active tab, navigate to the next available */
        const isClosingActive =
            activePath === filePath ||
            activePath === encodeURIComponent(filePath);

        if (isClosingActive) {
            const remaining = openFiles.filter((f) => f.path !== filePath);
            if (remaining.length > 0) {
                navigate(`/editor/${encodeURIComponent(remaining[0].path)}`);
            } else {
                navigate("/editor");
            }
        }
    };

    /* ── Render ────────────────────────────────────────────────────── */

    return (
        <header
            className="flex h-12 shrink-0 items-center justify-between
                 border-b border-[#2a2d3a] bg-[#13151c]/80 px-4
                 backdrop-blur-sm"
        >
            {/* ── Left: traffic lights + file tabs ─────────────────── */}
            <div className="flex items-center gap-4 overflow-hidden">
                {/* macOS traffic lights (decorative) */}
                <div className="flex shrink-0 items-center gap-1.5">
                    <span className="inline-block h-3 w-3 rounded-full bg-[#ef4444]" />
                    <span className="inline-block h-3 w-3 rounded-full bg-[#f59e0b]" />
                    <span className="inline-block h-3 w-3 rounded-full bg-[#22c55e]" />
                </div>

                {/* File tabs — horizontally scrollable */}
                <nav className="flex items-center gap-0.5 overflow-x-auto">
                    {openFiles.length === 0 && (
                        <span className="px-3 py-1.5 text-xs text-[#565a6e]">
                            No files open
                        </span>
                    )}

                    {openFiles.map((file) => {
                        const isActive =
                            activePath === file.path ||
                            activePath === encodeURIComponent(file.path);
                        const isDirty = dirtyFiles.has(file.path);

                        return (
                            <button
                                key={file.path}
                                onClick={() => activateTab(file.path)}
                                className={`group flex shrink-0 items-center gap-1.5 rounded-md
                                 px-3 py-1.5 text-xs font-medium transition
                  ${isActive
                                        ? "bg-[rgba(99,102,241,0.12)] text-[#c0c1ff]"
                                        : "text-[#565a6e] hover:bg-[#1e2030] hover:text-[#8b8fa3]"
                                    }`}
                            >
                                <span className="material-symbols-outlined text-[14px]">
                                    {file.name.endsWith(".md")
                                        ? "description"
                                        : file.name.endsWith(".json")
                                            ? "data_object"
                                            : "draft"}
                                </span>

                                <span className="max-w-[120px] truncate">{file.name}</span>

                                {/* Dirty indicator */}
                                {isDirty && (
                                    <span className="inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-[#f59e0b]" />
                                )}

                                {/* Close button */}
                                <span
                                    onClick={(e) => handleClose(e, file.path)}
                                    className="material-symbols-outlined ml-0.5 hidden text-[14px]
                                     text-[#565a6e] transition hover:text-[#ef4444]
                                     group-hover:inline-block"
                                >
                                    close
                                </span>
                            </button>
                        );
                    })}
                </nav>
            </div>

            {/* ── Right: global actions ─────────────────────────────── */}
            <div className="flex shrink-0 items-center gap-1.5">
                <button
                    onClick={() => {
                        // @ts-ignore
                        window.electron?.showNotification("IMBUTO", "No new notifications");
                    }}
                    className="rounded-md p-1.5 text-[#565a6e] transition
                     hover:bg-[#1e2030] hover:text-[#8b8fa3]"
                    aria-label="Notifications"
                >
                    <span className="material-symbols-outlined text-[20px]">
                        notifications
                    </span>
                </button>
                <button
                    onClick={() => {
                        // @ts-ignore
                        window.electron?.openSettings();
                    }}
                    className="rounded-md p-1.5 text-[#565a6e] transition
                     hover:bg-[#1e2030] hover:text-[#8b8fa3]"
                    aria-label="Settings"
                >
                    <span className="material-symbols-outlined text-[20px]">
                        settings
                    </span>
                </button>
                <div
                    className="flex h-7 w-7 items-center justify-center rounded-full
                     bg-[#6366f1] text-xs font-semibold text-white"
                >
                    U
                </div>
            </div>
        </header>
    );
}
