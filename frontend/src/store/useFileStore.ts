import { create } from "zustand";
import type { FileDetail } from "../shared/api/imbutoClient";

/* ── Exponential backoff polling state (module-scoped, not serialized) ── */

const SYNC_POLL_MIN_DELAY = 500;
const SYNC_POLL_MAX_DELAY = 10_000;
const SYNC_POLL_FACTOR = 1.5;
const MAX_RETRIES = 20;

let _pollTimer: ReturnType<typeof setTimeout> | null = null;
let _currentDelay = SYNC_POLL_MIN_DELAY;
let _retries = 0;

interface FileState {
    /** Currently focused file (the one loaded in the editor). */
    fileDetail: FileDetail | null;
    setFileDetail: (detail: FileDetail | null) => void;

    /** Current position of the caret inside the edited file. */
    cursorPosition: number;
    setCursorPosition: (pos: number) => void;

    /** All files currently open as tabs. */
    openFiles: FileDetail[];
    openFile: (detail: FileDetail) => void;
    closeFile: (path: string) => void;

    /** Paths of files with unsaved changes. */
    dirtyFiles: Set<string>;
    setDirty: (path: string, dirty: boolean) => void;

    /** Global counter to trigger file tree re-fetches cleanly. */
    fileRefreshKey: number;
    triggerFileRefresh: () => void;

    /** Indicates if background vector syncing is active. */
    isSyncing: boolean;

    /**
     * Kick off exponential-backoff polling of `/api/sync-status`.
     * Idempotent: if already polling, resets delay for rapid re-poll.
     */
    startSyncPolling: () => void;

    /** Force-stop polling and clear isSyncing. For cleanup on unmount. */
    stopSyncPolling: () => void;
}

export const useFileStore = create<FileState>((set) => {
    /* ── Internal polling loop ───────────────────────────────────────── */

    const _clearPoll = () => {
        if (_pollTimer !== null) {
            clearTimeout(_pollTimer);
            _pollTimer = null;
        }
    };

    const _poll = async () => {
        if (_retries >= MAX_RETRIES) {
            _clearPoll();
            console.error("[imbuto] Sync polling aborted — backend unreachable after %d retries", MAX_RETRIES);
            set({ isSyncing: false });
            return;
        }
        _retries++;
        try {
            const baseURL = (window as any).imbuto?.apiUrl || "http://localhost:8000";
            const token = (window as any).imbuto?.internalToken || "";
            const res = await fetch(`${baseURL}/api/sync-status`, {
                headers: { "X-Internal-Token": token }
            });
            if (res.ok) {
                const data = await res.json();
                if (data.is_syncing === true) {
                    // Still syncing — back off and schedule next tick
                    _currentDelay = Math.min(_currentDelay * SYNC_POLL_FACTOR, SYNC_POLL_MAX_DELAY);
                    _pollTimer = setTimeout(_poll, _currentDelay);
                } else {
                    // Sync complete — stop immediately
                    _clearPoll();
                    set({ isSyncing: false });
                }
            } else {
                // Non-ok response — back off and retry
                _currentDelay = Math.min(_currentDelay * SYNC_POLL_FACTOR, SYNC_POLL_MAX_DELAY);
                _pollTimer = setTimeout(_poll, _currentDelay);
            }
        } catch {
            // Network error — back off and retry
            _currentDelay = Math.min(_currentDelay * SYNC_POLL_FACTOR, SYNC_POLL_MAX_DELAY);
            _pollTimer = setTimeout(_poll, _currentDelay);
        }
    };

    return {
        fileDetail: null,
        setFileDetail: (detail) => set({ fileDetail: detail }),

        cursorPosition: 0,
        setCursorPosition: (pos) => set({ cursorPosition: pos }),

        openFiles: [],
        openFile: (detail) => set((state) => {
            if (state.openFiles.some((f) => f.path === detail.path)) return state;
            return { openFiles: [...state.openFiles, detail] };
        }),
        closeFile: (path) => set((state) => {
            const nextDirty = new Set(state.dirtyFiles);
            nextDirty.delete(path);
            return {
                openFiles: state.openFiles.filter((f) => f.path !== path),
                dirtyFiles: nextDirty
            };
        }),

        dirtyFiles: new Set(),
        setDirty: (path, dirty) => set((state) => {
            const nextDirty = new Set(state.dirtyFiles);
            if (dirty) nextDirty.add(path);
            else nextDirty.delete(path);
            return { dirtyFiles: nextDirty };
        }),

        fileRefreshKey: 0,
        triggerFileRefresh: () => set((state) => ({ fileRefreshKey: state.fileRefreshKey + 1 })),

        isSyncing: false,

        startSyncPolling: () => {
            // Reset delay for rapid initial poll (handles back-to-back saves)
            _currentDelay = SYNC_POLL_MIN_DELAY;
            _retries = 0;
            _clearPoll();
            set({ isSyncing: true });
            _pollTimer = setTimeout(_poll, _currentDelay);
        },

        stopSyncPolling: () => {
            _clearPoll();
            set({ isSyncing: false });
        },
    };
});
