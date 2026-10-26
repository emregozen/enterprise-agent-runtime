import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { App } from "./App";
import "@fontsource-variable/inter";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "./index.css";

const stored = localStorage.getItem("theme");
const theme = new URLSearchParams(window.location.search).get("theme");
const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
const dark = theme === "dark" || (theme !== "light" && (stored === "dark" || (stored !== "light" && prefersDark)));
document.documentElement.classList.toggle("dark", dark);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
