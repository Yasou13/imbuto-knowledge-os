// Electron preload script
// Runs in a sandboxed renderer context before the page loads.
// Use this to expose safe APIs to the renderer via contextBridge.

import { contextBridge, ipcRenderer } from "electron";

const env = ipcRenderer.sendSync('get-env');

contextBridge.exposeInMainWorld("imbuto", {
    platform: process.platform,
    apiUrl: env.apiUrl,
    internalToken: env.internalToken,
});

contextBridge.exposeInMainWorld("electron", {
    openSettings: () => ipcRenderer.send("open-settings"),
    showNotification: (title: string, body: string) => ipcRenderer.send("show-notification", title, body),
});
