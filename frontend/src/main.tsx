import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
// Inter is bundled locally rather than pulled from Google Fonts, so the app
// renders identically with no internet access (and leaks no referrer).
import "@fontsource/inter/300.css";
import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";
import "@fontsource/inter/700.css";
import "@fontsource/inter/800.css";
import App from "./App";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
