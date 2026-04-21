import { useState, useEffect, useCallback } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { listFiles } from "../../api/imbutoClient";
import type { FileMetadata } from "../../api/imbutoClient";
import { useFileStore } from "../../../store/useFileStore";

/* ── Tree types ────────────────────────────────────────────────────── */

interface TreeNode {
    name: string;
    /** Full path for files, empty for folders. */
    path: string;
    isFolder: boolean;
    children: TreeNode[];
}

/* ── Helper: flat list → nested tree ───────────────────────────────── */

function buildTree(files: FileMetadata[]): TreeNode[] {
    const root: TreeNode = { name: "", path: "", isFolder: true, children: [] };

    for (const file of files) {
        const parts = file.path.split("/").filter(Boolean);
        let node = root;

        for (let i = 0; i < parts.length; i++) {
            const part = parts[i];
            const isLast = i === parts.length - 1;

            if (isLast) {
                /* Leaf file node */
                node.children.push({
                    name: file.name,
                    path: file.path,
                    isFolder: false,
                    children: [],
                });
            } else {
                /* Intermediate folder node — find or create */
                let folder = node.children.find(
                    (c) => c.isFolder && c.name === part,
                );
                if (!folder) {
                    folder = { name: part, path: "", isFolder: true, children: [] };
                    node.children.push(folder);
                }
                node = folder;
            }
        }
    }

    /* Sort: folders first (alphabetical), then files (alphabetical) */
    const sortChildren = (nodes: TreeNode[]): TreeNode[] => {
        nodes.sort((a, b) => {
            if (a.isFolder !== b.isFolder) return a.isFolder ? -1 : 1;
            return a.name.localeCompare(b.name);
        });
        for (const n of nodes) {
            if (n.isFolder) sortChildren(n.children);
        }
        return nodes;
    };

    return sortChildren(root.children);
}

/* ── File icon helper ──────────────────────────────────────────────── */

function fileIcon(name: string): string {
    if (name.endsWith(".md")) return "description";
    if (name.endsWith(".json")) return "data_object";
    if (name.endsWith(".py")) return "code";
    if (name.endsWith(".ts") || name.endsWith(".tsx")) return "javascript";
    return "draft";
}

/* ── Recursive TreeNode renderer ───────────────────────────────────── */

function TreeItem({
    node,
    depth,
    activePath,
    onFileClick,
}: {
    node: TreeNode;
    depth: number;
    activePath: string;
    onFileClick: (path: string) => void;
}) {
    const [open, setOpen] = useState(depth < 2); // auto-expand first 2 levels

    if (node.isFolder) {
        return (
            <div>
                <button
                    onClick={() => setOpen((p) => !p)}
                    className="flex w-full items-center gap-1.5 rounded px-1 py-1
                     text-left text-[12px] text-[#8b8fa3] transition
                     hover:bg-[rgba(255,255,255,0.05)] hover:text-[#e2e4ea]"
                    style={{ paddingLeft: `${depth * 12 + 4}px` }}
                >
                    <span className="material-symbols-outlined text-[14px] transition-transform"
                        style={{ transform: open ? "rotate(90deg)" : "rotate(0deg)" }}
                    >
                        chevron_right
                    </span>
                    <span className="material-symbols-outlined text-[14px] text-[#f59e0b]">
                        {open ? "folder_open" : "folder"}
                    </span>
                    <span className="truncate">{node.name}</span>
                </button>

                {open && (
                    <div>
                        {node.children.map((child) => (
                            <TreeItem
                                key={child.isFolder ? `d:${child.name}` : child.path}
                                node={child}
                                depth={depth + 1}
                                activePath={activePath}
                                onFileClick={onFileClick}
                            />
                        ))}
                    </div>
                )}
            </div>
        );
    }

    /* File leaf */
    const isActive =
        activePath === node.path || activePath === encodeURIComponent(node.path);

    return (
        <button
            onClick={() => onFileClick(node.path)}
            className={`flex w-full items-center gap-1.5 rounded px-1 py-1
             text-left text-[12px] transition
             ${isActive
                    ? "bg-[rgba(99,102,241,0.12)] text-[#c0c1ff]"
                    : "text-[#8b8fa3] hover:bg-[rgba(255,255,255,0.05)] hover:text-[#e2e4ea]"
                }`}
            style={{ paddingLeft: `${depth * 12 + 4}px` }}
        >
            <span className="material-symbols-outlined text-[14px]">
                {fileIcon(node.name)}
            </span>
            <span className="min-w-0 truncate">{node.name}</span>
        </button>
    );
}

/* ── Root component ────────────────────────────────────────────────── */

export function FileTree() {
    const [files, setFiles] = useState<FileMetadata[]>([]);
    const [tree, setTree] = useState<TreeNode[]>([]);
    const [loading, setLoading] = useState(true);
    const location = useLocation();
    const navigate = useNavigate();
    const refreshKey = useFileStore((state) => state.fileRefreshKey);

    const activePath = location.pathname.replace(/^\/editor\/?/, "") || "";

    /* ── Fetch ─────────────────────────────────────────────────────── */

    const fetchFiles = useCallback(() => {
        setLoading(true);
        listFiles()
            .then((res) => {
                setFiles(res.files);
                setTree(buildTree(res.files));
            })
            .catch(() => {
                setFiles([]);
                setTree([]);
            })
            .finally(() => setLoading(false));
    }, []);

    useEffect(() => {
        fetchFiles();
    }, [fetchFiles, refreshKey]);

    /* ── Navigate ──────────────────────────────────────────────────── */

    const openFile = useCallback(
        (filePath: string) => {
            const safePath = filePath.replace(/\\/g, '/').split('/').map(encodeURIComponent).join('/');
            navigate(`/editor/${safePath}`);
        },
        [navigate],
    );

    /* ── Render ────────────────────────────────────────────────────── */

    return (
        <div className="flex flex-col">
            {/* Header */}
            <div className="flex items-center justify-between px-2 py-1">
                <p className="text-[10px] font-semibold uppercase tracking-widest text-[#565a6e]">
                    Vault Files
                </p>
                <button
                    onClick={fetchFiles}
                    disabled={loading}
                    className="rounded p-0.5 text-[#565a6e] transition
                     hover:bg-[#1e2030] hover:text-[#8b8fa3]
                     disabled:opacity-40"
                    aria-label="Refresh file list"
                >
                    <span
                        className={`material-symbols-outlined text-[14px]
                        ${loading ? "animate-spin" : ""}`}
                    >
                        sync
                    </span>
                </button>
            </div>

            {/* Tree */}
            {loading && files.length === 0 ? (
                <div className="flex items-center gap-2 px-2 py-4 text-[11px] text-[#565a6e]">
                    <span className="material-symbols-outlined animate-spin text-[14px]">
                        progress_activity
                    </span>
                    Scanning…
                </div>
            ) : tree.length === 0 ? (
                <p className="px-2 py-4 text-[11px] text-[#565a6e]">
                    No files in vault.
                </p>
            ) : (
                <div className="space-y-px">
                    {tree.map((node) => (
                        <TreeItem
                            key={node.isFolder ? `d:${node.name}` : node.path}
                            node={node}
                            depth={0}
                            activePath={activePath}
                            onFileClick={openFile}
                        />
                    ))}
                </div>
            )}
        </div>
    );
}
