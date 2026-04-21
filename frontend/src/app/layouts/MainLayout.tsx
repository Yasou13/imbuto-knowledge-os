import type { ReactNode } from "react";
import { Sidebar } from "../../shared/ui/Sidebar/Sidebar";
import { TopNav } from "../../shared/ui/TopNav/TopNav";
import { ContextPanel } from "../../widgets/ContextPanel/ContextPanel";

interface MainLayoutProps {
    children: ReactNode;
}

/**
 * Root layout shell.
 *
 * Dimensions:
 *  - Left sidebar:  240px (fixed)
 *  - Right panel:   320px (fixed, ContextPanel)
 *  - TopNav:        48px
 */
export function MainLayout({ children }: MainLayoutProps) {
    return (
        <div className="flex h-screen overflow-hidden bg-[#0f1117]">
            {/* ── Fixed sidebar ────────────────────────────────────── */}
            <Sidebar />

            {/* ── Main content area ────────────────────────────────── */}
            <div
                className="relative ml-[240px] mr-[320px] flex flex-1 flex-col
                   h-screen"
            >
                <TopNav />

                <main className="flex-1 overflow-y-auto p-6">
                    {children}
                </main>
            </div>

            {/* ── Right context panel ────────────────────────────── */}
            <ContextPanel />
        </div>
    );
}
