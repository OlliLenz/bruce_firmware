import hashlib
from typing import TYPE_CHECKING, Any
import requests

if TYPE_CHECKING:
    Import: Any = None
    env: Any = {}

import glob
import gzip
from os import makedirs, remove, rename
from os.path import basename, dirname, exists, isfile, join
from shutil import copy2

Import("env")  # type: ignore

FRAMEWORK_DIR = env.PioPlatform().get_package_dir("framework-arduinoespressif32-libs")
board_mcu = env.BoardConfig()
mcu = board_mcu.get("build.mcu", "")
patchflag_path = join(FRAMEWORK_DIR,mcu, "lib", ".patched")
python_exe = env.get("PYTHONEXE", "python")

# patch file only if we didn't do it befored
if not isfile(join(FRAMEWORK_DIR,mcu, "lib", ".patched")):
    original_file = join(FRAMEWORK_DIR,mcu, "lib", "libnet80211.a")
    patched_file = join(
        FRAMEWORK_DIR, mcu, "lib", "libnet80211.a.patched"
    )

    if not isfile(original_file) and isfile("%s.old" % (original_file)):
        copy2("%s.old" % (original_file), original_file)

    patch_rc = 0
    if mcu=="esp32c5" or mcu=="esp32c6" :
        patch_rc = env.Execute(
            '"%s" -m platformio pkg exec -p toolchain-riscv32-esp-elf -- riscv32-esp-elf-objcopy --weaken-symbol=ieee80211_raw_frame_sanity_check %s %s'
            % (python_exe, original_file, patched_file)
        )
    elif mcu=="esp32p4":
        patch_rc = 1
    else:
        patch_rc = env.Execute(
            '"%s" -m platformio pkg exec -p toolchain-xtensa-esp-elf -- xtensa-esp-elf-objcopy --weaken-symbol=ieee80211_raw_frame_sanity_check %s %s'
            % (python_exe, original_file, patched_file)
        )

    if patch_rc == 0 and isfile(patched_file):
        if isfile("%s.old" % (original_file)):
            remove("%s.old" % (original_file))
        if isfile(original_file):
            rename(original_file, "%s.old" % (original_file))
        else:
            print("Patch: Original file not found")
        rename(patched_file, original_file)
    else:
        print("Patch: libnet80211 patch skipped; keeping original archive")


    def _touch(path):
        with open(path, "w") as fp:
            fp.write("")

    env.Execute(lambda *args, **kwargs: _touch(patchflag_path))


def hash_file(file_path):
    """Generate SHA-256 hash for a single file."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        # Read the file in chunks to avoid memory issues
        for chunk in iter(lambda: f.read(4096), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def hash_files(file_paths):
    """Generate a combined hash for multiple files."""
    combined_hash = hashlib.sha256()

    for file_path in file_paths:
        file_hash = hash_file(file_path)
        combined_hash.update(file_hash.encode("utf-8"))  # Update with the file's hash

    return combined_hash.hexdigest()


def save_checksum_file(hash_value, output_file):
    """Save the hash value to a specified output file."""
    with open(output_file, "w") as f:
        f.write(hash_value)


def load_checksum_file(input_file):
    """Load the hash value from a specified input file."""
    with open(input_file, "r") as f:
        return f.readline().strip()


def minify_remote(src, url, label):
    original = src.read()
    try:
        minify_req = requests.post(
            url,
            {"input": original.decode("utf-8")},
            timeout=10,
        )
        minify_req.raise_for_status()
        return minify_req.text.encode("utf-8")
    except requests.RequestException as e:
        print(f"[GZIP & EMBED INTO HEADER] - {label} minifier unavailable, using original: {e}")
        return original


def minify_css(c):
    return minify_remote(c, "https://www.toptal.com/developers/cssminifier/api/raw", "CSS")


def minify_js(js):
    return minify_remote(js, "https://www.toptal.com/developers/javascript-minifier/api/raw", "JS")


def minify_html(html):
    return minify_remote(html, "https://www.toptal.com/developers/html-minifier/api/raw", "HTML")


# gzip web files
def prepare_www_files():
    HEADER_FILE = join(env.get("PROJECT_DIR"), "include", "webFiles.h")
    filetypes_to_gzip = ["html", "css", "js"]
    data_src_dir = join(env.get("PROJECT_DIR"), "embedded_resources/web_interface")
    checksum_file = join(data_src_dir, "checksum.sha256")
    checksum = ""

    if not exists(data_src_dir):
        print(f'Error: Source directory "{data_src_dir}" does not exist!')
        return

    if exists(checksum_file):
        checksum = load_checksum_file(checksum_file)

    files_to_gzip = []
    for extension in filetypes_to_gzip:
        files_to_gzip.extend(glob.glob(join(data_src_dir, "*." + extension)))

    files_checksum = hash_files(files_to_gzip)
    if files_checksum == checksum:
        print("[GZIP & EMBED INTO HEADER] - Nothing to process.")
        return

    print(f"[GZIP & EMBED INTO HEADER] - Processing {len(files_to_gzip)} files.")

    makedirs(dirname(HEADER_FILE), exist_ok=True)

    with open(HEADER_FILE, "w") as header:
        header.write(
            "#ifndef WEB_FILES_H\n#define WEB_FILES_H\n\n#include <Arduino.h>\n\n"
        )
        header.write(
            "// THIS FILE IS AUTOGENERATED DO NOT MODIFY IT. MODIFY FILES IN /embedded_resources/web_interface\n\n"
        )

        for file in files_to_gzip:
            gz_file = file + ".gz"
            with open(file, "rb") as src, gzip.open(gz_file, "wb") as dst:
                ext = basename(file).rsplit(".", 1)[-1].lower()
                if ext == 'html':
                    minified = minify_html(src)
                elif ext == 'css':
                    minified = minify_css(src)
                elif ext == 'js':
                    minified = minify_js(src)
                else:
                    raise ValueError(f"Unsupported file type: {ext}")

                # # Output minified file
                # min_file = file + ".min"
                # with open(min_file, "wb") as minf:
                #     minf.write(minified)

                dst.write(minified)

            with open(gz_file, "rb") as gz:
                compressed_data = gz.read()
                var_name = basename(file).replace(".", "_")

                header.write(f"const uint8_t {var_name}[] PROGMEM = {{\n")

                # Write hex values, inserting a newline every 15 bytes
                for i in range(0, len(compressed_data), 15):
                    hex_chunk = ", ".join(
                        f"0x{byte:02X}" for byte in compressed_data[i : i + 15]
                    )
                    header.write(f"  {hex_chunk},\n")

                header.write("};\n\n")
                header.write(
                    f"const uint32_t {var_name}_size = {len(compressed_data)};\n\n"
                )

            remove(gz_file)  # Clean up temporary gzip file

        header.write("#endif // WEB_FILES_H\n")

    save_checksum_file(files_checksum, checksum_file)

    print(f"[DONE] Gzipped files embedded into {HEADER_FILE}")


prepare_www_files()
