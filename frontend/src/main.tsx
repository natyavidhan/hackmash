import "@fontsource-variable/archivo/wdth.css";
import "@fontsource/kalam/latin-400.css";
import "./styles/base.css";
import "./styles/layout.css";
import "./styles/board.css";
import "./styles/notice.css";
import "./styles/sheet.css";
import "./styles/tracker.css";
import "./styles/pages.css";
import "./styles/mobile.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
