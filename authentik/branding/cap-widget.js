// Loaded in authentik's CAPTCHA iframe as well as its provider-discovery context.
// Keep the original widget and verification protocol; only customize presentation.
// A static dependency must register the provider before authentik's load handler.
// Top-level await can let the script load event run before registration finishes.
import "https://cap.pmh.codes/assets/widget.js";

if (window.frameElement?.id === "ak-captcha") {
    const style = document.createElement("style");
    style.textContent = `
        :root { color-scheme: dark; }
        html, body { margin: 0; padding: 0; overflow: hidden; }
        .cap-container {
            box-sizing: border-box;
            width: 100%;
            padding: 8px 0;
        }
        cap-widget {
            display: block;
            width: min(260px, 100%);
            --cap-widget-width: 100%;
            --cap-background: #191a1e;
            --cap-color: #f1f1f6;
            --cap-border-color: #303644;
            --cap-checkbox-background: #12151d;
            --cap-checkbox-border: 1px solid #596171;
            --cap-spinner-color: #e6e7eb;
            --cap-spinner-background-color: #303644;
        }
    `;
    document.head.appendChild(style);
    // The outer iframe otherwise combines width:100% with a default border.
    Object.assign(window.frameElement.style, {
        boxSizing: "border-box",
        border: "0",
        display: "block",
        maxWidth: "100%",
    });
}
