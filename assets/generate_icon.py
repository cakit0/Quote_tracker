"""
Generate the application icon.

Design: a rounded square in HAWE dark with a red header bar, holding three
descending white bars (falling / compared prices) and a red price-tag dot.
It reads as "price tracking" and stays legible at 16 px, where fine detail
disappears - so the small sizes are drawn with simplified geometry rather than
by downscaling the large one.

    python assets/generate_icon.py

Writes assets/icon.ico (multi-resolution) and assets/icon.png (512 px).
"""

from pathlib import Path

from PIL import Image, ImageDraw

RED = (226, 0, 26, 255)        # HAWE red  #E2001A
DARK = (26, 26, 26, 255)       # HAWE dark #1A1A1A
WHITE = (255, 255, 255, 255)
GREEN = (26, 122, 60, 255)     # best-price accent

OUT_DIR = Path(__file__).resolve().parent
SIZES = [16, 24, 32, 48, 64, 128, 256]


def draw_icon(size: int) -> Image.Image:
    """Draw the icon at ``size`` px.

    Everything is expressed as a fraction of ``size`` so each resolution is
    drawn natively (crisp edges) instead of being resampled.
    """
    # Supersample for smooth curves, except at tiny sizes where the extra
    # detail just turns to mush.
    ss = 4 if size >= 32 else 8
    s = size * ss
    pad = s * 0.05
    radius = s * 0.22

    # Body: build the rounded square as a mask, then paint the dark body and
    # the red header band *through* it.  Compositing this way avoids the
    # hairline seam you get from overlapping two rounded rectangles.
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [pad, pad, s - pad, s - pad], radius=radius, fill=255)

    body = Image.new("RGBA", (s, s), DARK)
    band_h = s * 0.22
    ImageDraw.Draw(body).rectangle([0, 0, s, pad + band_h], fill=RED)

    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    img.paste(body, (0, 0), mask)
    d = ImageDraw.Draw(img)

    # Three descending bars = comparing prices across suppliers.
    base_y = s - s * 0.20          # bars sit on this line
    bar_w = s * 0.15
    gap = s * 0.075
    total = bar_w * 3 + gap * 2
    x0 = (s - total) / 2
    heights = [0.42, 0.30, 0.20]   # tall -> short (falling price)
    for i, hf in enumerate(heights):
        x = x0 + i * (bar_w + gap)
        top = base_y - s * hf
        # The cheapest (last) bar is green: the "best price" the app finds.
        fill = GREEN if i == len(heights) - 1 else WHITE
        r = min(bar_w * 0.28, (base_y - top) * 0.45)
        d.rounded_rectangle([x, top, x + bar_w, base_y], radius=r, fill=fill)

    # Baseline under the bars.
    line_y = base_y + s * 0.035
    d.rounded_rectangle([x0 - s * 0.03, line_y,
                         x0 + total + s * 0.03, line_y + s * 0.022],
                        radius=s * 0.011, fill=WHITE)

    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    images = [draw_icon(sz) for sz in SIZES]
    ico_path = OUT_DIR / "icon.ico"
    # Pillow writes every supplied size into the .ico container.
    images[-1].save(ico_path, format="ICO",
                    sizes=[(sz, sz) for sz in SIZES])
    png = draw_icon(512)
    png.save(OUT_DIR / "icon.png", format="PNG")
    print(f"wrote {ico_path} ({', '.join(str(s) for s in SIZES)} px)")
    print(f"wrote {OUT_DIR / 'icon.png'} (512 px)")


if __name__ == "__main__":
    main()
