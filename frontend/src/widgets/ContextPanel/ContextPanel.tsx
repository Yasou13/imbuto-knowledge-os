import { useState, useRef, useEffect, useCallback } from "react";
import { useFileStore } from "../../store/useFileStore";
import { queryMemory } from "../../shared/api/imbutoClient";
import type { ContextSource } from "../../shared/api/imbutoClient";
import { useModelStore } from "../../store/useModelStore";

/* ── Types ─────────────────────────────────────────────────────────── */

type PanelTab = "inspector" | "ai_chat" | "sources";

interface ChatMessage {
    role: "system" | "user" | "assistant";
    content: string;
    sources?: ContextSource[];
}

/* ── Tab config ────────────────────────────────────────────────────── */

const TABS: { key: PanelTab; icon: string; label: string }[] = [
    { key: "inspector", icon: "info", label: "Inspector" },
    { key: "ai_chat", icon: "smart_toy", label: "AI Chat" },
    { key: "sources", icon: "source", label: "Sources" },
];

/* ── Component ─────────────────────────────────────────────────────── */

export function ContextPanel() {
    const [activeTab, setActiveTab] = useState<PanelTab>("inspector");

    return (
        <aside
            className="fixed right-0 top-0 z-40 flex h-screen w-[320px] flex-col
                 border-l border-[#2a2d3a] bg-[#13151c]"
        >
            {/* ── Tab bar ──────────────────────────────────────────── */}
            <div className="flex h-12 shrink-0 items-center border-b border-[#2a2d3a]">
                {TABS.map((tab) => (
                    <button
                        key={tab.key}
                        onClick={() => setActiveTab(tab.key)}
                        className={`flex flex-1 items-center justify-center gap-1.5
                        py-3 text-xs font-medium transition
              ${activeTab === tab.key
                                ? "border-b-2 border-[#6366f1] text-[#c0c1ff]"
                                : "border-b-2 border-transparent text-[#565a6e] hover:text-[#8b8fa3]"
                            }`}
                    >
                        <span className="material-symbols-outlined text-[16px]">
                            {tab.icon}
                        </span>
                        {tab.label}
                    </button>
                ))}
            </div>

            {/* ── Tab content ──────────────────────────────────────── */}
            <div className="flex-1 overflow-y-auto">
                {activeTab === "inspector" && <InspectorTab />}
                {activeTab === "ai_chat" && <AiChatTab />}
                {activeTab === "sources" && <SourcesTab />}
            </div>
        </aside>
    );
}

/* ── Inspector Tab ─────────────────────────────────────────────────── */

function InspectorTab() {
    const file = useFileStore((state) => state.fileDetail);

    if (!file) {
        return (
            <div className="flex flex-col items-center gap-3 p-8 text-center">
                <span className="material-symbols-outlined text-[32px] text-[#565a6e]">
                    description
                </span>
                <p className="text-xs text-[#565a6e]">
                    Open a file in the editor to inspect its metadata.
                </p>
            </div>
        );
    }

    return (
        <div className="space-y-4 p-4">
            {/* Metadata section */}
            <section>
                <SectionHeader icon="description" label="Metadata" />
                <div className="mt-2 space-y-2">
                    <MetaRow label="File" value={file.name} />
                    <MetaRow label="Path" value={file.path} />
                    <MetaRow
                        label="Modified"
                        value={new Date(file.last_modified).toLocaleString()}
                    />
                    <MetaRow label="Chunks" value={String(file.chunk_count)} />
                    <MetaRow
                        label="Tokens"
                        value={file.token_count.toLocaleString()}
                    />
                    <MetaRow
                        label="Size"
                        value={`${(file.size / 1024).toFixed(1)} KB`}
                    />
                </div>
            </section>

            {/* Connections section — derived from wikilinks */}
            <section>
                <SectionHeader icon="hub" label="Connections" />
                {file.wikilinks.length === 0 ? (
                    <p className="mt-2 text-xs text-[#565a6e]">
                        No wikilinks found in this document.
                    </p>
                ) : (
                    <div className="mt-2 space-y-1.5">
                        {file.wikilinks.map((link) => (
                            <a
                                key={link}
                                href={`#/editor/${link}.md`}
                                className="flex items-center gap-2 rounded-lg border border-[#2a2d3a]
                                 bg-[#181a23] px-3 py-2 text-xs transition
                                 hover:border-[#6366f1]/40 hover:bg-[rgba(99,102,241,0.06)]"
                            >
                                <span className="material-symbols-outlined text-[14px] text-[#6366f1]">
                                    arrow_forward
                                </span>
                                <span className="truncate text-[#e2e4ea]">
                                    {link}
                                </span>
                                <span className="ml-auto text-[10px] uppercase text-[#565a6e]">
                                    outbound
                                </span>
                            </a>
                        ))}
                    </div>
                )}
            </section>
        </div>
    );
}

/* ── AI Chat Tab ───────────────────────────────────────────────────── */

function AiChatTab() {
    const file = useFileStore((state) => state.fileDetail);
    const cursorPosition = useFileStore((state) => state.cursorPosition);
    const selectedModel = useModelStore((state) => state.selectedModel);
    const isSyncing = useFileStore((state) => state.isSyncing);
    const [messages, setMessages] = useState<ChatMessage[]>([]);
    const [input, setInput] = useState("");
    const [isLoading, setIsLoading] = useState(false);
    const scrollRef = useRef<HTMLDivElement>(null);

    /* Auto-scroll on new messages */
    useEffect(() => {
        scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
    }, [messages, isLoading]);

    /* System message when file changes */
    useEffect(() => {
        if (file) {
            setMessages([
                {
                    role: "system",
                    content: `Context loaded: ${file.name} (${file.chunk_count} chunks, ${file.token_count.toLocaleString()} tokens)`,
                },
            ]);
        } else {
            setMessages([]);
        }
    }, [file?.path]);

    const handleSend = useCallback(async () => {
        const trimmed = input.trim();
        if (!trimmed || isLoading) return;

        const userMsg: ChatMessage = { role: "user", content: trimmed };
        setMessages((prev) => [...prev, userMsg]);
        setInput("");
        setIsLoading(true);

        try {
            const rawContext = file ? file.content : "";
            const res = await queryMemory(trimmed, "ws-default", selectedModel, rawContext, cursorPosition);
            const assistantMsg: ChatMessage = {
                role: "assistant",
                content: res.answer,
                sources: res.context,
            };
            setMessages((prev) => [...prev, assistantMsg]);
        } catch (err) {
            const errMsg: ChatMessage = {
                role: "assistant",
                content: `Error: ${err instanceof Error ? err.message : "Query failed"}`,
            };
            setMessages((prev) => [...prev, errMsg]);
        } finally {
            setIsLoading(false);
        }
    }, [input, isLoading]);

    const handleKeyDown = useCallback(
        (e: React.KeyboardEvent) => {
            if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSend();
            }
        },
        [handleSend],
    );

    return (
        <div className="flex h-full flex-col">
            {/* Messages area */}
            <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto p-4">
                {messages.length === 0 && (
                    <div className="flex flex-col items-center gap-2 pt-8 text-center">
                        <span className="material-symbols-outlined text-[28px] text-[#565a6e]">
                            smart_toy
                        </span>
                        <p className="text-xs text-[#565a6e]">
                            Ask questions about your knowledge vault.
                        </p>
                    </div>
                )}
                {messages.map((msg, i) => (
                    <ChatBubble key={i} role={msg.role}>
                        {msg.content}
                        {msg.sources && msg.sources.length > 0 && (
                            <div className="mt-2 space-y-1 border-t border-[#2a2d3a] pt-2">
                                <p className="text-[10px] font-semibold uppercase tracking-wider text-[#565a6e]">
                                    Sources ({msg.sources.length})
                                </p>
                                {msg.sources.map((s, j) => (
                                    <div
                                        key={j}
                                        className="rounded border border-[#2a2d3a] bg-[#0f1117] px-2 py-1
                                         text-[10px] text-[#8b8fa3]"
                                    >
                                        <span className="font-medium text-[#c0c1ff]">
                                            {s.file}
                                        </span>
                                        {" — "}
                                        <span className="text-[#22c55e]">
                                            {(s.score * 100).toFixed(0)}%
                                        </span>
                                    </div>
                                ))}
                            </div>
                        )}
                    </ChatBubble>
                ))}
                {isLoading && (
                    <div className="flex items-center gap-2 rounded-lg border border-[#22d3ee]/20
                         bg-[rgba(34,211,238,0.06)] px-3 py-2 text-xs text-[#22d3ee]">
                        <span className="material-symbols-outlined animate-spin text-[14px]">
                            progress_activity
                        </span>
                        Querying RAG pipeline…
                    </div>
                )}
                {isSyncing && (
                    <div className="flex items-center gap-2 rounded-lg border border-[#f59e0b]/20
                         bg-[rgba(245,158,11,0.06)] px-3 py-2 text-xs text-[#f59e0b]">
                        <span className="material-symbols-outlined animate-spin text-[14px]">
                            sync
                        </span>
                        Syncing vault...
                    </div>
                )}
            </div>

            {/* Input area */}
            <div className="border-t border-[#2a2d3a] p-3">
                <div
                    className="flex items-center gap-2 rounded-lg border border-[#2a2d3a]
                     bg-[#181a23] px-3 py-2"
                >
                    <input
                        type="text"
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        onKeyDown={handleKeyDown}
                        placeholder={file ? `Ask about ${file.name}…` : "Ask anything…"}
                        disabled={isLoading || isSyncing}
                        className="flex-1 bg-transparent text-xs text-[#e2e4ea]
                       placeholder-[#565a6e] outline-none disabled:opacity-50"
                    />
                    <button
                        onClick={handleSend}
                        disabled={isLoading || !input.trim() || isSyncing}
                        className="rounded-md p-1 text-[#6366f1] transition
                       hover:bg-[rgba(99,102,241,0.12)] disabled:opacity-30"
                        aria-label="Send"
                    >
                        <span className="material-symbols-outlined text-[18px]">send</span>
                    </button>
                </div>
            </div>
        </div>
    );
}

/* ── Sources Tab ───────────────────────────────────────────────────── */

function SourcesTab() {
    const file = useFileStore((state) => state.fileDetail);

    /* Sources are stored in the last assistant message from AI Chat.
       We use a shared mechanism: the AiChatTab stores lastSources, but
       since tabs are siblings, we listen to a simple global pattern.
       For now, show file-level context if no query has been made. */

    if (!file) {
        return (
            <div className="flex flex-col items-center gap-3 p-8 text-center">
                <span className="material-symbols-outlined text-[28px] text-[#565a6e]">
                    source
                </span>
                <p className="text-xs text-[#565a6e]">
                    Open a file and query the AI to see retrieved sources.
                </p>
            </div>
        );
    }

    return (
        <div className="space-y-4 p-4">
            <SectionHeader icon="source" label="Document Info" />
            <div className="space-y-2">
                <div className="rounded-lg border border-[#2a2d3a] bg-[#181a23] p-3">
                    <div className="flex items-center justify-between text-xs">
                        <span className="text-[#8b8fa3]">Indexed chunks</span>
                        <span className="font-mono text-[#22c55e]">{file.chunk_count}</span>
                    </div>
                    <div className="mt-1 flex items-center justify-between text-xs">
                        <span className="text-[#8b8fa3]">Token count</span>
                        <span className="font-mono text-[#c0c1ff]">
                            {file.token_count.toLocaleString()}
                        </span>
                    </div>
                    <div className="mt-1 flex items-center justify-between text-xs">
                        <span className="text-[#8b8fa3]">File size</span>
                        <span className="font-mono text-[#e2e4ea]">
                            {(file.size / 1024).toFixed(1)} KB
                        </span>
                    </div>
                </div>
            </div>

            {file.wikilinks.length > 0 && (
                <>
                    <SectionHeader icon="hub" label="Knowledge Graph Links" />
                    <div className="space-y-1">
                        {file.wikilinks.map((link) => (
                            <a
                                key={link}
                                href={`#/editor/${link}.md`}
                                className="flex items-center gap-2 rounded border border-[#2a2d3a]
                                 bg-[#181a23] px-3 py-1.5 text-[11px] text-[#e2e4ea]
                                 transition hover:border-[#6366f1]/40"
                            >
                                <span className="material-symbols-outlined text-[12px] text-[#6366f1]">
                                    link
                                </span>
                                {link}
                            </a>
                        ))}
                    </div>
                </>
            )}
        </div>
    );
}

/* ── Shared primitives ─────────────────────────────────────────────── */

function SectionHeader({ icon, label }: { icon: string; label: string }) {
    return (
        <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-[16px] text-[#6366f1]">
                {icon}
            </span>
            <h3 className="text-[10px] font-semibold uppercase tracking-widest text-[#565a6e]">
                {label}
            </h3>
        </div>
    );
}

function MetaRow({ label, value }: { label: string; value: string }) {
    return (
        <div className="flex items-center justify-between text-xs">
            <span className="text-[#8b8fa3]">{label}</span>
            <span className="max-w-[160px] truncate text-right text-[#e2e4ea]">
                {value}
            </span>
        </div>
    );
}

function ChatBubble({
    role,
    children,
}: {
    role: "system" | "user" | "assistant";
    children: React.ReactNode;
}) {
    const styles: Record<string, string> = {
        system:
            "border-[#2a2d3a] bg-[#181a23] text-[#565a6e] text-[10px] italic",
        user:
            "border-[#6366f1]/30 bg-[rgba(99,102,241,0.08)] text-[#c0c1ff]",
        assistant:
            "border-[#22d3ee]/20 bg-[rgba(34,211,238,0.06)] text-[#e2e4ea]",
    };

    const icons: Record<string, string> = {
        system: "info",
        user: "person",
        assistant: "smart_toy",
    };

    return (
        <div
            className={`rounded-lg border px-3 py-2 text-xs leading-relaxed
                  ${styles[role]}`}
        >
            <div className="mb-1 flex items-center gap-1">
                <span className="material-symbols-outlined text-[12px]">
                    {icons[role]}
                </span>
                <span className="text-[10px] font-semibold uppercase tracking-wider">
                    {role}
                </span>
            </div>
            {children}
        </div>
    );
}
