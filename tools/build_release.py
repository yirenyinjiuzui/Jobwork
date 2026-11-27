"""Build a clean ZIP and a self-contained text recovery copy; never overwrite."""
import base64
import hashlib
import re
from pathlib import Path
import zipfile

ROOT_FILES = {".gitignore", "README.md", "VERSION"}
TREE_DIRS = {"docs", "extension", "web", "tests", "skills", "tools"}
RESTORE = r"""$ErrorActionPreference = 'Stop'
try {
    $txt = (Read-Host 'Full path to the downloaded TXT').Trim().Trim('"')
    $dest = (Read-Host 'NEW destination folder, e.g. D:\JobWorkbench-test').Trim().Trim('"')
    if ([string]::IsNullOrWhiteSpace($dest)) { throw 'Destination is required.' }
    if (Test-Path -LiteralPath $dest) { throw 'Destination already exists. Choose a NEW folder; existing data was not changed.' }
    $raw = Get-Content -LiteralPath $txt -Raw
    $hashMatch = [regex]::Match($raw, '(?m)^ZIP SHA256: ([a-f0-9]{64})\r?$')
    $payload = [regex]::Match($raw, '(?ms)^-----BEGIN JOB WORKBENCH ZIP-----\r?\n(.*?)^-----END JOB WORKBENCH ZIP-----')
    if (-not $hashMatch.Success -or -not $payload.Success) { throw 'Incomplete TXT. Save the complete backup first.' }
    $bytes = [Convert]::FromBase64String($payload.Groups[1].Value)
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $actual = [BitConverter]::ToString($sha.ComputeHash($bytes)).Replace('-', '').ToLowerInvariant() }
    finally { $sha.Dispose() }
    if ($actual -ne $hashMatch.Groups[1].Value) { throw 'SHA256 mismatch. No destination was created.' }
    $null = New-Item -ItemType Directory -Path $dest -ErrorAction Stop
    $dest = (Resolve-Path -LiteralPath $dest).Path
    $zip = Join-Path $dest 'verified-release.zip'
    [IO.File]::WriteAllBytes($zip, $bytes)
    Expand-Archive -LiteralPath $zip -DestinationPath $dest -ErrorAction Stop
    Write-Host ('Verified and extracted. Open: ' + (Join-Path $dest 'job-workbench\start-windows.cmd'))
} catch {
    Write-Host ('Recovery stopped: ' + $_.Exception.Message)
    Write-Host 'Keep old installations and data. If a new folder was partially created, use another NEW destination.'
}
"""

def decode_backup(text):
    expected = re.search(r"(?m)^ZIP SHA256: ([a-f0-9]{64})\r?$", text)
    payload = re.search(r"(?ms)^-----BEGIN JOB WORKBENCH ZIP-----\r?\n(.*?)^-----END JOB WORKBENCH ZIP-----", text)
    if not expected or not payload:
        raise ValueError("Incomplete backup")
    data = base64.b64decode(re.sub(r"\s", "", payload[1]), validate=True)
    if hashlib.sha256(data).hexdigest() != expected[1]:
        raise ValueError("SHA256 mismatch")
    return data

def release_files(root):
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if not path.is_file() or path.is_symlink() or any(part in {"data", "__pycache__", ".git", ".venv"} for part in rel.parts):
            continue
        if path.suffix in {".pyc", ".sqlite3", ".db"} or path.name.endswith(("-wal", "-shm")):
            continue
        if (len(rel.parts) == 1 and (path.name in ROOT_FILES or path.suffix in {".py", ".cmd"})) or (len(rel.parts) > 1 and rel.parts[0] in TREE_DIRS):
            yield path, rel

def build(root, out):
    version = (root / "VERSION").read_text().strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Invalid version")
    zipped = out / ("job-workbench-v" + version + ".zip")
    backup = out / ("job-workbench-v" + version + "-base64.txt")
    if zipped.exists() or backup.exists():
        raise FileExistsError("Release already exists; refusing to overwrite")
    out.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zipped, "x", zipfile.ZIP_DEFLATED) as archive:
        for path, rel in release_files(root):
            archive.write(path, "job-workbench/" + rel.as_posix())
    data = zipped.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    text = ("求职工作台 v" + version + "：ZIP 的完整 TXT 恢复备份\n"
            "ZIP SHA256: " + digest + "\n\n"
            "保存完整 TXT。只复制下面 BEGIN POWERSHELL 与 END POWERSHELL 之间的命令到 Windows PowerShell，按提示输入本 TXT 路径和全新目标目录。\n"
            "不要复制 Base64 数据到命令窗口；不要对整个 TXT 直接解码。无需管理员权限或修改执行策略。\n"
            "目标已存在即停止；校验成功后才创建目标并解压，不覆盖原 data。真实 Windows 实机仍待验收。\n\n"
            "-----BEGIN POWERSHELL-----\n" + RESTORE + "-----END POWERSHELL-----\n\n"
            "-----BEGIN JOB WORKBENCH ZIP-----\n" + base64.encodebytes(data).decode("ascii") +
            "-----END JOB WORKBENCH ZIP-----\n")
    with backup.open("x", encoding="utf-8") as stream:
        stream.write(text)
    assert decode_backup(text) == data
    return zipped, backup, digest

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for result in build(Path(__file__).resolve().parents[1], args.output):
        print(result)
