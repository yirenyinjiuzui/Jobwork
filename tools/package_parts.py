"""Build the four module ZIPs from the same full distribution archive."""
import argparse
import hashlib
import re
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, ZipFile

PARTS = {
    "岗位发现与开招提醒": "discovery",
    "简历导入与个人资料": "profile",
    "浏览器扩展与网申填表": "extension",
    "投递追踪与待办": "tracking",
}
PREFIX = "job-workbench/"


def module_files(archive, title):
    index = f"{PREFIX}modules/{title}/README.md"
    guide = archive.read(index).decode("utf-8")
    selections = {PREFIX + "VERSION", index}
    entries = set(archive.namelist())
    for line in guide.split("## 打包范围\n", 1)[1].strip().splitlines():
        link = re.fullmatch(r"- \[[^\]]+\]\(\.\./\.\./([^)]+)\)", line)
        if not link:
            raise ValueError(f"{title}: invalid file entry {line!r}")
        relative = link[1]
        if PurePosixPath(relative).is_absolute() or ".." in relative.split("/"):
            raise ValueError(f"{title}: invalid path {relative}")
        name = PREFIX + relative
        matches = {f for f in entries if f.startswith(name)} if name.endswith("/") else entries & {name}
        if not matches:
            raise ValueError(f"{title}: file missing from full ZIP: {relative}")
        selections.update(matches)
    return sorted(selections)


def package_parts(full_zip):
    with ZipFile(full_zip) as source:
        version = source.read(PREFIX + "VERSION").decode().strip()
        if not re.fullmatch(r"\d+\.\d+\.\d+", version) or full_zip.name != f"job-workbench-v{version}.zip":
            raise ValueError("Full ZIP filename and VERSION must agree")
        plans = {slug: module_files(source, title) for title, slug in PARTS.items()}
        outputs = [full_zip, full_zip.with_name(full_zip.stem + "-base64.txt")]
        for slug, names in plans.items():
            path = full_zip.with_name(f"{full_zip.stem}-{slug}.zip")
            with ZipFile(path, "x", ZIP_DEFLATED) as part:
                for name in names:
                    part.writestr(name, source.read(name))
            outputs.append(path)
    with full_zip.with_name("SHA256SUMS.txt").open("x", encoding="ascii", newline="\n") as sums:
        for path in outputs:
            sums.write(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("full_zip", type=Path)
    package_parts(parser.parse_args().full_zip)
