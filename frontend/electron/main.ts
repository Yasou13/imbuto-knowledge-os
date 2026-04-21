import { app, BrowserWindow, ipcMain, Notification, dialog } from "electron";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawn, ChildProcess } from 'child_process';
import crypto from "node:crypto";
let pythonProcess: ChildProcess | null = null;
const internalToken = crypto.randomUUID();

/* ── ESM path resolution ───────────────────────────────────────────── */

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

/* ── Paths ─────────────────────────────────────────────────────────── */

const VITE_DEV_SERVER_URL = process.env["VITE_DEV_SERVER_URL"];
const RENDERER_DIST = path.join(__dirname, "../dist");

/* ── Window factory ────────────────────────────────────────────────── */

function createWindow() {
    const win = new BrowserWindow({
        width: 1400,
        height: 900,
        minWidth: 1024,
        minHeight: 640,
        title: "IMBUTO",
        backgroundColor: "#0f1117",
        webPreferences: {
            preload: path.join(__dirname, 'preload.mjs'),
            nodeIntegration: false,
            contextIsolation: true,
        },
    });

    if (VITE_DEV_SERVER_URL) {
        win.loadURL(VITE_DEV_SERVER_URL);
    } else {
        win.loadFile(path.join(RENDERER_DIST, "index.html"));
    }
}

/* ── App lifecycle ─────────────────────────────────────────────────── */

async function waitForBackend(url: string, maxAttempts = 240, intervalMs = 500): Promise<boolean> {
    for (let i = 0; i < maxAttempts; i++) {
        if (i > 0 && i % 10 === 0) {
            console.log(`[Electron] Still waiting for backend to load AI models... (Attempt ${i}/${maxAttempts})`);
        }
        try {
            const res = await fetch(url);
            if (res.status === 200) {
                return true;
            }
        } catch (e) {
            // Error connecting, retry
        }
        await new Promise(resolve => setTimeout(resolve, intervalMs));
    }
    return false;
}

app.whenReady().then(async () => {
    const isProd = app.isPackaged;
    const pythonExecutable = isProd
        ? path.join(process.resourcesPath, 'imbuto_backend', 'imbuto_backend')
        : path.join(__dirname, '..', '..', 'venv', 'bin', 'python');

    const spawnArgs = isProd ? [] : ["-m", "personal_os.server"];
    const projectRoot = path.join(__dirname, '..', '..');

    try {
        pythonProcess = spawn(pythonExecutable, spawnArgs, {
            cwd: projectRoot,
            env: { ...process.env, IMBUTO_INTERNAL_TOKEN: internalToken }
        });
        pythonProcess.stdout?.on('data', (data) => console.log(`[FastAPI]: ${data.toString()}`));
        pythonProcess.stderr?.on('data', (data) => console.error(`[FastAPI Error]: ${data.toString()}`));
    } catch (error) {
        console.error("Failed to spawn Python backend:", error);
    }

    ipcMain.on('open-settings', () => {
        console.log("Opening settings UI...");
    });

    ipcMain.on('show-notification', (_, title, body) => {
        new Notification({ title, body }).show();
    });

    ipcMain.on('get-env', (event) => {
        event.returnValue = {
            apiUrl: process.env.API_URL || "",
            internalToken: internalToken
        };
    });

    const isBackendReady = await waitForBackend("http://127.0.0.1:8000/health");
    if (!isBackendReady) {
        dialog.showErrorBox('Startup Error', 'The knowledge engine backend failed to start. Please check the logs or your antivirus.');
        app.quit();
        return;
    }

    createWindow();

    app.on("activate", () => {
        if (BrowserWindow.getAllWindows().length === 0) {
            createWindow();
        }
    });
});

app.on('will-quit', () => {
    if (pythonProcess) {
        console.log("Terminating Python backend...");
        pythonProcess.kill();
    }
});

app.on("window-all-closed", () => {
    if (process.platform !== "darwin") {
        app.quit();
    }
});
