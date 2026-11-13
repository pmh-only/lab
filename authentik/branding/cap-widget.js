// Appended to the checksum-verified upstream widget by the server init container.
// authentik 2026.8 loads this as a module in the parent but a classic script in
// its CAPTCHA iframe: this bundle must work in both, with no imports or await.

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
    const container = document.getElementById("ak-container");
    if (container) {
        const resize = () => {
            window.frameElement.style.height =
                `${Math.ceil(container.getBoundingClientRect().height)}px`;
        };
        new ResizeObserver(resize).observe(container);
        requestAnimationFrame(resize);
    }
}
