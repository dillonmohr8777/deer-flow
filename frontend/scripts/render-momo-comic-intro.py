"""Render the thirty original paper-comic plates as a quiet looping backdrop.

The stills are kept as individual web-sized deliverables. This script only
animates camera position and dissolves; it never alters their source files.
"""

from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]
PLATES = ROOT / "public/momentum/intro-comic/plates"
FILMS = ROOT / "public/momentum/films"
NAME = "momo-comic-intro-20260925"
FPS = 30
FRAMES_PER_PLATE = 22
DISSOLVE = 0.2


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def main() -> None:
    plates = [PLATES / f"plate-{i:02d}.webp" for i in range(1, 31)]
    missing = [str(path) for path in plates if not path.is_file()]
    if missing:
        raise SystemExit(f"Missing plates: {', '.join(missing)}")

    # Repeating the opening plate at the end makes the loop join at the same
    # composition; the repeat is not counted as a thirty-first source image.
    sequence = [*plates, plates[0]]
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    for plate in sequence:
        command.extend(["-i", str(plate)])

    filters = []
    for index in range(len(sequence)):
        filters.append(
            f"[{index}:v]"
            "zoompan=z='min(zoom+0.002,1.04)':"
            "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={FRAMES_PER_PLATE}:s=960x540:fps={FPS},"
            f"format=yuv420p[v{index}]"
        )

    duration = FRAMES_PER_PLATE / FPS
    step = duration - DISSOLVE
    previous = "v0"
    for index in range(1, len(sequence)):
        output = "film" if index == len(sequence) - 1 else f"mix{index}"
        filters.append(
            f"[{previous}][v{index}]xfade=transition=fade:"
            f"duration={DISSOLVE}:offset={index * step:.6f}[{output}]"
        )
        previous = output

    mp4 = FILMS / f"{NAME}.mp4"
    webm = FILMS / f"{NAME}.webm"
    poster = FILMS / f"{NAME}.webp"
    command.extend(
        [
            "-filter_complex", ";".join(filters),
            "-map", "[film]", "-an", "-c:v", "libx264", "-preset", "medium",
            "-crf", "26", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            str(mp4),
        ]
    )
    run(command)
    run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(mp4), "-an", "-c:v", "libvpx-vp9", "-b:v", "0",
            "-crf", "38", "-row-mt", "1", str(webm),
        ]
    )
    shutil.copyfile(plates[0], poster)
    print(f"Rendered {len(plates)} plates: {mp4}, {webm}, {poster}")


if __name__ == "__main__":
    main()
