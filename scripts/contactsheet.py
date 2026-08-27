"""Tile a directory of screenshots into one labelled contact sheet.

Reviewing a dozen separate PNGs costs a dozen round trips; one sheet costs one.

    python scripts/contactsheet.py gui-shots/ -o sheet.png
    python scripts/contactsheet.py gui-shots/ --cols 3 --width 520

With --baseline, each shot is placed next to the same-named file from another
directory and pixel differences are boxed in red, which is how you see what a
change actually moved:

    python scripts/contactsheet.py gui-shots/ --baseline gui-shots-main/ -o diff.png
"""

import argparse
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

BG = (250, 250, 250)
LABEL_BG = (32, 34, 38)
LABEL_FG = (245, 245, 245)
DIFF_BOX = (220, 40, 40)
PAD = 12
LABEL_H = 22


def _font(size=13):
    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ):
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def _scaled(path, width):
    image = Image.open(path).convert("RGB")
    if image.width <= width:
        return image
    height = round(image.height * width / image.width)
    return image.resize((width, height), Image.LANCZOS)


def _diff_boxes(image, baseline_path, width):
    """Return the image with changed regions outlined, plus a changed-pixel count."""
    baseline = _scaled(baseline_path, width)
    if baseline.size != image.size:
        annotated = image.copy()
        ImageDraw.Draw(annotated).rectangle(
            [(0, 0), (image.width - 1, image.height - 1)], outline=DIFF_BOX, width=3
        )
        return annotated, -1

    diff = ImageChops.difference(image, baseline).convert("L")
    mask = diff.point(lambda v: 255 if v > 12 else 0)
    bbox = mask.getbbox()
    histogram = mask.histogram()
    changed = sum(histogram[1:])
    annotated = image.copy()
    if bbox:
        ImageDraw.Draw(annotated).rectangle(bbox, outline=DIFF_BOX, width=2)
    return annotated, changed


def build(shot_dir, out_path, cols=3, width=460, baseline_dir=None):
    shots = sorted(Path(shot_dir).rglob("*.png"))
    if not shots:
        raise SystemExit(f"No PNGs under {shot_dir}")

    font = _font()
    tiles = []
    for shot in shots:
        image = _scaled(shot, width)
        label = str(shot.relative_to(shot_dir))
        if baseline_dir:
            candidate = Path(baseline_dir) / shot.relative_to(shot_dir)
            if candidate.exists():
                image, changed = _diff_boxes(image, candidate, width)
                label += "  [size differs]" if changed < 0 else f"  [{changed} px changed]"
            else:
                label += "  [new]"
        tiles.append((label, image))

    cell_w = width + PAD
    cell_h = max(img.height for _, img in tiles) + LABEL_H + PAD
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell_w + PAD, rows * cell_h + PAD), BG)
    draw = ImageDraw.Draw(sheet)

    for index, (label, image) in enumerate(tiles):
        col, row = index % cols, index // cols
        x = PAD + col * cell_w
        y = PAD + row * cell_h
        draw.rectangle([(x, y), (x + width - 1, y + LABEL_H - 1)], fill=LABEL_BG)
        draw.text((x + 6, y + 4), label, fill=LABEL_FG, font=font)
        sheet.paste(image, (x, y + LABEL_H))
        draw.rectangle(
            [(x, y), (x + width - 1, y + LABEL_H + image.height - 1)],
            outline=(200, 200, 200),
        )

    sheet.save(out_path)
    print(f"{out_path}  ({sheet.width}x{sheet.height}, {len(tiles)} shots)")
    return out_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("shot_dir")
    parser.add_argument("-o", "--out", default="contact-sheet.png")
    parser.add_argument("--cols", type=int, default=3)
    parser.add_argument("--width", type=int, default=460, help="Per-tile width in px")
    parser.add_argument("--baseline", default=None, help="Directory to diff against")
    args = parser.parse_args()
    build(args.shot_dir, args.out, args.cols, args.width, args.baseline)


if __name__ == "__main__":
    main()
