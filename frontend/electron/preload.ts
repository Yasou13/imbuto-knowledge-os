// Electron preload script
// Runs in a sandboxed renderer context before the page loads.
// Use this to expose safe APIs to the renderer via contextBridge.

import { contextBridge, ipcRenderer } from "electron";

const apiUrlArg = process.argv.find((arg) => arg.startsWith("--api-url="));
const apiUrl = apiUrlArg ? apiUrlArg.split("=")[1] : undefined;

const tokenArg = process.argv.find((arg) => arg.startsWith("--internal-token="));
const internalToken = tokenArg ? tokenArg.split("=")[1] : undefined;

contextBridge.exposeInMainWorld("imbuto", {
    platform: process.platform,
    apiUrl: apiUrl,
    internalToken: internalToken,
});

contextBridge.exposeInMainWorld("electron", {
    openSettings: () => ipcRenderer.send("open-settings"),
    showNotification: (title: string, body: string) => ipcRenderer.send("show-notification", title, body),
});
