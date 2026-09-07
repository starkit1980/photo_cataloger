#!/usr/bin/env python3

import os
import sqlite3
from pathlib import Path
from PIL import Image, ExifTags
import time
import html
from collections import defaultdict
import json
import re
import argparse
import sys
from datetime import timedelta, datetime

__version__ = "0.1.0"
__author__ = "starkit"
__license__ = "MIT"

# -----------------------------
# CONFIG
# -----------------------------
BASE_DIR = Path(__file__).parent
CATALOG_DIR = BASE_DIR / "Catalog"
THUMB_DIR = CATALOG_DIR / ".thumbs"
DB_PATH = CATALOG_DIR / "basa.db"

EXTS = [".jpg", ".jpeg"]
ARCHIVE_EXTS = {".zip", ".rar", ".7z", ".tar", ".gz"}

CHUNK = 1000
THUMB_SIZE = (150, 150)

LOG_FILE = Path("debug.log")
VERBOSITY = False

def log(message: str) -> None:
    if VERBOSITY == False:
        return
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line)

# -----------------------------
# Prepare thumb directory
# -----------------------------
def prepare_tumb_dirs():
    CATALOG_DIR.mkdir(exist_ok=True)
    THUMB_DIR.mkdir(parents=True, exist_ok=True)
    for f in THUMB_DIR.glob("*.jpg"):
        f.unlink()

# -----------------------------
# Human readable size
# -----------------------------
def human_size(n):
    for unit in ("", "k", "M", "G", "T"):
        if n < 1024:
            return f"{n:.2f}{unit}"
        n /= 1024

# -----------------------------
# EXIF helpers
# -----------------------------
def extract_exif(path):
    EXIF_MAP = {v: k for k, v in ExifTags.TAGS.items()}
    try:
        img = Image.open(path)
        exif = img._getexif()
        if not exif:
            return {"datetime": "~empty", "camera": "~empty"}

        dt = exif.get(EXIF_MAP.get("DateTimeOriginal")) or exif.get(EXIF_MAP.get("DateTime"))
        make = exif.get(EXIF_MAP.get("Make"))
        model = exif.get(EXIF_MAP.get("Model"))

        clean_dt = re.sub(r'[\x00-\x1F]', '', dt)
        clean_make = re.sub(r'[\x00-\x1F]', '', make)
        clean_model = re.sub(r'[\x00-\x1F]', '', model)

        if clean_make == "" and clean_model == "":
            camera = "~empty"
        elif clean_make != "" and clean_model == "":
            camera = f"{clean_make} (Unknown)"
        elif clean_make == "" and clean_model != "":
            camera = f"Unknown ({clean_model})"
        else:
            camera = f"{clean_make} ({clean_model})"

        log(f"[INFO:extract_exif]: path: {path}, dt: {dt}, make: {make}, model: {model}, clean_dt: {clean_dt}, camera: {camera}")

        return {
            "datetime": clean_dt if clean_dt !="" else "~empty",
            "camera": camera
        }
    except:
        return {"datetime": "~empty", "camera": "~empty"}

# -----------------------------
# Thumbnail generator
# -----------------------------
def make_thumb(src_path, thumb_path):
    try:
        img = Image.open(src_path)
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGB")

        img.thumbnail(THUMB_SIZE)
        img.save(thumb_path, "JPEG")
        return thumb_path
    except:
        log(f"[ERROR:make_thumb]: Error while creating tumb for: '{src_path}'")
        return ""

# -----------------------------
# SQLite setup
# -----------------------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS photos (
            id INTEGER PRIMARY KEY,
            path TEXT,
            exif_datetime TEXT,
            file_datetime REAL,
            camera TEXT,
            size INTEGER,
            thumb_path TEXT
        )
    """)
    conn.commit()

    # CLEAN TABLEs
    cur.execute("DELETE FROM photos")
    conn.commit()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS archives (
            id INTEGER PRIMARY KEY,
            path TEXT,
            size INTEGER,
            ext TEXT,
            file_datetime REAL
        )
    """)
    conn.commit()

    cur.execute("DELETE FROM archives")
    conn.commit()

    return conn

# -----------------------------
# Insert archive to BD
# -----------------------------
def insert_archive(conn, path, size, ext, file_dt):
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO archives (path, size, ext, file_datetime)
        VALUES (?, ?, ?, ?)
    """, (str(path), size, ext, file_dt))
    conn.commit()

# -----------------------------
# Insert photo to BD
# -----------------------------
def insert_photo(conn, path, exif, file_dt, size, thumb_path):
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO photos (path, exif_datetime, file_datetime, camera, size, thumb_path)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        str(path),
        exif["datetime"] if exif else None,
        file_dt,
        exif["camera"] if exif else None,
        size,
        str(thumb_path)
    ))
    conn.commit()

# -----------------------------
# Trim file path
# -----------------------------
def short(path, n=30):
    path = str(path)
    return path if len(path) <= n else "..." + path[-n:]

# -----------------------------
# Count files in dir (recursively)
# -----------------------------
def count_files(root_dir):
    pict = 0
    overall = 0
    archs = 0
    print(f"Analysis...")
    for root, dirs, files in os.walk(root_dir):
        print(f"\rCurrent folder: '{short(root)}'", end="")
        overall += len(files)
        for name in files:
            if Path(name).suffix.lower() in EXTS:
                pict += 1
            if Path(name).suffix.lower() in ARCHIVE_EXTS:
                archs += 1
    print(f"\nTotal files in folder '{root_dir}' = {overall}")
    print(f"Pictures ({EXTS}) = {pict}")
    print(f"Archivies ({ARCHIVE_EXTS}) = {archs}")
    return pict, archs

# -----------------------------
# Show progress
# -----------------------------
def progress(current, total, short_curr_folder):
    percent = current * 100 // total
    bar = "#" * (percent // 2)
    bar = bar.ljust(50)
    print(f"\r[{bar}] {percent}% ({current}/{total})   {short_curr_folder}", end="")

# -----------------------------
# Scan disk
# -----------------------------
def scan_disk(root_dir):
    conn = init_db()

    # First count files
    pict_files, arch_files = count_files(root_dir)
    total_files = pict_files + arch_files
    current = 0
    current_arch = 0

    exts = set()
    arch_exts = set()
    pict_size = 0
    archives_size = 0

    print("Scan pictures and archives...")
    for root, dirs, files in os.walk(root_dir):
        for name in files:
            path = Path(root) / name
            ext = path.suffix.lower()

            # ARCHIVES
            if ext in ARCHIVE_EXTS:
                size = os.path.getsize(path)
                file_dt = os.path.getmtime(path)
                insert_archive(conn, path, size, ext, file_dt)
                current_arch += 1
                progress(current + current_arch, total_files, short(root))
                archives_size += size
                arch_exts.add(ext)
                continue

            if ext not in EXTS:
                continue

            exts.add(ext)
            size = os.path.getsize(path)
            pict_size += size

            file_dt = os.path.getmtime(path)
            exif = extract_exif(path)

            # thumbnail name = id-like number
            thumb_name = f"{current+1}.jpg"
            thumb_path = THUMB_DIR / thumb_name
            thumb_path = make_thumb(path, thumb_path)

            insert_photo(conn, path, exif, file_dt, size, thumb_path)

            current += 1
            progress(current + current_arch, total_files, short(root))

    print("")
    return pict_size, archives_size, pict_files, arch_files, sorted(exts), sorted(arch_exts)

# -----------------------------
# HTML helpers
# -----------------------------
CSS = """
<style>
    table { border-collapse: collapse; width: 100%; }
    td, th { border: 1px solid #ccc; padding: 5px; }
    th { background: #eee; }

    .thumb {
        max-width: 150px;
        max-height: 150px;
        width: 150px;
        height: auto;
        display: block;
    }
    .home {
        font-size: 18px;
        display: inline-block;
        margin-bottom: 15px;
    }

    .thumbbox {
        width: 150px;
        height: 150px;
        overflow: hidden;
        display: flex;
        align-items: center;
        justify-content: center;
    }

    .thumbf {
        width: 100%;
        height: 100%;
        object-fit: contain;
    }
</style>
"""

def write_html(path, content):
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

# -----------------------------
# Footer helper
# -----------------------------
def get_footer():
    return f"""
    <footer style="margin-top: 50px; border-top: 1px solid #ccc; color: #777; font-size: 12px; text-align: center;">
        <p>Catalog generated using Photo Cataloger v{__version__} | Created by: {__author__} | Licensed under: {__license__}</p>
    </footer>
    """

# -----------------------------
# Generate index.html
# -----------------------------
def generate_index(pict_size, archives_size, pict_files, arch_files, exts, arch_exts, root_folder):
    gen_time = datetime.now().strftime("%d-%m-%Y  %H:%M")
    html_content = f"""
    <html>
    <head>
        <meta charset="utf-8">
        <title>Photo Catalog</title>
        {CSS}
        <style>
            body {{ font-family: sans-serif; padding: 20px; }}
            a {{ display: block; margin: 10px 0; font-size: 20px; }}
        </style>
    </head>
    <body>
        <h1>Photo Catalog</h1>

        <p><b>Date of creation:</b> {gen_time}</p>
        <p><b>Root folder:</b> {root_folder}</p>
        <p><b>Files:</b> {pict_files + arch_files} (pictures: {pict_files}, archives: {arch_files})</p>
        <p><b>Overall size:</b> {human_size(archives_size + pict_size)} ({archives_size + pict_size} bytes)</p>
        <p><b>Overall pictures size:</b> {human_size(pict_size)} ({pict_size} bytes)</p>
        <p><b>Overall archives size:</b> {human_size(archives_size)} ({archives_size} bytes)</p>
        <p><b>Pictures:</b> {", ".join(exts)}</p>
        <p><b>Archives:</b> {", ".join(arch_exts)}</p>

        <hr>
        <h2>Pictures:</h2>
        <a href="file_data_sorted.html">List in ascending order of file date</a>
        <a href="exif_data_sorted.html">List of exif dates in ascending order</a>
        <a href="camera_sorted.html">List by camera</a>
        <a href="simple.html">A simple list</a>
        <a href="size_sorted.html">List in descending order of size</a>
        <hr>
        <h2>Archives:</h2>
        <a href="archives_by_path.html">Archives by path</a>
        <a href="archives.html">Archives by date</a>
        <a href="archives_by_size.html">Archives by size</a>
        <a href="archives_by_ext.html">Archives by extension</a>
        {get_footer()}
    </body>
    </html>
    """
    write_html(CATALOG_DIR / "index.html", html_content)

# -----------------------------
# Generate archives chunks (common)
# -----------------------------
def export_archive_chunks_js(js_folder, sort_key):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    direction = "ASC"

    if sort_key not in ["file_datetime", "size", "ext"]:
        sort_key = "path"

    if sort_key == "size":
        direction = "DESC"

    rows = cur.execute(f"""
        SELECT path, size, ext, file_datetime
        FROM archives
        ORDER BY {sort_key} {direction}
    """).fetchall()

    data_dir = CATALOG_DIR / js_folder
    data_dir.mkdir(exist_ok=True)

    chunk = []
    last_sel = None
    file_id = 0
    counter = 0

    for row in rows:
        path, size, ext, file_dt = row
        if sort_key == "file_datetime":
            current_sel = time.strftime('%Y-%m-%d', time.localtime(file_dt))
        elif sort_key == "size":
            current_sel = None
        elif sort_key == ext:
            current_sel = None
        else:
            current_sel = None

        if current_sel is not None and current_sel != last_sel:
            chunk.append({"is_header": True, "header": current_sel})
            last_sel = current_sel
            counter += 1

        chunk.append({
            "is_header": False,
            "path": path,
            "size": human_size(size),
            "ext": ext,
            "file_dt": time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(file_dt))
        })
        counter += 1

        if len(chunk) >= CHUNK:
            js_content = f"window.chunk_{file_id:06} = {json.dumps(chunk, ensure_ascii=False)};"
            with open(data_dir / f"data_{file_id:06}.js", "w", encoding="utf-8") as f:
                f.write(js_content)
            chunk = []
            file_id += 1

    if chunk:
        js_content = f"window.chunk_{file_id:06} = {json.dumps(chunk, ensure_ascii=False)};"
        with open(data_dir / f"data_{file_id:06}.js", "w", encoding="utf-8") as f:
            f.write(js_content)

    conn.close()
    return counter

# -----------------------------
# Generate archive page (common)
# -----------------------------
def generate_archives(title, sort_key, output_name_without_ext):
    js_folder = f"{output_name_without_ext}_files"
    output_name = f"{output_name_without_ext}.html"
    print(f"Generating {output_name}...")
    total_count = export_archive_chunks_js(js_folder, sort_key)
    html_content = f"""
    <html>
    <head>
        <meta charset="utf-8">
        <title>{title}</title>
        {CSS}
        <style>
            .table-header {{ display: grid; grid-template-columns: 7fr 1fr 0.5fr 0.3fr; font-weight: bold; background: #eee; padding: 5px; border: 1px solid #ccc; position: sticky; top: 0; z-index: 100; }}
            .table-header a {{
                color: inherit;
                text-decoration: none;
                display: block;
            }}
            .table-header a:hover {{
                text-decoration: underline;
            }}
            #container {{ position: relative; width: 100%; }}
            .vrow {{ position: absolute; left: 0; right: 0; display: grid; grid-template-columns: 7fr 1fr 0.5fr 0.3fr; align-items: center; border-bottom: 1px solid #ccc; height: 50px; box-sizing: border-box; padding: 5px; background: white; }}
            .vrow div {{ padding: 0 5px; word-break: break-all; overflow: hidden; }}
        </style>
    </head>
    <body>
        <p><a href="index.html" class="home">Home</a></p>
        <h1>{title}</h1>
        <div class="table-header">
            <div><a href="archives_by_path.html">Path</a></div>
            <div><a href="archives.html">File Date</a></div>
            <div><a href="archives_by_size.html">Size</a></div>
            <div><a href="archives_by_ext.html">Ext</a></div>
        </div>
        <div id="container"></div>

        <script>
            let chunks = {{}};
            let loadedChunks = new Set();
            const CHUNK_SIZE = 1000;
            const rowHeight = 50;
            const totalCount = {total_count};
            const container = document.getElementById("container");
            container.style.height = (totalCount * rowHeight) + "px";

            function loadChunk(id) {{
                if (loadedChunks.has(id)) return;
                loadedChunks.add(id);
                const script = document.createElement('script');
                script.src = '{js_folder}/data_' + id.toString().padStart(6, '0') + '.js';
                script.onload = () => {{
                    chunks[id] = window['chunk_' + id.toString().padStart(6, '0')];
                    render();
                }};
                document.body.appendChild(script);
            }}

            function render() {{
                const scrollTop = window.scrollY || document.documentElement.scrollTop;
                const start = Math.floor(Math.max(0, scrollTop - 100) / rowHeight);
                const end = Math.min(start + 20, totalCount);

                for(let i = Math.floor(start / CHUNK_SIZE); i <= Math.floor(end / CHUNK_SIZE); i++) loadChunk(i);

                container.innerHTML = "";
                for (let i = start; i < end; i++) {{
                    const chunkId = Math.floor(i / CHUNK_SIZE);
                    const idx = i % CHUNK_SIZE;
                    const div = document.createElement("div");
                    div.className = "vrow";
                    div.style.top = (i * rowHeight) + "px";

                    if (chunks[chunkId] && chunks[chunkId][idx]) {{
                        const it = chunks[chunkId][idx];
                        if (it.is_header) {{
                            div.innerHTML = `<div style="grid-column: span 7; font-size: 20px; font-weight: bold; background: #ddd; padding: 5px;">${{it.header}}</div>`;
                            div.style.background = "#ddd";
                        }} else {{
                            div.innerHTML = `
                                <div>${{it.path}}</div>
                                <div>${{it.file_dt}}</div>
                                <div>${{it.size}}</div>
                                <div>${{it.ext}}</div>
                            `;
                        }}
                    }} else {{
                        div.innerHTML = `<div style="grid-column: span 7;">Loading...</div>`;
                    }}
                    container.appendChild(div);
                }}
            }}
            window.addEventListener("scroll", render);
            render();
        </script>
    {get_footer()}
    </body>
    </html>
    """
    write_html(CATALOG_DIR / output_name, html_content)

# -----------------------------
# Generate data chunks (common version)
# -----------------------------
def export_data_chunks_js(js_folder, sort_key):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    direction = "ASC"

    if sort_key not in ["path", "exif_datetime", "file_datetime", "camera", "size"]:
        sort_key = "path"

    if sort_key == "size":
        direction = "DESC"

    rows = cur.execute(f"""
        SELECT path, exif_datetime, file_datetime, camera, size, thumb_path
        FROM photos
        ORDER BY {sort_key} {direction}
    """).fetchall()

    data_dir = CATALOG_DIR / js_folder
    data_dir.mkdir(exist_ok=True)

    chunk = []
    last_sel = None
    file_id = 0
    counter = 0

    for row in rows:
        path, exif_dt, file_dt, camera, size, thumb = row
        if sort_key == "path":
            current_sel = None
        if sort_key == "exif_datetime":
            current_sel = exif_dt
        elif sort_key == "file_datetime":
            current_sel = time.strftime('%Y-%m-%d', time.localtime(file_dt))
        elif sort_key == "camera":
            current_sel = camera
        elif sort_key == "size":
            current_sel = None
        else:
            current_sel = None

        if current_sel is not None and current_sel != last_sel:
            chunk.append({"is_header": True, "header": current_sel})
            last_sel = current_sel
            counter += 1

        chunk.append({
            "is_header": False,
            "path": path, "exif": exif_dt,
            "file_dt": time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(file_dt)),
            "camera": camera, "size": human_size(size), "thumb": thumb if thumb != "" else None,
        })
        counter += 1

        if len(chunk) >= CHUNK:
            js_content = f"window.chunk_{file_id:06} = {json.dumps(chunk, ensure_ascii=False)};"
            with open(data_dir / f"data_{file_id:06}.js", "w", encoding="utf-8") as f:
                f.write(js_content)
            chunk = []
            file_id += 1

    if chunk:
        js_content = f"window.chunk_{file_id:06} = {json.dumps(chunk, ensure_ascii=False)};"
        with open(data_dir / f"data_{file_id:06}.js", "w", encoding="utf-8") as f:
            f.write(js_content)

    conn.close()
    return counter

# -----------------------------
# Generate data page (common)
# -----------------------------
def generate_data_page(title, sort_key, output_name_without_ext):
    js_folder = f"{output_name_without_ext}_files"
    output_name = f"{output_name_without_ext}.html"
    print(f"Generating {output_name}...")
    total_count = export_data_chunks_js(js_folder, sort_key)
    html_content = f"""
    <html>
    <head>
        <meta charset="utf-8">
        <title>{title}</title>
        {CSS}
        <style>
            .table-header {{
                display: grid;
                grid-template-columns: 160px 4fr 1fr 1fr 1.5fr 0.4fr;
                font-weight: bold;
                background: #eee;
                padding: 5px;
                border: 1px solid #ccc;
                position: sticky;
                top: 0;
                z-index: 100;
            }}
            .table-header a {{
                color: inherit;
                text-decoration: none;
                display: block;
            }}
            .table-header a:hover {{
                text-decoration: underline;
            }}
            .no-preview {{
                font-size: 10px;
                color: #999;
                text-align: center;
                border: 1px dashed #ccc;
                width: 100%;
                height: 100%;
                display: flex;
                align-items: center;
                justify-content: center;
            }}
            #container {{ position: relative; width: 100%; }}
            .vrow {{
                position: absolute;
                left: 0;
                right: 0;
                display: grid;
                grid-template-columns: 160px 4fr 1fr 1fr 1.5fr 0.4fr;
                align-items: center;
                border-bottom: 1px solid #ccc;
                height: 150px;
                box-sizing: border-box;
                padding: 5px;
                background: white;
            }}
            .vrow div {{ padding: 0 5px; word-break: break-all; overflow: hidden; }}
        </style>
    </head>
    <body>
        <p><a href="index.html" class="home">Home</a></p>
        <h1>{title}</h1>
        <div class="table-header">
            <div>Thumb</div>
            <div><a href="simple.html">Path</a></div>
            <div><a href="exif_data_sorted.html">EXIF</a></div>
            <div><a href="file_data_sorted.html">File Date</a></div>
            <div><a href="camera_sorted.html">Camera</a></div>
            <div><a href="size_sorted.html">Size</a></div>
        </div>
        <div id="container"></div>

        <script>
            let chunks = {{}};
            let loadedChunks = new Set();
            const CHUNK_SIZE = 1000;
            const rowHeight = 150;
            const totalCount = {total_count};
            const container = document.getElementById("container");
            container.style.height = (totalCount * rowHeight) + "px";

            function loadChunk(id) {{
                if (loadedChunks.has(id)) return;
                loadedChunks.add(id);
                const script = document.createElement('script');
                script.src = '{js_folder}/data_' + id.toString().padStart(6, '0') + '.js';
                script.onload = () => {{
                    chunks[id] = window['chunk_' + id.toString().padStart(6, '0')];
                    render();
                }};
                document.body.appendChild(script);
            }}

            function render() {{
                const scrollTop = window.scrollY || document.documentElement.scrollTop;
                const start = Math.floor(Math.max(0, scrollTop - 100) / rowHeight);
                const end = Math.min(start + 20, totalCount);

                for(let i = Math.floor(start / CHUNK_SIZE); i <= Math.floor(end / CHUNK_SIZE); i++) loadChunk(i);

                container.innerHTML = "";
                for (let i = start; i < end; i++) {{
                    const chunkId = Math.floor(i / CHUNK_SIZE);
                    const idx = i % CHUNK_SIZE;
                    const div = document.createElement("div");
                    div.className = "vrow";
                    div.style.top = (i * rowHeight) + "px";

                    if (chunks[chunkId] && chunks[chunkId][idx]) {{
                        const it = chunks[chunkId][idx];
                        if (it.is_header) {{
                            div.innerHTML = `<div style="grid-column: span 7; font-size: 20px; font-weight: bold; background: #ddd; ">${{it.header}}</div>`;
                            div.style.background = "#ddd";
                        }} else {{
                            let thumbHtml = it.thumb
                                ? '<img src="' + it.thumb + '" class="thumbf">'
                                : '<div class="no-preview">No preview</div>';
                            div.innerHTML = `
                                <div class="thumbbox">${{thumbHtml}}</div>
                                <div>${{it.path}}</div>
                                <div>${{it.exif || ""}}</div>
                                <div>${{it.file_dt}}</div>
                                <div>${{it.camera || ""}}</div>
                                <div>${{it.size}}</div>
                            `;
                        }}
                    }} else {{
                        div.innerHTML = `<div style="grid-column: span 7;">Loading...</div>`;
                    }}
                    container.appendChild(div);
                }}
            }}
            window.addEventListener("scroll", render);
            render();
        </script>
    {get_footer()}
    </body>
    </html>
    """
    write_html(CATALOG_DIR / output_name, html_content)

# -----------------------------
# Main
# -----------------------------
def main():
    parser = argparse.ArgumentParser(description="Photo cataloger")

    parser.add_argument("-r", "--root_path", default="C:/", help="Starting folder for scanning (default C:/)")
    parser.add_argument("-p", "--pass_scan", action="store_true", help="Skip scan (use existing DB)")

    args = parser.parse_args()

    root_path = Path(args.root_path)
    full_scan = not args.pass_scan

    if full_scan == False and not DB_PATH.exists():
        print(f"Error: Database ({DB_PATH}) not found. Please run a full scan first.")
        return 1

    start = time.perf_counter()
    if full_scan == True:
        print("Prepare output folders...")
        prepare_tumb_dirs()
        print("Start scan...")
        pict_size, archives_size, pict_files, arch_files, exts, arch_exts = scan_disk(root_path)
    else:
        print("Using prescaned data (all sizes = 0)...")
        pict_size = 0
        archives_size = 0
        pict_files = 0
        arch_files = 0
        exts = EXTS
        arch_exts = ARCHIVE_EXTS

    print("Generating index.html...")
    generate_index(pict_size, archives_size, pict_files, arch_files, exts, arch_exts, root_path)
    # Generate pages
    generate_data_page("A simple list", "path", "simple")
    generate_data_page("List of exif dates in ascending order", "exif_datetime", "exif_data_sorted")
    generate_data_page("List in ascending order of file date", "file_datetime", "file_data_sorted")
    generate_data_page("List by camera", "camera", "camera_sorted")
    generate_data_page("List in descending order of size", "size", "size_sorted")

    generate_archives("Archives by path", "path", "archives_by_path")
    generate_archives("Archives by date", "file_datetime", "archives")
    generate_archives("Archives by size", "size", "archives_by_size")
    generate_archives("Archives by extension", "ext", "archives_by_ext")

    elapsed = time.perf_counter() - start
    print(f"Completed in {str(timedelta(seconds=elapsed))}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
