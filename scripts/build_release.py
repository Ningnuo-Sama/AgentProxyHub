import os
import zipfile
import shutil

root_dir = r"D:\GitHub\AgentProxyHub"
release_dir = os.path.join(root_dir, "release")
os.makedirs(release_dir, exist_ok=True)

zip_name = "AgentProxyHub-v1.0.0-windows-x64.zip"
zip_path = os.path.join(release_dir, zip_name)

# 需要打包的文件和目录清单
include_dirs = ["assets", "config", "core", "mcp", "scripts", "ui"]
include_files = [
    "启动AgentProxyHub.bat",
    "打开面板.bat",
    "停止服务.bat",
    "README.md",
    "README_EN.md",
    "README_JA.md",
    "README_KO.md"
]

# 检查是否可打包 bin/ 内核
bin_dir = os.path.join(root_dir, "bin")
os.makedirs(bin_dir, exist_ok=True)
sys_mihomo = r"D:\Program Files\FengWoBridge\mihomo.exe"
if os.path.exists(sys_mihomo) and not os.path.exists(os.path.join(bin_dir, "mihomo.exe")):
    shutil.copy2(sys_mihomo, os.path.join(bin_dir, "mihomo.exe"))
    for f in ["geoip.metadb", "geosite.dat"]:
        p = os.path.join(r"D:\Program Files\FengWoBridge", f)
        if os.path.exists(p):
            shutil.copy2(p, os.path.join(bin_dir, f))
if os.path.exists(os.path.join(bin_dir, "mihomo.exe")):
    include_dirs.append("bin")

with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
    for d in include_dirs:
        abs_d = os.path.join(root_dir, d)
        if os.path.exists(abs_d):
            for r, _, files in os.walk(abs_d):
                for f in files:
                    full_p = os.path.join(r, f)
                    rel_p = os.path.relpath(full_p, root_dir)
                    zf.write(full_p, rel_p)
    for f in include_files:
        full_p = os.path.join(root_dir, f)
        if os.path.exists(full_p):
            zf.write(full_p, f)

print(f"[OK] Release package generated: {zip_path} ({os.path.getsize(zip_path) / (1024*1024):.2f} MB)")
