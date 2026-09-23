"""Split each living cut-paper Momo into kraft back / blue body / white+grey top layers.

Same recipe as the Dillon Brain split: HSV band masks, median/close cleanup,
and a full-silhouette kraft backing so a lifted layer never reveals a hole.

    python scripts/split-momo-layers.py <cut-png-dir> public/momentum/momos-living
"""

import pathlib
import sys

from PIL import Image, ImageChops, ImageFilter

WORK, FINAL = 640, 320


def band(ch, lo, hi):
    return ch.point(lambda x: 255 if lo <= x <= hi else 0)


def clean(mask, open_px=5, close_px=5):
    m = mask.filter(ImageFilter.MedianFilter(open_px))
    return m.filter(ImageFilter.MaxFilter(close_px)).filter(ImageFilter.MinFilter(close_px))


def square(im, side):
    im = im.copy()
    im.thumbnail((side, side), Image.LANCZOS)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.alpha_composite(im, ((side - im.width) // 2, (side - im.height) // 2))
    return canvas


def split(path, out):
    src = square(Image.open(path).convert("RGBA"), WORK)
    alpha = src.getchannel("A")
    solid = alpha.point(lambda a: 255 if a > 128 else 0)
    # The deckled rim belongs to the kraft back: nothing above it reaches the outer 6px.
    inner = solid.filter(ImageFilter.MinFilter(13))
    h_, s_, v_ = src.convert("RGB").convert("HSV").split()

    # Top: unsaturated paper, i.e. white eyes, grey hardware and tools, dark pupils.
    # A 7px median drops the thin pale highlight rims that are not separate paper.
    top_m = ImageChops.multiply(clean(band(s_, 0, 58), 7, 5), inner)
    # Gold antenna ball: warm and saturated, rides with the hardware.
    gold = ImageChops.multiply(
        ImageChops.multiply(band(h_, 18, 45), band(s_, 110, 255)), band(v_, 120, 255)
    )
    top_m = ImageChops.lighter(top_m, ImageChops.multiply(clean(gold, 3, 3), inner))
    # Kraft backing: warm, moderately saturated.
    kraft_m = ImageChops.multiply(
        ImageChops.multiply(band(h_, 8, 42), band(s_, 35, 150)), band(v_, 100, 255)
    )
    kraft_m = ImageChops.subtract(clean(kraft_m, 3, 3), top_m)

    top = src.copy()
    top.putalpha(top_m.filter(ImageFilter.GaussianBlur(0.7)))

    # Body keeps everything but kraft; under the top pieces it darkens: the shadow of a lifted strip.
    body = src.copy()
    shade = ImageChops.multiply(src, Image.new("RGBA", src.size, (120, 130, 150, 255)))
    body.paste(shade, (0, 0), top_m.filter(ImageFilter.MaxFilter(3)))
    body_m = ImageChops.darker(ImageChops.subtract(alpha, kraft_m), inner)
    body.putalpha(body_m.filter(ImageFilter.GaussianBlur(0.6)))

    # Full silhouette in kraft so a lifted layer never shows a hole.
    back = Image.new("RGBA", src.size, (205, 182, 145, 255))
    back.putalpha(alpha)
    # Kraft pixels, plus the rim and thin parts (antenna stems) the eroded layers above leave out.
    keep = ImageChops.lighter(kraft_m, ImageChops.subtract(solid, inner))
    back.alpha_composite(Image.composite(src, Image.new("RGBA", src.size, (0, 0, 0, 0)), keep))

    out.mkdir(parents=True, exist_ok=True)
    size = 0
    for name, im in (("back", back), ("body", body), ("top", top), ("flat", src)):
        target = out / f"{name}.webp"
        im.resize((FINAL, FINAL), Image.LANCZOS).save(target, "WEBP", quality=82, method=6)
        size += target.stat().st_size
    return size


if __name__ == "__main__":
    src_dir, out_dir = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
    total = 0
    for png in sorted(src_dir.glob("*.png")):
        size = split(png, out_dir / png.stem)
        total += size
        print(png.stem, size // 1024, "KB")
    print("total", total // 1024, "KB")
