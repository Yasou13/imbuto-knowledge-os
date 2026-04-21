import { useEffect, useState, useRef, useCallback, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import ForceGraph3D from "react-force-graph-3d";
import type { ForceGraphMethods } from "react-force-graph-3d";
import * as THREE from "three";
import { getGraphData, addToBlacklist, ApiError } from "../../shared/api/imbutoClient";
import type { GraphDataResponse } from "../../shared/api/imbutoClient";

/* ── Color palette for groups ──────────────────────────────────────── */

const GROUP_PALETTE = [
    "#6366f1", // indigo (primary accent)
    "#22d3ee", // cyan
    "#f59e0b", // amber
    "#10b981", // emerald
    "#f472b6", // pink
    "#a78bfa", // violet
    "#fb923c", // orange
    "#34d399", // teal
    "#e879f9", // fuchsia
    "#38bdf8", // sky
];

function getGroupColor(group: string, groups: string[]): string {
    const idx = groups.indexOf(group);
    return GROUP_PALETTE[idx % GROUP_PALETTE.length];
}

/* ── Types for force-graph internal data ───────────────────────────── */

interface FGNode {
    id: string;
    name: string;
    group: string;
    isFolder?: boolean;  // synthetic folder node
    fileCount?: number;  // how many files in the cluster
    x?: number;
    y?: number;
    vx?: number;
    vy?: number;
    fx?: number | null;
    fy?: number | null;
}

interface FGLink {
    source: string | FGNode;
    target: string | FGNode;
    type: "structural" | "semantic" | "cluster" | "inter-folder";
    weight: number;
    reason?: string;
    linkCount?: number; // for inter-folder edges: how many underlying links
}

/* ── Helpers ───────────────────────────────────────────────────────── */

function linkId(l: FGLink): string {
    const s = typeof l.source === "object" ? (l.source as FGNode).id : l.source;
    const t = typeof l.target === "object" ? (l.target as FGNode).id : l.target;
    return `${s}::${t}`;
}

function nodeId(n: FGNode | string): string {
    return typeof n === "object" ? n.id : n;
}

/* ── Module-level persistence (survives unmount/remount) ────────────── */

let _cachedGraphData: GraphDataResponse | null = null;
let _cachedCameraState: { x: number; y: number; z: number } | null = null;

/* ── Component ─────────────────────────────────────────────────────── */

export function GraphPage() {
    const [graphData, setGraphData] = useState<GraphDataResponse>(
        _cachedGraphData ?? { nodes: [], links: [] }
    );
    const [loading, setLoading] = useState(!_cachedGraphData);
    const [error, setError] = useState<string | null>(null);

    /* ── Interactive state ──────────────────────────────────────────── */
    const [hoverNode, setHoverNode] = useState<FGNode | null>(null);
    const [hoverLink, setHoverLink] = useState<FGLink | null>(null);
    const [mousePos, setMousePos] = useState<{ x: number; y: number }>({ x: 0, y: 0 });

    /* ── Link click popup state ─────────────────────────────────────── */
    const [clickedLink, setClickedLink] = useState<FGLink | null>(null);
    const [popupPos, setPopupPos] = useState<{ x: number; y: number }>({ x: 0, y: 0 });

    /* ── Folder scoping + breadcrumbs ──────────────────────────────── */
    const [folderPath, setFolderPath] = useState<string | null>(null);

    /* ── Filter state ──────────────────────────────────────────────── */
    const [showSemantic, setShowSemantic] = useState(true);
    const [minWeight, setMinWeight] = useState(0.85);

    /* ── Animation tick for semantic pulse ─────────────────────────── */
    const tickRef = useRef(0);

    const navigate = useNavigate();
    const fgRef = useRef<ForceGraphMethods | undefined>(undefined);
    const containerRef = useRef<HTMLDivElement>(null);
    const cameraRestoredRef = useRef(false);
    const fetchingRef = useRef(false);
    const forceInitRef = useRef(false);
    const clickTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const lastClickedNodeRef = useRef<string | null>(null);

    /* ── Responsive dimensions ─────────────────────────────────────── */

    const [dimensions, setDimensions] = useState({ width: 800, height: 600 });

    useEffect(() => {
        const measure = () => {
            if (containerRef.current) {
                const rect = containerRef.current.getBoundingClientRect();
                setDimensions({ width: rect.width, height: rect.height });
            }
        };
        measure();
        const ro = new ResizeObserver(measure);
        if (containerRef.current) ro.observe(containerRef.current);
        return () => ro.disconnect();
    }, []);

    /* ── Pulse tick (semantic link animation) ──────────────────────── */

    useEffect(() => {
        let raf: number;
        const loop = () => {
            tickRef.current += 1;
            raf = requestAnimationFrame(loop);
        };
        raf = requestAnimationFrame(loop);
        return () => cancelAnimationFrame(raf);
    }, []);

    /* ── Fetch graph data (guarded, single-flight, folder-aware) ───── */

    const fetchGraph = useCallback((force = false, folder?: string | null) => {
        if (fetchingRef.current) return;
        if (_cachedGraphData && !force && folder === undefined) return;

        fetchingRef.current = true;
        setLoading(true);
        setError(null);

        getGraphData(folder ?? undefined)
            .then((data) => {
                setGraphData(data);
                if (folder === undefined || folder === null) {
                    _cachedGraphData = data;
                }
                // Reset force initialization flag so new data gets proper forces
                forceInitRef.current = false;
            })
            .catch((err) => {
                const msg = err instanceof Error ? err.message : "Failed to load graph";
                const status = err instanceof ApiError ? err.status : 0;
                if (status === 404 || status >= 500) {
                    setError(`Sync Error (${status}): ${msg}`);
                } else {
                    setError(msg);
                }
            })
            .finally(() => {
                setLoading(false);
                fetchingRef.current = false;
            });
    }, []);

    // Auto-fetch on mount + when folderPath changes
    useEffect(() => {
        fetchGraph(true, folderPath);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [folderPath]);

    /* ── Restore camera position from cache ────────────────────────── */

    useEffect(() => {
        if (_cachedCameraState && fgRef.current && !cameraRestoredRef.current) {
            const fg = fgRef.current;
            const timer = setTimeout(() => {
                fg.cameraPosition?.(_cachedCameraState!, undefined, 100);
                cameraRestoredRef.current = true;
            }, 100);
            return () => clearTimeout(timer);
        }
    }, [loading]);

    /* ── Save camera on unmount ─────────────────────────────────────── */

    useEffect(() => {
        return () => {
            try {
                if (fgRef.current) {
                    const pos = (fgRef.current as any).cameraPosition();
                    _cachedCameraState = { x: pos.x, y: pos.y, z: pos.z };

                    // Force WebGL context destruction cleanly
                    if (typeof (fgRef.current as any)._destructor === 'function') {
                        (fgRef.current as any)._destructor();
                    }
                }
            } catch { /* best-effort */ }
        };
    }, []);

    /* ── Track mouse position for tooltip ──────────────────────────── */

    useEffect(() => {
        const handler = (e: MouseEvent) => setMousePos({ x: e.clientX, y: e.clientY });
        window.addEventListener("mousemove", handler);
        return () => window.removeEventListener("mousemove", handler);
    }, []);

    /* ── Derived: breadcrumb segments ─────────────────────────────── */

    const breadcrumbs = useMemo(() => {
        const crumbs: { label: string; path: string | null }[] = [
            { label: "Vault", path: null },
        ];
        if (folderPath) {
            const parts = folderPath.split("/").filter(Boolean);
            let acc = "";
            for (const part of parts) {
                acc = acc ? `${acc}/${part}` : part;
                crumbs.push({ label: part, path: acc });
            }
        }
        return crumbs;
    }, [folderPath]);

    /* ── Derived: unique groups ─────────────────────────────────────── */

    const uniqueGroups = useMemo(
        () => [...new Set(graphData.nodes.map((n) => n.group))].sort(),
        [graphData.nodes]
    );

    /* ── Derived: folder-count map ─────────────────────────────────── */

    const folderCounts = useMemo(() => {
        const counts: Record<string, number> = {};
        graphData.nodes.forEach((n) => {
            counts[n.group] = (counts[n.group] || 0) + 1;
        });
        return counts;
    }, [graphData.nodes]);

    /* ── Derived: graph data with macro/micro view ─────────────────── */

    const augmentedGraphData = useMemo(() => {
        // Filter semantic links by user controls
        const filteredLinks: FGLink[] = graphData.links.filter((l) => {
            if (l.type === "semantic") {
                if (!showSemantic) return false;
                if (l.weight < minWeight) return false;
            }
            return true;
        });

        // ── MICRO VIEW (drilled into a folder) ──────────────────────
        if (folderPath) {
            return { nodes: [...graphData.nodes], links: filteredLinks };
        }

        // ── MACRO VIEW (global — folders only) ──────────────────────
        // 1. Create folder cluster nodes
        const nonRootGroups = uniqueGroups.filter((g) => g !== "root");
        const rootFiles = graphData.nodes.filter((n) => n.group === "root");

        const folderNodes: FGNode[] = nonRootGroups.map((g) => ({
            id: `__folder__${g}`,
            name: `📁 ${g}`,
            group: g,
            isFolder: true,
            fileCount: folderCounts[g] || 0,
        }));

        // 2. Compute inter-folder edges by aggregating file-level links
        const interFolderMap = new Map<string, { weight: number; count: number; types: Set<string> }>();
        const nodeGroupMap: Record<string, string> = {};
        graphData.nodes.forEach((n) => { nodeGroupMap[n.id] = n.group; });

        filteredLinks.forEach((l) => {
            const srcId = typeof l.source === "string" ? l.source : (l.source as FGNode).id;
            const tgtId = typeof l.target === "string" ? l.target : (l.target as FGNode).id;
            const srcGroup = nodeGroupMap[srcId];
            const tgtGroup = nodeGroupMap[tgtId];
            if (!srcGroup || !tgtGroup) return;
            if (srcGroup === tgtGroup) return; // intra-folder → skip for macro view
            if (srcGroup === "root" || tgtGroup === "root") return;

            const key = [srcGroup, tgtGroup].sort().join("::");
            const existing = interFolderMap.get(key);
            if (existing) {
                existing.weight = Math.max(existing.weight, l.weight);
                existing.count += 1;
                existing.types.add(l.type);
            } else {
                interFolderMap.set(key, { weight: l.weight, count: 1, types: new Set([l.type]) });
            }
        });

        const interFolderLinks: FGLink[] = [];
        interFolderMap.forEach((val, key) => {
            const [a, b] = key.split("::");
            interFolderLinks.push({
                source: `__folder__${a}`,
                target: `__folder__${b}`,
                type: "inter-folder",
                weight: val.weight,
                linkCount: val.count,
                reason: `${val.count} connection${val.count > 1 ? "s" : ""} (${[...val.types].join(", ")})`,
            });
        });

        // 3. Include root files as individual nodes (they have no folder)
        return {
            nodes: [...rootFiles, ...folderNodes],
            links: interFolderLinks,
        };
    }, [graphData, showSemantic, minWeight, folderPath, uniqueGroups, folderCounts]);

    /* ── Derived: neighbor highlight set ────────────────────────────── */

    const highlightNeighbors = useMemo(() => {
        if (!hoverNode) return new Set<string>();
        const neighbors = new Set<string>([hoverNode.id]);
        augmentedGraphData.links.forEach((link) => {
            if (link.type === "cluster") return;
            const src = nodeId(link.source as FGNode);
            const tgt = nodeId(link.target as FGNode);
            if (src === hoverNode.id) neighbors.add(tgt);
            if (tgt === hoverNode.id) neighbors.add(src);
        });
        return neighbors;
    }, [hoverNode, augmentedGraphData.links]);

    /* ── Counts ────────────────────────────────────────────────────── */

    const visibleLinks = augmentedGraphData.links.filter((l) => l.type !== "cluster");
    const structuralCount = visibleLinks.filter((l) => l.type === "structural").length;
    const semanticCount = visibleLinks.filter((l) => l.type === "semantic").length;

    /* ── Node 3D renderer ──────────────────────────────────────── */

    const getNodeObject = useCallback(
        (node: object) => {
            const n = node as FGNode;
            const color = getGroupColor(n.group, uniqueGroups);

            const isHighlighted = hoverNode ? highlightNeighbors.has(n.id) : true;
            const isHovered = hoverNode?.id === n.id;

            if (n.isFolder) {
                const group = new THREE.Group();
                const isFolderHighlighted = !hoverNode || hoverNode.group === n.group;

                // Main inner sphere
                const mainGeom = new THREE.SphereGeometry(10);
                const mainMat = new THREE.MeshLambertMaterial({
                    color,
                    transparent: true,
                    opacity: isFolderHighlighted ? 0.35 : 0.15
                });
                group.add(new THREE.Mesh(mainGeom, mainMat));

                // Outer glow sphere
                const glowGeom = new THREE.SphereGeometry(15);
                const glowMat = new THREE.MeshBasicMaterial({
                    color,
                    transparent: true,
                    opacity: isFolderHighlighted ? 0.08 : 0.02
                });
                group.add(new THREE.Mesh(glowGeom, glowMat));

                return group;
            }

            // Regular file node
            const radius = isHovered ? 6 : 4;
            const geom = new THREE.SphereGeometry(radius);
            const mat = new THREE.MeshLambertMaterial({
                color: isHighlighted ? color : "#555555",
                transparent: true,
                opacity: isHighlighted ? 1.0 : 0.3
            });
            return new THREE.Mesh(geom, mat);
        },
        [hoverNode, highlightNeighbors, uniqueGroups]
    );

    /* ── Link 3D dimensions & styling ──────────────────────────────── */

    const getLinkWidth = useCallback((link: object) => {
        const l = link as FGLink;
        if (l.type === "cluster") return 0;
        const srcId = nodeId(l.source);
        const tgtId = nodeId(l.target);
        const isNeighborLink = hoverNode && highlightNeighbors.has(srcId) && highlightNeighbors.has(tgtId);
        const isLinkHovered = hoverLink && linkId(hoverLink) === linkId(l);
        const isLinkClicked = clickedLink && linkId(clickedLink) === linkId(l);

        if (l.type === "inter-folder") {
            return isLinkHovered || isLinkClicked ? 3 : 1.5;
        }

        const weightNorm = l.type === "semantic" ? (l.weight - 0.82) / (1.0 - 0.82) : 1.0;
        const baseWidth = l.type === "semantic" ? 0.4 + weightNorm * 1.6 : 0.8;
        return isLinkHovered || isLinkClicked ? baseWidth + 1 : isNeighborLink ? baseWidth + 0.5 : baseWidth;
    }, [hoverNode, hoverLink, clickedLink, highlightNeighbors]);

    const getLinkColor = useCallback((link: object) => {
        const l = link as FGLink;
        if (l.type === "cluster") return "rgba(0,0,0,0)";

        const srcId = nodeId(l.source);
        const tgtId = nodeId(l.target);
        const isNeighborLink = hoverNode && highlightNeighbors.has(srcId) && highlightNeighbors.has(tgtId);
        const isLinkHovered = hoverLink && linkId(hoverLink) === linkId(l);
        const isLinkClicked = clickedLink && linkId(clickedLink) === linkId(l);

        if (l.type === "inter-folder") {
            const alpha = isLinkHovered || isLinkClicked ? 0.9 : isNeighborLink ? 0.7 : 0.3;
            return `rgba(192, 193, 255, ${alpha})`;
        }

        const weightNorm = l.type === "semantic" ? (l.weight - 0.82) / (1.0 - 0.82) : 1.0;
        const baseAlpha = l.type === "semantic" ? 0.15 + weightNorm * 0.7 : 0.4;

        if (l.type === "semantic") {
            const alpha = isLinkHovered || isLinkClicked ? 0.95 : isNeighborLink ? Math.min(baseAlpha + 0.3, 0.9) : baseAlpha;
            return `rgba(163, 139, 250, ${alpha})`;
        } else {
            const alpha = isLinkHovered || isLinkClicked ? 0.95 : isNeighborLink ? 0.8 : baseAlpha;
            return `rgba(99, 102, 241, ${alpha})`;
        }
    }, [hoverNode, hoverLink, clickedLink, highlightNeighbors]);

    /* ── Handlers ──────────────────────────────────────────────────── */

    const handleNodeClick = useCallback(
        (node: object) => {
            setClickedLink(null);
            const n = node as FGNode;

            if (n.isFolder) {
                // Double-click detection for folder drill-down
                if (lastClickedNodeRef.current === n.id && clickTimerRef.current) {
                    // Second click within 300ms → drill down
                    clearTimeout(clickTimerRef.current);
                    clickTimerRef.current = null;
                    lastClickedNodeRef.current = null;
                    setFolderPath(n.group);
                    setTimeout(() => fgRef.current?.zoomToFit(400, 100), 300);
                } else {
                    // First click → start timer
                    lastClickedNodeRef.current = n.id;
                    clickTimerRef.current = setTimeout(() => {
                        clickTimerRef.current = null;
                        lastClickedNodeRef.current = null;
                    }, 300);
                }
                return;
            }

            // File node → open in editor
            navigate(`/editor/${encodeURIComponent(n.id)}`);
        },
        [navigate]
    );

    const handleNodeHover = useCallback(
        (node: object | null) => {
            const n = node as FGNode | null;
            setHoverNode(n || null);
            if (n) setHoverLink(null);
            if (containerRef.current) {
                containerRef.current.style.cursor = n ? "pointer" : "default";
            }
        },
        []
    );

    const handleLinkHover = useCallback(
        (link: object | null) => {
            const l = link as FGLink | null;
            // Don't show hover for cluster links
            if (l && l.type === "cluster") return;
            setHoverLink(l || null);
            if (containerRef.current) {
                containerRef.current.style.cursor = l ? "pointer" : "default";
            }
        },
        []
    );

    const handleLinkClick = useCallback(
        (link: object) => {
            const l = link as FGLink;
            if (l.type === "cluster") return;
            setClickedLink(l);
            setPopupPos({ x: mousePos.x, y: mousePos.y });
        },
        [mousePos]
    );

    const handleBreakConnection = useCallback(
        async () => {
            if (!clickedLink) return;
            const src = typeof clickedLink.source === "object"
                ? (clickedLink.source as FGNode).id : clickedLink.source;
            const tgt = typeof clickedLink.target === "object"
                ? (clickedLink.target as FGNode).id : clickedLink.target;

            setGraphData((prev) => ({
                ...prev,
                links: prev.links.filter((lnk) => {
                    const lSrc = typeof lnk.source === "string" ? lnk.source : lnk.source;
                    const lTgt = typeof lnk.target === "string" ? lnk.target : lnk.target;
                    const srcMatch = lSrc === src || lSrc === tgt;
                    const tgtMatch = lTgt === src || lTgt === tgt;
                    return !(srcMatch && tgtMatch);
                }),
            }));
            setClickedLink(null);

            try {
                await addToBlacklist(src, tgt);
            } catch (err) {
                console.error("Failed to blacklist link:", err);
            }
        },
        [clickedLink]
    );

    const handleBackgroundClick = useCallback(() => {
        setClickedLink(null);
    }, []);

    /* ── Configure clustered forces after graph engine mounts ─────── */

    const handleEngineInit = useCallback(() => {
        const fg = fgRef.current;
        if (!fg || forceInitRef.current) return;
        forceInitRef.current = true;

        const d3 = (fg as any).d3Force;
        if (!d3) return;

        // --- Charge: strong repulsion between all, extra for inter-group ---
        const chargeFn = d3("charge");
        if (chargeFn) {
            chargeFn.strength((n: any) => {
                if (n.isFolder) return -400;  // folder nodes push harder
                return -120;
            }).distanceMax(400);
        }

        // --- Link distance: based on type & weight ---
        const linkFn = d3("link");
        if (linkFn) {
            linkFn.distance((l: any) => {
                if (l.type === "cluster") return 30;  // tight cluster pull
                if (l.type === "semantic") {
                    // High similarity → short link, low → long
                    const w = l.weight ?? 0.82;
                    return 200 - (w - 0.82) / (1.0 - 0.82) * 160;  // 200 → 40
                }
                return 70;  // structural
            }).strength((l: any) => {
                if (l.type === "cluster") return 0.8;  // strong cluster bond
                if (l.type === "semantic") return 0.3;
                return 0.5;  // structural
            });
        }

        // --- Add a cluster force: same-group attraction ---
        // We use D3's forceX/forceY with per-group centers calculated from
        // the folder node positions — but the simpler approach is the
        // cluster links above, which already achieve this.

    }, []);

    /* ── RENDER: Loading ───────────────────────────────────────────── */

    if (loading) {
        return (
            <div className="flex h-full w-full items-center justify-center">
                <div className="flex flex-col items-center gap-3">
                    <span className="material-symbols-outlined animate-spin text-[32px] text-[#6366f1]">
                        progress_activity
                    </span>
                    <p className="text-sm text-[#565a6e]">Loading Graph View…</p>
                </div>
            </div>
        );
    }

    /* ── RENDER: Error ─────────────────────────────────────────────── */

    if (error) {
        const isSyncError = error.startsWith("Sync Error");
        return (
            <div className="flex h-full w-full items-center justify-center">
                <div
                    className={`flex flex-col items-center gap-3 rounded-xl border px-8 py-6 text-center
                     ${isSyncError
                            ? "border-[#f59e0b]/30 bg-[rgba(245,158,11,0.06)]"
                            : "border-[#ef4444]/30 bg-[rgba(239,68,68,0.06)]"
                        }`}
                >
                    <span
                        className={`material-symbols-outlined text-[32px] ${isSyncError ? "text-[#f59e0b]" : "text-[#ef4444]"
                            }`}
                    >
                        {isSyncError ? "sync_problem" : "error"}
                    </span>
                    <h2 className="text-lg font-semibold text-[#e2e4ea]">
                        {isSyncError ? "Sync Error" : "Graph Load Failed"}
                    </h2>
                    <p className="max-w-sm text-sm text-[#8b8fa3]">{error}</p>
                    <button
                        onClick={() => {
                            setError(null);
                            _cachedGraphData = null;
                            fetchGraph(true, folderPath);
                        }}
                        className="mt-2 flex items-center gap-1.5 rounded-lg border border-[#2a2d3a]
                            bg-[#1e2030] px-4 py-2 text-xs text-[#8b8fa3]
                            transition hover:bg-[#2a2d3a] hover:text-[#e2e4ea]"
                    >
                        <span className="material-symbols-outlined text-[16px]">refresh</span>
                        Retry
                    </button>
                </div>
            </div>
        );
    }

    /* ── RENDER: Graph ─────────────────────────────────────────────── */

    return (
        <div ref={containerRef} className="relative h-full w-full overflow-hidden -m-6">
            {/* ── Breadcrumb navigation (top-left) ────────────────── */}
            <div className="absolute top-4 left-4 z-20 flex items-center gap-1.5 rounded-lg border border-[#2a2d3a]
                 bg-[#13151c]/90 px-3 py-1.5 shadow-xl backdrop-blur">
                {breadcrumbs.map((crumb, i) => (
                    <span key={crumb.path ?? "root"} className="flex items-center gap-1">
                        {i > 0 && (
                            <span className="material-symbols-outlined text-[12px] text-[#565a6e]">
                                chevron_right
                            </span>
                        )}
                        <button
                            onClick={() => setFolderPath(crumb.path)}
                            className={`text-[11px] font-medium transition-colors
                                ${crumb.path === folderPath
                                    ? "text-[#c0c1ff]"
                                    : "text-[#8b8fa3] hover:text-[#e2e4ea]"
                                }`}
                        >
                            {crumb.label}
                        </button>
                    </span>
                ))}

                {/* "Back to Global" button when drilled into a folder */}
                {folderPath && (
                    <>
                        <span className="mx-1.5 h-3 w-px bg-[#2a2d3a]" />
                        <button
                            onClick={() => {
                                setFolderPath(null);
                                setTimeout(() => fgRef.current?.zoomToFit(400, 100), 300);
                            }}
                            className="flex items-center gap-1 rounded-md bg-[#6366f1]/15 px-2 py-0.5
                                text-[10px] font-medium text-[#c0c1ff]
                                transition hover:bg-[#6366f1]/25"
                        >
                            <span className="material-symbols-outlined text-[12px]">zoom_out_map</span>
                            Global View
                        </button>
                    </>
                )}
            </div>

            {/* Force graph canvas */}
            <ForceGraph3D
                ref={fgRef}
                width={dimensions.width}
                height={dimensions.height}
                graphData={augmentedGraphData as any}
                nodeThreeObject={getNodeObject}
                linkWidth={getLinkWidth}
                linkColor={getLinkColor}
                linkResolution={8}
                onNodeClick={handleNodeClick}
                onNodeHover={handleNodeHover}
                onLinkHover={handleLinkHover}
                onLinkClick={handleLinkClick}
                onBackgroundClick={handleBackgroundClick}
                onEngineStop={handleEngineInit}
                backgroundColor="#0f1117"
                cooldownTicks={_cachedCameraState ? 0 : 120}
                d3AlphaDecay={0.015}
                d3VelocityDecay={0.2}
            />

            {/* ── Node tooltip (hover) ─────────────────────────────── */}
            {hoverNode && !hoverLink && !clickedLink && (
                <div
                    className="pointer-events-none fixed z-50 rounded-lg border border-[#2a2d3a]
                     bg-[#13151c]/95 px-3 py-2 shadow-xl backdrop-blur"
                    style={{ left: mousePos.x + 14, top: mousePos.y - 10 }}
                >
                    {hoverNode.isFolder ? (
                        <>
                            <p className="text-xs font-semibold text-[#c0c1ff]">
                                <span className="material-symbols-outlined mr-1 align-middle text-[14px]">folder</span>
                                {hoverNode.group}
                            </p>
                            <p className="mt-0.5 text-[10px] text-[#8b8fa3]">
                                {hoverNode.fileCount} files
                            </p>
                            <p className="mt-0.5 text-[9px] text-[#6366f1] italic">Double-click to explore</p>
                        </>
                    ) : (
                        <>
                            <p className="text-xs font-medium text-[#e2e4ea]">{hoverNode.name}</p>
                            <p className="text-[10px] text-[#565a6e]">{hoverNode.id}</p>
                            <p className="mt-1 text-[10px] text-[#8b8fa3]">
                                <span
                                    className="mr-1 inline-block h-2 w-2 rounded-full"
                                    style={{ backgroundColor: getGroupColor(hoverNode.group, uniqueGroups) }}
                                />
                                {hoverNode.group}
                            </p>
                        </>
                    )}
                </div>
            )}

            {/* ── Link tooltip (hover) ─────────────────────────────── */}
            {hoverLink && !clickedLink && hoverLink.type !== "cluster" && (
                <div
                    className="pointer-events-none fixed z-50 rounded-lg border border-[#2a2d3a]
                     bg-[#13151c]/95 px-3 py-2 shadow-xl backdrop-blur"
                    style={{ left: mousePos.x + 14, top: mousePos.y - 10 }}
                >
                    {hoverLink.type === "semantic" ? (
                        <>
                            <p className="text-xs font-medium text-[#a78bfa]">
                                <span className="material-symbols-outlined mr-1 align-middle text-[14px]">
                                    neurology
                                </span>
                                Semantic Link: {Math.round(hoverLink.weight * 100)}% Match
                            </p>
                            {hoverLink.reason && (
                                <p className="mt-0.5 text-[10px] text-[#c0c1ff]">{hoverLink.reason}</p>
                            )}
                            <p className="mt-0.5 text-[9px] text-[#565a6e] italic">Click to manage</p>
                        </>
                    ) : (
                        <>
                            <p className="text-xs font-medium text-[#6366f1]">
                                <span className="material-symbols-outlined mr-1 align-middle text-[14px]">
                                    link
                                </span>
                                Structural Link (wikilink)
                            </p>
                            <p className="mt-0.5 text-[9px] text-[#565a6e] italic">Click to manage</p>
                        </>
                    )}
                </div>
            )}

            {/* ── Link click popup (interactive) ──────────────────── */}
            {clickedLink && clickedLink.type !== "cluster" && (
                <div
                    className="fixed z-[60] w-[260px] rounded-xl border border-[#2a2d3a]
                     bg-[#13151c]/95 p-4 shadow-2xl backdrop-blur"
                    style={{
                        left: Math.min(popupPos.x + 10, dimensions.width - 280),
                        top: Math.min(popupPos.y - 40, dimensions.height - 200),
                    }}
                >
                    {/* Header */}
                    <div className="flex items-center justify-between">
                        <span className={`text-xs font-semibold ${clickedLink.type === "semantic" ? "text-[#a78bfa]" : "text-[#6366f1]"
                            }`}>
                            <span className="material-symbols-outlined mr-1 align-middle text-[16px]">
                                {clickedLink.type === "semantic" ? "neurology" : "link"}
                            </span>
                            {clickedLink.type === "semantic" ? "Semantic" : "Structural"} Link
                        </span>
                        <button
                            onClick={() => setClickedLink(null)}
                            className="rounded p-0.5 text-[#565a6e] hover:bg-[#2a2d3a] hover:text-[#e2e4ea]"
                        >
                            <span className="material-symbols-outlined text-[16px]">close</span>
                        </button>
                    </div>

                    {/* Nodes */}
                    <div className="mt-2 rounded-lg bg-[#0f1117] px-2.5 py-2">
                        <p className="text-[10px] text-[#8b8fa3]">
                            {typeof clickedLink.source === "object"
                                ? (clickedLink.source as FGNode).name
                                : clickedLink.source}
                        </p>
                        <span className="text-[10px] text-[#565a6e]">
                            {clickedLink.type === "semantic" ? " ↔ " : " → "}
                        </span>
                        <p className="text-[10px] text-[#8b8fa3]">
                            {typeof clickedLink.target === "object"
                                ? (clickedLink.target as FGNode).name
                                : clickedLink.target}
                        </p>
                    </div>

                    {/* Weight */}
                    {clickedLink.type === "semantic" && (
                        <div className="mt-2 flex items-center justify-between">
                            <span className="text-[10px] text-[#565a6e]">Similarity</span>
                            <span className="text-[11px] font-mono font-semibold text-[#e2e4ea]">
                                {Math.round(clickedLink.weight * 100)}%
                            </span>
                        </div>
                    )}

                    {/* Reason */}
                    {clickedLink.reason && (
                        <div className="mt-2 rounded-lg border border-[#2a2d3a] bg-[#1e2030] px-2.5 py-1.5">
                            <p className="text-[9px] font-semibold uppercase tracking-widest text-[#565a6e]">
                                Connection Reason
                            </p>
                            <p className="mt-0.5 text-[11px] text-[#c0c1ff]">{clickedLink.reason}</p>
                        </div>
                    )}

                    {/* Break Connection button */}
                    <button
                        onClick={handleBreakConnection}
                        className="mt-3 flex w-full items-center justify-center gap-1.5 rounded-lg
                            border border-[#ef4444]/30 bg-[rgba(239,68,68,0.08)] px-3 py-2
                            text-[11px] font-medium text-[#ef4444] transition
                            hover:bg-[rgba(239,68,68,0.15)] hover:border-[#ef4444]/50"
                    >
                        <span className="material-symbols-outlined text-[16px]">link_off</span>
                        Break Connection
                    </button>
                </div>
            )}

            {/* ── Filter control panel (top-right) ────────────────── */}
            <div
                className="absolute top-4 right-4 z-20 w-[220px] rounded-xl border border-[#2a2d3a]
                 bg-[#13151c]/90 px-4 py-3 shadow-xl backdrop-blur"
            >
                <div className="flex items-center justify-between">
                    <h3 className="flex items-center gap-2 text-xs font-semibold text-[#c0c1ff]">
                        <span className="material-symbols-outlined text-[16px]">tune</span>
                        Filters
                    </h3>
                    <button
                        onClick={() => {
                            _cachedGraphData = null;
                            fetchGraph(true, folderPath);
                        }}
                        disabled={loading}
                        className="flex items-center gap-1 rounded-md px-2 py-1 text-[10px] font-medium
                            text-[#8b8fa3] transition hover:bg-[#1e2030] hover:text-[#e2e4ea]
                            disabled:opacity-50 disabled:cursor-not-allowed"
                        title="Re-fetch graph from server"
                    >
                        <span className={`material-symbols-outlined text-[14px] ${loading ? "animate-spin" : ""}`}>
                            refresh
                        </span>
                        Refresh
                    </button>
                </div>

                {/* Toggle: Show Semantic Links */}
                <div className="mt-3 flex items-center justify-between">
                    <span className="text-[11px] text-[#8b8fa3]">Semantic Links</span>
                    <button
                        onClick={() => setShowSemantic((v) => !v)}
                        className={`relative h-5 w-9 rounded-full transition-colors duration-200
                            ${showSemantic ? "bg-[#6366f1]" : "bg-[#2a2d3a]"}`}
                        aria-label="Toggle semantic links"
                    >
                        <span
                            className={`absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white
                                transition-transform duration-200
                                ${showSemantic ? "translate-x-4" : "translate-x-0"}`}
                        />
                    </button>
                </div>

                {/* Similarity threshold slider */}
                <div className={`mt-3 transition-opacity duration-200 ${showSemantic ? "opacity-100" : "opacity-30 pointer-events-none"}`}>
                    <div className="flex items-center justify-between">
                        <span className="text-[11px] text-[#8b8fa3]">Min Similarity</span>
                        <span className="text-[11px] font-mono text-[#e2e4ea]">
                            {Math.round(minWeight * 100)}%
                        </span>
                    </div>
                    <input
                        type="range"
                        min={85}
                        max={100}
                        step={1}
                        value={Math.round(minWeight * 100)}
                        onChange={(e) => setMinWeight(Number(e.target.value) / 100)}
                        className="mt-1.5 h-1 w-full cursor-pointer appearance-none rounded-full
                            bg-[#2a2d3a] accent-[#6366f1]
                            [&::-webkit-slider-thumb]:h-3.5 [&::-webkit-slider-thumb]:w-3.5
                            [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full
                            [&::-webkit-slider-thumb]:bg-[#6366f1] [&::-webkit-slider-thumb]:shadow-md
                            [&::-webkit-slider-thumb]:transition-transform [&::-webkit-slider-thumb]:hover:scale-125"
                    />
                    <div className="mt-1 flex justify-between text-[9px] text-[#565a6e]">
                        <span>85%</span>
                        <span>100%</span>
                    </div>
                </div>

                {/* Stats */}
                <div className="mt-3 border-t border-[#2a2d3a] pt-2">
                    <p className="text-[10px] text-[#8b8fa3]">
                        Showing {structuralCount + semanticCount} edges
                        <span className="text-[#565a6e]">
                            {" "}({structuralCount} structural, {semanticCount} semantic)
                        </span>
                    </p>
                    {!folderPath && uniqueGroups.filter(g => g !== "root").length > 0 && (
                        <p className="mt-1 text-[10px] text-[#565a6e]">
                            {uniqueGroups.filter(g => g !== "root").length} folder clusters
                        </p>
                    )}
                </div>
            </div>

            {/* ── Legend panel (bottom-left) ────────────────────────── */}
            <div
                className="absolute bottom-4 left-4 z-20 rounded-xl border border-[#2a2d3a]
                 bg-[#13151c]/90 px-4 py-3 shadow-xl backdrop-blur"
            >
                <h3 className="text-xs font-semibold text-[#c0c1ff]">
                    {folderPath ? `📁 ${folderPath}` : "Knowledge Graph"}
                </h3>
                <p className="mt-1 text-[10px] text-[#8b8fa3]">
                    {graphData.nodes.length} nodes &bull;{" "}
                    {structuralCount + semanticCount} edges
                </p>

                {/* Group legend */}
                <div className="mt-3 space-y-1">
                    <p className="text-[9px] font-semibold uppercase tracking-widest text-[#565a6e]">
                        {folderPath ? "Files" : "Clusters"}
                    </p>
                    {uniqueGroups.map((g) => (
                        <div key={g} className="flex items-center gap-2">
                            <span
                                className="inline-block h-2.5 w-2.5 rounded-full"
                                style={{ backgroundColor: getGroupColor(g, uniqueGroups) }}
                            />
                            <button
                                onClick={() => setFolderPath(g === "root" ? null : g)}
                                className="text-[10px] text-[#8b8fa3] hover:text-[#e2e4ea] transition"
                            >
                                {g} {!folderPath && folderCounts[g] ? `(${folderCounts[g]})` : ""}
                            </button>
                        </div>
                    ))}
                </div>

                {/* Link type legend */}
                <div className="mt-3 space-y-1">
                    <p className="text-[9px] font-semibold uppercase tracking-widest text-[#565a6e]">
                        Edges
                    </p>
                    <div className="flex items-center gap-2">
                        <span className="inline-block h-0.5 w-4 bg-[#6366f1]" />
                        <span className="text-[10px] text-[#8b8fa3]">
                            Structural (wikilink)
                        </span>
                    </div>
                    <div className="flex items-center gap-2">
                        <span
                            className="inline-block h-0.5 w-4"
                            style={{
                                background:
                                    "repeating-linear-gradient(90deg, #a78bfa 0 3px, transparent 3px 6px)",
                            }}
                        />
                        <span className="text-[10px] text-[#8b8fa3]">
                            Semantic (pulsing)
                        </span>
                    </div>
                </div>

                <p className="mt-3 text-[9px] text-[#565a6e]">
                    {folderPath
                        ? "Click node → Editor • Click link → Manage"
                        : "Click cluster → Drill down • Click file → Editor"}
                </p>
            </div>
        </div>
    );
}
