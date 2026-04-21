import { create } from "zustand";

export const MODELS = [
    "groq/llama-3.3-70b-versatile",
    "groq/llama-3.1-8b-instant",
    "gemini/gemini-1.5-flash-latest",
    "anthropic/claude-3-5-sonnet-20240620",
    "openai/gpt-4o",
];

interface ModelState {
    selectedModel: string;
    setSelectedModel: (model: string) => void;
}

export const useModelStore = create<ModelState>((set) => ({
    selectedModel: localStorage.getItem("imbuto:selected-model") || MODELS[0],
    setSelectedModel: (model) => {
        localStorage.setItem("imbuto:selected-model", model);
        set({ selectedModel: model });
    }
}));
