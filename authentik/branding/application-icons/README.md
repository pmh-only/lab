# Application icons

All assets have an 80×80 canvas with a centered 52×52 content area. Original
artwork keeps its aspect ratio and colors; dark artwork gets a neutral light
background instead of being recolored. No invented colored app tiles are used.

- Service logos: [Homarr Dashboard Icons](https://github.com/homarr-labs/dashboard-icons).
- Books and Mail: each application's existing Apple touch icon.
- Apps without published logos: [Lucide](https://lucide.dev/) 0.468.0 symbols,
  with a dark stroke on a light background for visibility in both themes.

`python authentik/branding/application-icons/generate.py` refreshes the checked-in
SVG snapshots. Each SVG embeds its artwork, including any raster favicon; the
dashboard does not depend on nested external image requests. Artwork remains
subject to its original project's license and trademarks.
