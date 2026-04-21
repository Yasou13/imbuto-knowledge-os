import { useState } from "react";
import { queryMemory } from "../../shared/api/imbutoClient";
import { useModelStore, MODELS } from "../../store/useModelStore";

/* ── Types ─────────────────────────────────────────────────────────── */

interface RetrievedSource {
    file: string;
    chunk: string;
    score: number;
}

/* ── Static config ─────────────────────────────────────────────────── */

/* ── Component ─────────────────────────────────────────────────────── */

export function QueryEnginePage() {
    const [query, setQuery] = useState("");
    const [workspace, setWorkspace] = useState("ws-default");
    const model = useModelStore((state) => state.selectedModel);
    const setModel = useModelStore((state) => state.setSelectedModel);

    const [isLoading, setIsLoading] = useState(false);
    const [answer, setAnswer] = useState<string | null>(null);
    const [sources, setSources] = useState<RetrievedSource[]>([]);
    const [error, setError] = useState<string | null>(null);

    /* ── Submission handler ──────────────────────────────────────────── */

    const handleSubmit = async () => {
        const trimmed = query.trim();
        if (!trimmed || isLoading) return;

        setIsLoading(true);
        setError(null);
        setAnswer(null);
        setSources([]);

        try {
            const res = await queryMemory(trimmed, workspace, model);
            setAnswer(res.answer);

            const mapped: RetrievedSource[] = (res.context ?? []).map(
                (ctx: any) => ({
                    file: (ctx.file as string) ?? (ctx.source_file as string) ?? "unknown",
                    chunk: (ctx.content as string) ?? (ctx.chunk as string) ?? "",
                    score: (ctx.score as number) ?? (ctx.distance as number) ?? 0,
                }),
            );
            setSources(mapped);
        } catch (err) {
            setError(err instanceof Error ? err.message : "Request failed");
        } finally {
            setIsLoading(false);
        }
    };

    const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
        if (e.key === "Enter") {
            e.preventDefault();
            handleSubmit();
        }
    };

    /* ── Render ──────────────────────────────────────────────────────── */

    return (
        <div className="space-y-6">
            {/* ── Page header ────────────────────────────────────────── */}
            <div className="flex items-center gap-3">
                <span className="material-symbols-outlined text-[28px] text-[#6366f1]">
                    search
                </span>
                <div>
                    <h1 className="text-xl font-semibold text-[#e2e4ea]">
                        Query Engine
                    </h1>
                    <p className="text-xs text-[#565a6e]">
                        Retrieve answers from your knowledge base using RAG
                    </p>
                </div>
            </div>

            {/* ── Search input ───────────────────────────────────────── */}
            <div
                className="flex items-center gap-3 rounded-xl border border-[#2a2d3a]
                   bg-[#13151c] px-4 py-3"
            >
                <span className="material-symbols-outlined text-[20px] text-[#565a6e]">
                    search
                </span>
                <input
                    type="text"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    onKeyDown={handleKeyDown}
                    disabled={isLoading}
                    placeholder="Ask your knowledge base anything..."
                    className="flex-1 bg-transparent text-sm text-[#e2e4ea]
                     placeholder-[#565a6e] outline-none disabled:opacity-50"
                />
                <button
                    onClick={handleSubmit}
                    disabled={isLoading || !query.trim()}
                    className="flex items-center gap-1.5 rounded-lg bg-[#6366f1] px-4 py-2
                     text-xs font-medium text-white transition hover:bg-[#5558e6]
                     active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed"
                >
                    {isLoading ? (
                        <>
                            <span className="material-symbols-outlined animate-spin text-[16px]">
                                progress_activity
                            </span>
                            Synthesizing...
                        </>
                    ) : (
                        <>
                            <span className="material-symbols-outlined text-[16px]">send</span>
                            Ask
                        </>
                    )}
                </button>
            </div>

            {/* ── Config row ─────────────────────────────────────────── */}
            <div className="flex items-center gap-4">
                <div className="flex items-center gap-2">
                    <span className="text-[10px] font-semibold uppercase tracking-widest text-[#565a6e]">
                        Workspace
                    </span>
                    <select
                        value={workspace}
                        onChange={(e) => setWorkspace(e.target.value)}
                        className="rounded-md border border-[#2a2d3a] bg-[#1e2030] px-2 py-1.5
                       text-xs text-[#e2e4ea] outline-none focus:border-[#6366f1]"
                    >
                        <option value="ws-default">Default Vault</option>
                        <option value="ws-research">Research</option>
                    </select>
                </div>

                <div className="flex items-center gap-2">
                    <span className="text-[10px] font-semibold uppercase tracking-widest text-[#565a6e]">
                        Model
                    </span>
                    <select
                        value={model}
                        onChange={(e) => setModel(e.target.value)}
                        className="rounded-md border border-[#2a2d3a] bg-[#1e2030] px-2 py-1.5
                       text-xs text-[#e2e4ea] outline-none focus:border-[#6366f1]"
                    >
                        {MODELS.map((m) => (
                            <option key={m} value={m}>{m}</option>
                        ))}
                    </select>
                </div>

                <button
                    className="flex items-center gap-1.5 rounded-md border border-[#2a2d3a]
                     bg-[#1e2030] px-3 py-1.5 text-xs text-[#8b8fa3] transition
                     hover:border-[#6366f1]/40 hover:text-[#c0c1ff]"
                >
                    <span className="material-symbols-outlined text-[14px]">
                        auto_stories
                    </span>
                    Full Library
                </button>
            </div>

            {/* ── Error state ────────────────────────────────────────── */}
            {error && (
                <div
                    className="flex items-center gap-2 rounded-xl border border-[#ef4444]/30
                     bg-[rgba(239,68,68,0.06)] px-5 py-4 text-sm text-[#ef4444]"
                >
                    <span className="material-symbols-outlined text-[20px]">error</span>
                    {error}
                </div>
            )}

            {/* ── Loading skeleton ───────────────────────────────────── */}
            {isLoading && (
                <div
                    className="animate-pulse space-y-3 rounded-xl border border-[#22d3ee]/20
                     bg-[rgba(34,211,238,0.04)] p-5"
                >
                    <div className="flex items-center gap-2">
                        <span className="material-symbols-outlined animate-spin text-[20px] text-[#22d3ee]">
                            progress_activity
                        </span>
                        <span className="text-sm font-semibold text-[#e2e4ea]">
                            Synthesizing from knowledge base...
                        </span>
                    </div>
                    <div className="h-3 w-3/4 rounded bg-[#1e2030]" />
                    <div className="h-3 w-1/2 rounded bg-[#1e2030]" />
                    <div className="h-3 w-2/3 rounded bg-[#1e2030]" />
                </div>
            )}

            {/* ── AI response card ───────────────────────────────────── */}
            {!isLoading && answer && (
                <div
                    className="rounded-xl border border-[#22d3ee]/20 bg-[rgba(34,211,238,0.04)]
                     p-5"
                >
                    <div className="mb-3 flex items-center gap-2">
                        <span className="material-symbols-outlined text-[20px] text-[#22d3ee]">
                            smart_toy
                        </span>
                        <h2 className="text-sm font-semibold text-[#e2e4ea]">
                            AI Response
                        </h2>
                        <span className="ml-auto text-[10px] text-[#565a6e]">
                            {model.split("/")[1]}
                        </span>
                    </div>
                    <div className="whitespace-pre-wrap text-sm leading-relaxed text-[#c8cacd]">
                        {answer}
                    </div>
                </div>
            )}

            {/* ── Retrieved sources ──────────────────────────────────── */}
            {!isLoading && sources.length > 0 && (
                <div className="space-y-3">
                    <div className="flex items-center gap-2">
                        <span className="material-symbols-outlined text-[16px] text-[#6366f1]">
                            source
                        </span>
                        <h3 className="text-[10px] font-semibold uppercase tracking-widest text-[#565a6e]">
                            Retrieved Sources ({sources.length} chunks)
                        </h3>
                    </div>

                    {sources.map((src, i) => (
                        <div
                            key={i}
                            className="rounded-lg border border-[#2a2d3a] bg-[#13151c] p-4"
                        >
                            <div className="mb-2 flex items-center justify-between">
                                <div className="flex items-center gap-2">
                                    <span className="material-symbols-outlined text-[14px] text-[#6366f1]">
                                        description
                                    </span>
                                    <span className="text-xs font-medium text-[#e2e4ea]">
                                        {src.file}
                                    </span>
                                </div>
                                {src.score > 0 && (
                                    <span
                                        className={`rounded-full px-2 py-0.5 text-[10px] font-semibold
                      ${src.score >= 0.9
                                                ? "bg-[rgba(34,197,94,0.12)] text-[#22c55e]"
                                                : src.score >= 0.85
                                                    ? "bg-[rgba(99,102,241,0.12)] text-[#c0c1ff]"
                                                    : "bg-[rgba(245,158,11,0.12)] text-[#f59e0b]"
                                            }`}
                                    >
                                        {(src.score * 100).toFixed(0)}% match
                                    </span>
                                )}
                            </div>
                            <p className="text-xs leading-relaxed text-[#8b8fa3]">
                                {src.chunk}
                            </p>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}
