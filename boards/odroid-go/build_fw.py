from pathlib import Path
import csv
import shutil
import subprocess

from SCons.Script import Import

Import("env")
pio_env = env


def _project_option(name, default=""):
    return pio_env.GetProjectOption(name, default=default)


def _run(cmd, cwd=None):
    print("[odroid_go_fw]", " ".join(str(c) for c in cmd))
    return subprocess.run(cmd, cwd=cwd, check=False)


def _partition_size(project_dir, board_config):
    part_csv_name = board_config.get("build.partitions") or _project_option(
        "board_build.partitions", ""
    )
    if not part_csv_name:
        return None

    part_csv = project_dir / part_csv_name
    if not part_csv.exists():
        return None

    with open(part_csv, newline="") as f:
        for row in csv.reader(f):
            if not row or row[0].strip().startswith("#"):
                continue
            cols = [c.strip() for c in row]
            if len(cols) < 5:
                continue
            name, ptype, subtype, _offset, size = cols[:5]
            if ptype == "app" and subtype == "ota_0":
                return int(size, 0)
    return None


def _odroid_go_data_partition_size(app_size):
    # The ODROID-GO factory updater places firmware entries immediately after
    # its 0x10000..0x100000 factory partition and rejects entries past 16 MB.
    odroid_go_app_start = 0x100000
    flash_size = 0x1000000
    data_size = flash_size - odroid_go_app_start - app_size
    if data_size <= 0:
        raise RuntimeError("ODROID-GO app partition leaves no room for data partition")
    return data_size


def _prepare_mkfw(project_dir, mkfw_dir):
    mkfw = mkfw_dir / "mkfw"
    if not mkfw.exists():
        repo = _project_option(
            "custom_odroid_go_mkfw_repo",
            "https://github.com/othercrashoverride/odroid-go-firmware.git",
        )
        ref = _project_option("custom_odroid_go_mkfw_ref", "factory")
        clone_dir = mkfw_dir.parents[1]

        if not clone_dir.exists():
            clone_dir.parent.mkdir(parents=True, exist_ok=True)
            rc = _run(
                [
                    "git",
                    "clone",
                    "--depth",
                    "1",
                    "--branch",
                    ref,
                    repo,
                    str(clone_dir),
                ],
                cwd=project_dir,
            )
            if rc.returncode != 0:
                raise RuntimeError("failed to clone ODROID-GO mkfw source")

        if not mkfw_dir.exists():
            raise RuntimeError(f"mkfw source directory not found: {mkfw_dir}")

    rc = _run(["make"], cwd=mkfw_dir)
    if rc.returncode != 0:
        raise RuntimeError("failed to build mkfw")

    if not mkfw.exists():
        raise RuntimeError(f"mkfw executable not found: {mkfw}")

    return mkfw


def _prepare_tile(project_dir, build_dir):
    raw_opt = _project_option("custom_odroid_go_tile_raw", "")
    if raw_opt:
        tile_raw = project_dir / raw_opt
        if not tile_raw.exists():
            raise RuntimeError(f"configured ODROID-GO raw tile not found: {tile_raw}")
        if tile_raw.stat().st_size != 86 * 48 * 2:
            raise RuntimeError(f"ODROID-GO raw tile has invalid size: {tile_raw}")
        return tile_raw

    tile_png = project_dir / _project_option(
        "custom_odroid_go_tile_png", "media/pictures/bruce_hd.png"
    )
    if not tile_png.exists():
        raise RuntimeError(f"configured ODROID-GO tile image not found: {tile_png}")

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError(
            "ffmpeg is required to generate the ODROID-GO RGB565 tile. "
            "Install it or set custom_odroid_go_tile_raw to an existing 86x48 rgb565 file."
        )

    tile_raw = build_dir / "odroid-go-tile.raw"
    vf = (
        "scale=86:48:force_original_aspect_ratio=decrease,"
        "pad=86:48:(ow-iw)/2:(oh-ih)/2:color=black"
    )
    rc = _run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(tile_png),
            "-vf",
            vf,
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb565",
            str(tile_raw),
        ],
        cwd=project_dir,
    )
    if rc.returncode != 0:
        raise RuntimeError("failed to generate ODROID-GO RGB565 tile")

    if tile_raw.stat().st_size != 86 * 48 * 2:
        raise RuntimeError(f"generated ODROID-GO raw tile has invalid size: {tile_raw}")

    return tile_raw


def _build_fw_callback(target, source, env):
    if str(_project_option("custom_odroid_go_fw_enabled", "yes")).lower() in (
        "0",
        "false",
        "no",
    ):
        return

    project_dir = Path(env.subst("$PROJECT_DIR"))
    build_dir = Path(env.subst("$BUILD_DIR"))
    app_bin = build_dir / "firmware.bin"
    if not app_bin.exists():
        raise RuntimeError(f"application binary not found: {app_bin}")

    mkfw_dir = project_dir / _project_option(
        "custom_odroid_go_mkfw_dir", ".pio/odroid-go-firmware/tools/mkfw"
    )
    mkfw = _prepare_mkfw(project_dir, mkfw_dir)
    tile_raw = _prepare_tile(project_dir, build_dir)

    part_size = _partition_size(project_dir, env.BoardConfig())
    if part_size is None:
        raise RuntimeError("could not determine ODROID-GO app partition size")
    data_size = _odroid_go_data_partition_size(part_size)
    empty_data = build_dir / "odroid-go-empty-data.bin"
    empty_data.touch()

    description = _project_option("custom_odroid_go_fw_description", "Bruce")
    out_name = _project_option("custom_odroid_go_fw_name", "Bruce-odroid-go.fw")
    out_fw = project_dir / out_name
    temporary_fw = build_dir / "firmware.fw"
    if temporary_fw.exists():
        temporary_fw.unlink()

    rc = _run(
        [
            str(mkfw),
            description,
            str(tile_raw),
            "0",
            "16",
            str(part_size),
            "app",
            str(app_bin),
            "1",
            "130",
            str(data_size),
            "spiffs",
            str(empty_data),
        ],
        cwd=build_dir,
    )
    if rc.returncode != 0:
        raise RuntimeError("mkfw failed")

    if not temporary_fw.exists():
        raise RuntimeError(f"mkfw did not produce {temporary_fw}")

    shutil.copy2(temporary_fw, out_fw)
    print(f"[odroid_go_fw] Success -> {out_fw} ({out_fw.stat().st_size} bytes)")


app_bin = Path(pio_env.subst("$BUILD_DIR")) / "firmware.bin"
pio_env.AddPostAction(str(app_bin), _build_fw_callback)
