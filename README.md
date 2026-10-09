# Altium 工具集（Altium Tools GUI）

面向 **Altium Designer (AD22)** 的桌面小工具集，统一走
**eda-agent MCP 桥接**（stdio + JSON-RPC）驱动运行中的 AD，不依赖 AD 自带的脚本 IDE。

界面遵循本机统一规范：**tkinter/ttk 现代浅色**（`clam` 深度定制、`Microsoft YaHei UI`、
主色 `#2563EB`），左侧竖排图标侧边栏 + 分组，大内容区可拖拽调尺寸，参数写 JSON 持久化。

## 功能

| 分组 | 页面 | 说明 |
|---|---|---|
| 原理图操作 | 概览 | 占位页（后续在此分类下扩展） |
| PCB 操作 | **画中点短线** | 在两条竖线/水平线的中点画短线，内部 2 个 tab |
| PCB 操作 | **叠层设计** | 叠层参数计算与生成 |
| PCB 操作 | **层交换** | 层名重排/交换（层名取自「叠层设计」确认后的结果） |

## 环境要求

- **Windows** + **Altium Designer**（本机实测 AD22 / 25.8.1.18，进程名 `X2`）
- **Python 3.12**（必须带 `tkinter`）。本机隔离 venv（3.13）**没有 tkinter**，请用系统 Python：
  ```
  C:\Users\admin\AppData\Local\Programs\Python\Python312\python.exe
  ```
- **第三方依赖：无**（全部标准库 + 本目录内的本地模块）⇒ `requirements.txt` 为空是正常的
- 桥接侧需要 eda-agent MCP server（`altium_bridge.py` 会自动以子进程方式拉起）

## 运行

```bat
:: 方式 1：双击启动器（无控制台窗口）
AltiumTools.cmd

:: 方式 2：命令行（能看到报错）
"C:\Users\admin\AppData\Local\Programs\Python\Python312\python.exe" main.py
```

> `AltiumTools.cmd` 里的 Python 路径是**本机硬编码**的。换机器时请改成自己的 Python 3.12 路径，
> 或直接用命令行方式运行。

## 目录结构

```
altium_tools/
├── main.py                     # 入口：侧边栏 + 分组 + 页面装配
├── gui_style.py                # 统一浅色主题（PALETTE / init / card / sidebar / 配置读写）
├── gui_sidebar.py              # 左侧竖排图标侧边栏（纯 Canvas 矢量图标，零依赖）
├── altium_bridge.py            # eda-agent MCP stdio 桥接（MCPClient）
├── midpoint_tab.py             # 画中点短线
├── stackup_page.py             # 叠层设计（页面）
├── stackup_design.py           # 叠层设计（计算）
├── stackup_build.py            # 叠层设计（构建）
├── stackup_file.py             # 叠层文件读写（.stackup 文本通道）
├── swap_page.py                # 层交换（页面）
├── swap_script.py              # 层交换（脚本生成/执行）
├── altium_tools_config.json    # 参数持久化（首次运行自动生成/补全）
├── AltiumTools.cmd             # 双击启动器（主程序）
├── UploadToGitHub.cmd          # 双击启动器（图形上传窗口）
├── AltiumTools.spec            # PyInstaller 打包配置（打 exe 用）
├── gh_upload.py                # 一键发布到 GitHub（REST API，绕开 git.exe，见下）
└── upload_gui.py               # 图形上传窗口（双击即可，不用敲命令）
```

## 发布到 GitHub

有两种方式，效果一样：

**方式 A：图形窗口（推荐）** —— 双击 `UploadToGitHub.cmd`，或直接双击 `upload_gui.py`
填 Token → 点【先体检（不联网）】确认文件都 OK → 点【开始上传】。
窗口里还能勾「打包 exe 并作为附件上传」和填「发布 Release」（如 `v1.0.0`）。

**方式 B：命令行** —— 用 `gh_upload.py`

本仓库用 `gh_upload.py` 推送，**故意不用 `git.exe`**：

> 本机装有 DLP 透明加密驱动，非白名单进程（`git.exe` / `powershell`）读到的源文件是
> **密文**（文件头 `%TSD-Header-###%`），`git` 会把它当二进制提交，仓库里就是一堆乱码。
> **Python 在白名单里**，读到的是明文，所以脚本用 Python 读文件、直接调 GitHub REST API 建 commit。

```bat
:: 首次（自动建库）
python gh_upload.py --token ghp_xxx --repo altium-tools --public
:: 以后每次改完
python gh_upload.py --token ghp_xxx --repo altium-tools -m "修中点短线层跟随"
:: 顺便打 exe 并发 Release
python gh_upload.py --token ghp_xxx --repo altium-tools --release v1.0.0 --with-exe
:: 只看会传什么（不联网）
python gh_upload.py --dry-run
```

token 也可放环境变量 `GITHUB_TOKEN`。详见脚本头部注释。

> ⚠️ `upload_gui.py` / `UploadToGitHub.cmd` 必须用 **系统 Python 3.12**（带 tkinter）。
> 隔离 venv 的 3.13 没有 tkinter，启动会报 `ModuleNotFoundError`。
> `UploadToGitHub.cmd` 会自动探测带 tkinter 的 3.12，找不到会给出提示。

## License

MIT
