import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { App } from "./App";
import "./index.css";

const stored = localStorage.getItem("theme");
const theme = new URLSearchParams(window.location.search).get("theme");
if (theme === "dark" || (theme !== "light" && stored === "dark")) document.documentElement.classList.add("dark");

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
