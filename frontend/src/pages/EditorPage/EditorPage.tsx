import { useState, useEffect, useCallback } from "react";
import { useLocation } from "react-router-dom";
import { getFile, syncDocument, listFiles } from "../../shared/api/imbutoClient";
import { useFileStore } from "../../store/useFileStore";
import type { FileDetail, FileMetadata } from "../../shared/api/imbutoClient";

import CodeMirror from "@uiw/react-codemirror";
import type { ReactCodeMirrorRef } from "@uiw/react-codemirror";
import { vscodeDark } from "@uiw/codemirror-theme-vscode";
import { markdown, markdownLanguage } from "@codemirror/lang-markdown";
import { languages } from "@codemirror/language-data";
import { autocompletion, CompletionContext } from "@codemirror/autocomplete";
import React, { useRef } from "react";

/* ── Types ─────────────────────────────────────────────────────────── */

type SyncStatus = "idle" | "syncing" | "indexed" | "error";
type PageState = "loading" | "ready" | "error" | "empty";

/* ── Memoized Toolbar ─────────────────────────────────────────────── */

const EditorToolbar = React.memo(({
    editorRef,
    handleSave,
    syncStatus,
    syncedChunks,
    isDirty,
    lastModified
}: {
    editorRef: any,
    handleSave: () => void,
    syncStatus: SyncStatus,
    syncedChunks: number,
    isDirty: boolean,
    lastModified: string
}) => {
    return (
        <div className="flex items-center gap-1 rounded-lg border border-[#2a2d3a] bg-[#13151c] px-3 py-1.5 mt-4">
            <button
                onClick={() => {
                    const view = editorRef.current?.view;
                    if (!view) return;
                    const selection = view.state.selection.main;
                    const text = view.state.sliceDoc(selection.from, selection.to);
                    view.dispatch({
                        changes: { from: selection.from, to: selection.to, insert: `**${text}**` },
                        selection: { anchor: selection.from + 2, head: selection.to + 2 }
                    });
                    view.focus();
                }}
                className="rounded p-1.5 text-[#565a6e] transition hover:bg-[#1e2030] hover:text-[#8b8fa3]"
                title="Bold"
            >
                <span className="material-symbols-outlined text-[18px]">format_bold</span>
            </button>
            <button
                onClick={() => {
                    const view = editorRef.current?.view;
                    if (!view) return;
                    const selection = view.state.selection.main;
                    const text = view.state.sliceDoc(selection.from, selection.to);
                    view.dispatch({
                        changes: { from: selection.from, to: selection.to, insert: `_${text}_` },
                        selection: { anchor: selection.from + 1, head: selection.to + 1 }
                    });
                    view.focus();
                }}
                className="rounded p-1.5 text-[#565a6e] transition hover:bg-[#1e2030] hover:text-[#8b8fa3]"
                title="Italic"
            >
                <span className="material-symbols-outlined text-[18px]">format_italic</span>
            </button>
            <button
                onClick={() => {
                    const view = editorRef.current?.view;
                    if (!view) return;
                    const selection = view.state.selection.main;
                    const text = view.state.sliceDoc(selection.from, selection.to);
                    view.dispatch({
                        changes: { from: selection.from, to: selection.to, insert: `\`${text}\`` },
                        selection: { anchor: selection.from + 1, head: selection.to + 1 }
                    });
                    view.focus();
                }}
                className="rounded p-1.5 text-[#565a6e] transition hover:bg-[#1e2030] hover:text-[#8b8fa3]"
                title="Code"
            >
                <span className="material-symbols-outlined text-[18px]">code</span>
            </button>

            <div className="mx-2 h-5 w-px bg-[#2a2d3a]" />

            <button
                onClick={handleSave}
                disabled={syncStatus === "syncing"}
                className={`flex items-center gap-1.5 rounded-md px-3 py-1 text-xs font-medium transition
                    ${syncStatus === "syncing"
                        ? "bg-[#f59e0b] text-black cursor-wait"
                        : syncStatus === "indexed"
                            ? "bg-[#22c55e] text-white"
                            : syncStatus === "error"
                                ? "bg-[#ef4444] text-white"
                                : "bg-[#6366f1] text-white hover:bg-[#5558e6]"
                    }`}
            >
                {syncStatus === "syncing" ? (
                    <>
                        <span className="material-symbols-outlined animate-spin text-[14px]">progress_activity</span>
                        Syncing…
                    </>
                ) : syncStatus === "indexed" ? (
                    <>
                        <span className="material-symbols-outlined text-[14px]">check_circle</span>
                        Indexed ({syncedChunks} chunks)
                    </>
                ) : syncStatus === "error" ? (
                    <>
                        <span className="material-symbols-outlined text-[14px]">error</span>
                        Sync Failed
                    </>
                ) : (
                    <>
                        <span className="material-symbols-outlined text-[14px]">save</span>
                        Save {isDirty && "*"}
                    </>
                )}
            </button>

            <span className="ml-auto text-[10px] text-[#565a6e]">Ctrl+S</span>
            <span className="ml-3 text-[10px] text-[#565a6e]">Last edited: {new Date(lastModified).toLocaleString()}</span>
        </div>
    );
});

/* ── Memoized Meta Bar ───────────────────────────────────────────── */

const EditorMetaBar = React.memo(({ fileDetail }: { fileDetail: FileDetail }) => {
    return (
        <div className="flex items-center gap-4 text-xs text-[#8b8fa3]">
            <span className="flex items-center gap-1">
                <span className="material-symbols-outlined text-[14px]">calendar_today</span>
                {new Date(fileDetail.last_modified).toLocaleString()}
            </span>
            <span className="flex items-center gap-1">
                <span className="material-symbols-outlined text-[14px]">data_usage</span>
                {fileDetail.chunk_count} chunks &middot; {fileDetail.token_count.toLocaleString()} tokens
            </span>
            <span className="flex items-center gap-1">
                <span className="material-symbols-outlined text-[14px]">folder</span>
                {(fileDetail.size / 1024).toFixed(1)} KB
            </span>
            {fileDetail.wikilinks.length > 0 && (
                <span className="flex items-center gap-1">
                    <span className="material-symbols-outlined text-[14px]">hub</span>
                    {fileDetail.wikilinks.length} links
                </span>
            )}
        </div>
    );
});

/* ── Component ─────────────────────────────────────────────────────── */

export function EditorPage() {
    const location = useLocation();
    const setActiveFile = useFileStore((state) => state.setFileDetail);
    const addOpenFile = useFileStore((state) => state.openFile);
    const setDirtyState = useFileStore((state) => state.setDirty);
    const startSyncPolling = useFileStore((state) => state.startSyncPolling);

    /* Extract file path from URL: /editor/path/to/file.md → path/to/file.md */
    const rawFilePath = location.pathname.replace(/^\/editor\/?/, "") || "";
    let decodedFilePath = rawFilePath;
    if (rawFilePath) {
        try {
            decodedFilePath = decodeURIComponent(rawFilePath);
        } catch (error) {
            console.error("URI Decode failed for path:", rawFilePath, error);
            // Fallback to raw path if decoding fails
        }
    }
    const filePath = decodedFilePath;

    /* ── File state ─────────────────────────────────────────────────── */
    const [pageState, setPageState] = useState<PageState>(filePath ? "loading" : "empty");
    const [fileDetail, setFileDetail] = useState<FileDetail | null>(null);
    const [content, setContent] = useState("");
    const [isDirty, setIsDirty] = useState(false);

    /* ── Sync state ────────────────────────────────────────────────── */
    const [syncStatus, setSyncStatus] = useState<SyncStatus>("idle");
    const [syncedChunks, setSyncedChunks] = useState(0);
    const [syncError, setSyncError] = useState<string | null>(null);

    /* ── File browser state ────────────────────────────────────────── */
    const [files, setFiles] = useState<FileMetadata[]>([]);
    const [filesLoading, setFilesLoading] = useState(false);

    /* ── CodeMirror Editor Refs ────────────────────────────────────── */
    const editorRef = useRef<ReactCodeMirrorRef>(null);
    const debounceTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const mountedRef = useRef(true);

    /* ── Unmount cleanup: clear debounce timer, mark unmounted ───── */
    useEffect(() => {
        mountedRef.current = true;
        return () => {
            mountedRef.current = false;
            if (debounceTimeoutRef.current) {
                clearTimeout(debounceTimeoutRef.current);
                debounceTimeoutRef.current = null;
            }
        };
    }, []);

    /* ── CodeMirror Autocomplete ───────────────────────────────────── */
    const wikilinkCompletion = useCallback((context: CompletionContext) => {
        const word = context.matchBefore(/\[\[[^\]]*/);
        if (!word) return null;
        if (word.from === word.to && !context.explicit) return null;

        return {
            from: word.from + 2, // Start after [[
            options: files.map((f) => ({
                label: f.name.replace(/\.md$/, ""),
                type: "text",
                apply: `${f.name.replace(/\.md$/, "")}]]`
            }))
        };
    }, [files]);

    /* ── Load file from backend ────────────────────────────────────── */

    useEffect(() => {
        if (!filePath) {
            setPageState("empty");
            setFileDetail(null);
            setContent("");
            return;
        }

        let cancelled = false;
        setPageState("loading");

        getFile(filePath)
            .then((detail) => {
                if (cancelled) return;
                setFileDetail(detail);

                // Uncontrolled CodeMirror View Dispatch logic (Sync Guard)
                const view = editorRef.current?.view;
                if (view) {
                    const currentDoc = view.state.doc.toString();
                    if (currentDoc !== detail.content) {
                        view.dispatch({
                            changes: { from: 0, to: currentDoc.length, insert: detail.content }
                        });
                    }
                } else {
                    // Fallback to updating content if view isn't mounted yet
                    setContent(detail.content);
                }

                setIsDirty(false);
                setPageState("ready");
                setActiveFile(detail);
                addOpenFile(detail);
                setDirtyState(detail.path, false);
            })
            .catch((err) => {
                if (cancelled) return;
                console.error("Failed to load file:", err);
                setPageState("error");
            });

        return () => {
            cancelled = true;
            setActiveFile(null);
            if (debounceTimeoutRef.current) clearTimeout(debounceTimeoutRef.current);
        };
    }, [filePath]);

    /* ── Load file list for autocomplete and empty state ──────────── */

    useEffect(() => {
        setFilesLoading(true);
        listFiles()
            .then((res) => setFiles(res.files))
            .catch(() => setFiles([]))
            .finally(() => setFilesLoading(false));
    }, []);

    /* ── Content change handler ─────────────────────────────────────── */

    const handleContentChange = useCallback(
        (value: string) => {
            // Local state is uncontrolled by React so the cursor stays perfect
            // We just stash it into a local ref for saving
            setContent(value);

            // Only sync global dirty state after typing pauses (Debounce)
            if (debounceTimeoutRef.current) {
                clearTimeout(debounceTimeoutRef.current);
            }

            debounceTimeoutRef.current = setTimeout(() => {
                if (!mountedRef.current) return;
                setIsDirty(true);
                if (fileDetail) {
                    setDirtyState(fileDetail.path, true);
                }
            }, 400);
        },
        [fileDetail, setDirtyState],
    );

    /* ── Save handler ──────────────────────────────────────────────── */

    const handleSave = useCallback(async () => {
        if (syncStatus === "syncing" || !fileDetail) return;

        setSyncStatus("syncing");
        setSyncError(null);
        startSyncPolling();

        try {
            const res = await syncDocument(fileDetail.path, content);
            setSyncedChunks(res.synced_chunks);
            setSyncStatus("indexed");
            setIsDirty(false);
            if (fileDetail) setDirtyState(fileDetail.path, false);

            // Refresh metadata after save
            try {
                const updated = await getFile(fileDetail.path);
                setFileDetail(updated);
            } catch { /* non-critical */ }

            setTimeout(() => {
                if (mountedRef.current) setSyncStatus("idle");
            }, 3000);
        } catch (err) {
            setSyncError(err instanceof Error ? err.message : "Sync failed");
            setSyncStatus("error");
            setTimeout(() => {
                if (mountedRef.current) setSyncStatus("idle");
            }, 5000);
        }
    }, [syncStatus, fileDetail, content]);

    /* ── Keyboard shortcut (Ctrl+S) ────────────────────────────────── */

    useEffect(() => {
        const handler = (e: KeyboardEvent) => {
            if ((e.ctrlKey || e.metaKey) && e.key === "s") {
                e.preventDefault();
                handleSave();
            }
        };
        window.addEventListener("keydown", handler);
        return () => window.removeEventListener("keydown", handler);
    }, [handleSave]);

    /* ── RENDER: Loading ───────────────────────────────────────────── */

    if (pageState === "loading") {
        return (
            <div className="flex h-full items-center justify-center">
                <div className="flex flex-col items-center gap-3">
                    <span className="material-symbols-outlined animate-spin text-[32px] text-[#6366f1]">
                        progress_activity
                    </span>
                    <p className="text-sm text-[#565a6e]">Loading {filePath}…</p>
                </div>
            </div>
        );
    }

    /* ── RENDER: Error ─────────────────────────────────────────────── */

    if (pageState === "error") {
        return (
            <div className="flex h-full items-center justify-center">
                <div className="flex flex-col items-center gap-3 rounded-xl border border-[#ef4444]/30
                     bg-[rgba(239,68,68,0.06)] px-8 py-6 text-center">
                    <span className="material-symbols-outlined text-[32px] text-[#ef4444]">
                        error
                    </span>
                    <h2 className="text-lg font-semibold text-[#e2e4ea]">File Not Found</h2>
                    <p className="max-w-sm text-sm text-[#8b8fa3]">
                        Could not load <code className="text-[#c0c1ff]">{filePath}</code>.
                        Verify the file exists in the vault.
                    </p>
                    <a
                        href="#/editor"
                        className="mt-2 rounded-md bg-[#6366f1] px-4 py-1.5 text-sm font-medium
                         text-white transition hover:bg-[#5558e6]"
                    >
                        Back to File Browser
                    </a>
                </div>
            </div>
        );
    }

    /* ── RENDER: Empty (file browser) ──────────────────────────────── */

    if (pageState === "empty" || !fileDetail) {
        return (
            <div className="space-y-6">
                <div className="space-y-1">
                    <h1 className="text-xl font-semibold text-[#e2e4ea]">Knowledge Vault</h1>
                    <p className="text-xs text-[#565a6e]">
                        Select a file to open in the editor, or create a new entry.
                    </p>
                </div>

                {filesLoading ? (
                    <div className="flex items-center gap-2 py-8 text-sm text-[#565a6e]">
                        <span className="material-symbols-outlined animate-spin text-[18px]">
                            progress_activity
                        </span>
                        Scanning vault…
                    </div>
                ) : files.length === 0 ? (
                    <div className="flex flex-col items-center gap-3 rounded-xl border border-[#2a2d3a]
                         bg-[#13151c] px-8 py-12 text-center">
                        <span className="material-symbols-outlined text-[40px] text-[#565a6e]">
                            note_add
                        </span>
                        <p className="text-sm text-[#8b8fa3]">No markdown files found in the vault.</p>
                    </div>
                ) : (
                    <div className="space-y-1">
                        {files.map((f) => (
                            <a
                                key={f.path}
                                href={`#/editor/${f.path}`}
                                className="flex items-center gap-3 rounded-lg border border-[#2a2d3a]
                                 bg-[#13151c] px-4 py-3 transition hover:border-[#6366f1]/40
                                 hover:bg-[rgba(99,102,241,0.06)]"
                            >
                                <span className="material-symbols-outlined text-[20px] text-[#6366f1]">
                                    description
                                </span>
                                <div className="min-w-0 flex-1">
                                    <p className="truncate text-sm font-medium text-[#e2e4ea]">
                                        {f.name}
                                    </p>
                                    <p className="truncate text-[10px] text-[#565a6e]">{f.path}</p>
                                </div>
                                <div className="shrink-0 text-right text-[10px] text-[#565a6e]">
                                    <p>{(f.size / 1024).toFixed(1)} KB</p>
                                    <p>{new Date(f.last_modified).toLocaleDateString()}</p>
                                </div>
                            </a>
                        ))}
                    </div>
                )}
            </div>
        );
    }

    /* ── RENDER: Editor ─────────────────────────────────────────────── */

    return (
        <div className="space-y-6">
            {/* ── Document header ────────────────────────────────────── */}
            <div className="space-y-2">
                <div className="flex items-center gap-3">
                    <span className="material-symbols-outlined text-[28px] text-[#6366f1]">
                        description
                    </span>
                    <div className="min-w-0">
                        <h1 className="truncate text-xl font-semibold text-[#e2e4ea]">
                            {fileDetail.name}
                            {isDirty && (
                                <span className="ml-2 inline-block h-2 w-2 rounded-full bg-[#f59e0b]" />
                            )}
                        </h1>
                        <p className="truncate text-xs text-[#565a6e]">{fileDetail.path}</p>
                    </div>
                </div>

                {/* Meta bar — dynamically populated */}
                <EditorMetaBar fileDetail={fileDetail} />
            </div>

            {/* ── Editor toolbar ─────────────────────────────────────── */}
            <EditorToolbar
                editorRef={editorRef}
                handleSave={handleSave}
                syncStatus={syncStatus}
                syncedChunks={syncedChunks}
                isDirty={isDirty}
                lastModified={fileDetail.last_modified}
            />

            {/* ── Sync error detail ──────────────────────────────────── */}
            {syncError && (
                <div
                    className="flex items-center gap-2 rounded-lg border border-[#ef4444]/30
                     bg-[rgba(239,68,68,0.06)] px-4 py-2.5 text-xs text-[#ef4444]"
                >
                    <span className="material-symbols-outlined text-[16px]">error</span>
                    {syncError}
                </div>
            )}

            {/* ── Editor content area ─────────────────────────────────── */}
            <div className="rounded-xl border border-[#2a2d3a] bg-[#13151c] overflow-hidden">
                <CodeMirror
                    ref={editorRef}
                    value={content}
                    onChange={handleContentChange}
                    onUpdate={(viewUpdate) => {
                        if (viewUpdate.selectionSet) {
                            useFileStore.getState().setCursorPosition(viewUpdate.state.selection.main.head);
                        }
                    }}
                    height="520px"
                    theme={vscodeDark}
                    extensions={[
                        markdown({ base: markdownLanguage, codeLanguages: languages }),
                        autocompletion({ override: [wikilinkCompletion] })
                    ]}
                    className="text-sm font-mono leading-relaxed"
                />
            </div>
        </div>
    );
}
