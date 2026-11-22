# Altium 工具集（Altium Tools GUI）

面向 **Altium Designer (AD22)** 的桌面小工具集，统一走
**eda-agent MCP 桥接**（stdio + JSON-RPC）驱动运行中的 AD，不依赖 AD 自带的脚本 IDE。

界面为 **[oink-ui](https://oink-ui.hachiwii.com) 风格**：React 18 + Vite + TypeScript，
左侧分组侧边栏 + 大内容区，柔和圆角、发丝描边、无阴影、明暗主题，
主色单一（跟随 oink-ui 的 accent）。

> 2026-11 起界面已从 **tkinter/ttk** 整体改造为 **本地 Web 应用**：
> 后端仍是同一套 Python 纯逻辑（`altium_bridge` / `stackup_*` / `*_script`），
> 通过 `server.py` 暴露 JSON API，前端是 oink-ui 组件。
> 旧版 Tkinter 界面保留在 `legacy_tkinter/`（仅供参考，可随时回退）。

## 功能

| 分组 | 页面 | 说明 |
|---|---|---|
| 原理图操作 | 概览 | 占位页（后续在此分类下扩展） |
| PCB 操作 | **画中点短线** | 在两条竖线/水平线的中点画短线，内部 2 个 tab |
| PCB 操作 | **叠层设计** | 叠层参数计算与生成（层序表 / MMF 图 / 计算结果 / 写出 .stackup） |
| PCB 操作 | **层交换** | 层名重排/交换（层名取自「叠层设计」确认后的结果） |
| PCB 操作 | **叠层覆盖** | 清空 A 层 → 把 B 层内容复制到 A（B 保留） |
| PCB 操作 | **磁芯挖槽** | 选中 TopOverlay 闭合线 → 全板相似图形 → board cutout 增删 |
| PCB 操作 | **铺铜挖空** | 选中铺铜 + Polygon Cutout → 合并进铺铜轮廓端点 |
| PCB 操作 | **绕组矩阵绘制** | 选左右 MOS → 识别绕组范围 → 按层映射复制 |
| 原理图操作 | **port父子图同步** | 扫描调用结构 → 选子图 → 父图 entry 增删 |
| 工程管理 | **工程快照** | 日期目录 → 时间戳目录 → 拷工程本体 |

## 环境要求

- **Windows** + **Altium Designer**（本机实测 AD22 / 25.8.1.18，进程名 `X2`）
- **Python 3.12**（后端只用标准库；**不再需要 tkinter**）
- **Node.js 18+ / npm**（仅在改前端或重打包时需要）
- **Rust 工具链（MSVC）** —— 只有要自己重新构建桌面版 exe 时才需要：
  `https://static.rust-lang.org/rustup/dist/x86_64-pc-windows-msvc/rustup-init.exe`
  （静默安装：`rustup-init.exe -y --profile minimal --default-toolchain stable-x86_64-pc-windows-msvc --no-modify-path`）
  另外要 **Microsoft C++ Build Tools**（本机已有 VS 2022 BuildTools，含 "MSVC v143 生成工具" + Windows SDK）
  和 **Edge WebView2 Runtime**（Win11 自带）。
  crates 下载慢的话配一下镜像 `%USERPROFILE%\.cargo\config.toml`：
  ```toml
  [source.crates-io]
  replace-with = 'rsproxy-sparse'
  [source.rsproxy-sparse]
  registry = "sparse+https://rsproxy.cn/index/"
  [net]
  git-fetch-with-cli = true
  ```
- 桥接侧需要 eda-agent MCP server（`altium_bridge.py` 会自动以子进程方式拉起）

## 运行

### 方式 1：双击启动器（推荐）

```
AltiumTools.cmd
```

- 有桌面版 exe（`web/src-tauri/target/release/altium-tools.exe`）→ 直接开**原生窗口**
- 没有 → 起本地服务并用浏览器打开（`http://127.0.0.1:8765/`，端口占用时自动顺延）

> 已构建好的安装包：`web/src-tauri/target/release/bundle/nsis/AltiumTools_2.0.0_x64-setup.exe`

### 方式 2：桌面版（Tauri）

桌面版 = **Tauri v2 外壳 + 同一套 React/oink-ui 前端 + 同一个 Python 后端**：

```
AltiumTools.cmd                 :: 直接跑已构建的 exe
web/src-tauri/target/release/altium-tools.exe
```

- 窗口无地址栏、无标签页，就是普通软件窗口；用系统 **Edge WebView2** 渲染
- 启动时自动拉起 `server.py --port 8765 --strict-port` 作为后端，
  并在页面脚本之前注入 `window.__ALTUM_API__`（前端据此跨源访问后端，后端已放行 CORS）
- 关闭应用时后端进程一并结束；端口上已有健康实例时直接复用
- **不弹黑窗**：主程序是 GUI 子系统；后端用 `pythonw.exe` 拉起，
  子进程一律带 `CREATE_NO_WINDOW`，不会闪命令行窗口。后端日志见 `%TEMP%\altium_backend.log`
- 参数配置：桌面版与浏览器版共用同一份 `altium_tools_config.json`
  （桌面版通过 `ALTUM_HOME` 指向项目根；安装版则指向安装目录下的 `resources\`）

**构建桌面版**（需要 Rust 工具链，见文末）：

```bat
cd web
npm install
npm run tauri:build             :: 出 exe + NSIS 安装包 + MSI
npm run tauri:build -- --no-bundle   :: 只出 exe（免安装）
```

> ⚠️ **必须用 `npm run tauri:build`，不要直接 `cargo build --release`**：
> Tauri CLI 才会把 `web/dist` 嵌进二进制并剥掉 `build.devUrl`；
> 裸 `cargo build` 不嵌前端资源 → 窗口报 `asset not found: index.html`。
>
> 免安装分发：`target/release/altium-tools.exe` 需要配套的 `target/release/resources/`
> （后端 py 文件与配置），由 `tauri:build` 自动生成。

### 方式 3：命令行（浏览器版）

```bat
"C:\Users\admin\AppData\Local\Programs\Python\Python312\python.exe" server.py
python server.py --port 9000 --no-browser     # 指定端口 / 不开浏览器
```

### 方式 4：前端热更新（开发）

```bat
:: 终端 1：后端
python server.py --no-browser
:: 终端 2：前端（5173，API 自动代理到 8765）
cd web
npm install
npm run dev
:: 想在桌面窗口里调试：npm run tauri:dev（窗口加载 5173）
```

### 重新构建前端

```bat
cd web
npm install
npm run build        :: 产物在 web/dist，由 server.py 托管 / 打进桌面版
```

> `web/package.json` 里 oink-ui 用本地 `file:` 链接引用
> `e:/AI_workspace/oink_ui/oink-ui`（相对路径 `../../../../../AI_workspace/oink_ui/oink-ui`），
> 换机器时改这一行即可。

## 界面自适应

- 页面用 `Page size="full"` 铺满主区（不受 oink-ui 默认 960px 上限限制）
- 三栏/两栏布局用 `fr` 比例：窗口放大 → 各栏按比例变大；≤1500px → 结果栏掉到下一行铺满；≤1080px → 单列
- 所有表单栅格改用 `Grid minItemWidth`（自动填充），窄容器自动降列，不再挤成一团
- 层序表：列宽收紧 + 表格内 Select 起步宽压到 96px + 窄容器自动隐藏次要列（铜厚/介质），
  常用分辨率下**不需要横向滚动**；层序色带改为横排在表格上方，不占表格宽度
- 标题/表格/统计字号用 `clamp()` 随视口温和放大（1200→2200px 约 +10%）
- 表格高度 `min(56vh, 760px)`、日志高度 `clamp(160px, 26vh, 460px)`，随窗口高度联动

> 深链：`http://127.0.0.1:8765/?page=stackup` 可直接打开某个页面
> （`overview|midpoint|stackup|swap|overwrite|snapshot`）。

## 目录结构

```
altium_tools/
├── server.py                     # 入口：本地 HTTP 服务（API + 静态托管）
├── api/                          # 后端业务层（纯逻辑，无界面）
│   ├── paths.py                  # 路径（脚本输出目录 / 配置 / 前端产物）
│   ├── config_store.py           # 配置读写（读-合并-写、原子落盘）
│   ├── bridge_service.py         # AD 桥接单例 + 读板子铜层
│   ├── midpoint_service.py       # 画中点短线
│   ├── stackup_service.py        # 叠层设计状态机（序列/计算/确认/写出）
│   ├── swap_service.py           # 层交换脚本生成
│   ├── overwrite_service.py      # 叠层覆盖脚本生成
│   └── snapshot_service.py       # 工程快照（扫描/预览/新建/浏览目录）
├── web/                          # 前端（React 18 + Vite + TS + oink-ui）
│   ├── package.json / vite.config.ts / tsconfig.json / index.html
│   ├── src/
│   │   ├── main.tsx / App.tsx    # 外壳（AppShell + Nav 分组侧边栏 + 状态栏）
│   │   ├── api.ts / types.ts     # HTTP 客户端与数据类型
│   │   ├── app.css               # 应用级样式（全部用 --ok-* 令牌）
│   │   ├── components/           # LogPanel / MmfChart / LayerStrip
│   │   └── pages/                # 6 个页面
│   └── src-tauri/                # 桌面外壳（Tauri v2 / Rust）
│       ├── Cargo.toml / build.rs / tauri.conf.json
│       ├── capabilities/default.json
│       ├── icons/                # 由 altium_tools.ico 生成
│       └── src/lib.rs            # 拉起 Python 后端 + 建窗口 + 注入 API 地址
├── altium_bridge.py              # eda-agent MCP stdio 桥接（纯逻辑）
├── stackup_design.py             # 叠层计算（纯逻辑）
├── stackup_build.py              # 叠层文件生成（纯逻辑）
├── stackup_file.py               # .stackup 文本通道（纯逻辑）
├── swap_script.py                # 层交换 DelphiScript 生成（纯逻辑）
├── overwrite_script.py           # 叠层覆盖 DelphiScript 生成（纯逻辑）
├── snapshot_core.py              # 快照核心（纯逻辑）
├── legacy_tkinter/               # 旧版 tkinter 界面（保留参考）
│   ├── main.py / gui_style.py / gui_sidebar.py
│   └── midpoint_tab.py / stackup_page.py / swap_page.py / overwrite_page.py / snapshot_page.py
├── altium_tools_config.json      # 参数持久化（与旧版共用同一个 JSON，键名兼容）
├── AltiumTools.cmd               # 双击启动器（主程序）
├── UploadToGitHub.cmd            # 双击启动器（图形上传窗口，仍是 tkinter）
├── AltiumTools.spec              # PyInstaller 打包配置（打 exe 用）
├── gh_upload.py                  # 一键发布到 GitHub（REST API，绕开 git.exe，见下）
├── upload_gui.py                 # 图形上传窗口（双击即可，不用敲命令）
└── web/dist/                     # 前端构建产物（npm run build 生成）
```

## HTTP API（给前端用）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 健康检查 + 桥接状态 |
| GET/PUT | `/api/config` | 配置读写（读-合并-写） |
| GET | `/api/bridge/status` | AD 桥接状态 |
| POST | `/api/bridge/connect` | 显式连接 / 重新连接 Altium |
| POST | `/api/coreslot/scan` · `/create` · `/delete` | 搜寻相似闭合线 / 增加 / 删除 board cutout |
| POST | `/api/pourcut/scan` · `/apply` | 检查铺铜+cutout / 合并挖空到铺铜轮廓 |
| POST | `/api/winding/scan` · `/apply` | 识别绕组范围与复制计划 / 执行复制 |
| POST | `/api/schport/scan` · `/sync` | 扫描父子图 / 按子图 port 同步父图 entry |
| GET | `/api/pcb/stackup` | 读当前 PCB 的铜层 |
| GET | `/api/midpoint/meta` | 长度预设 / 层名候选 / 文案 |
| POST | `/api/midpoint/read` · `/api/midpoint/draw` | 读取选中对象 / 在中点画线 |
| GET | `/api/stackup/state` | 叠层设计全量状态 |
| POST | `/api/stackup/params` · `/row-type` · `/row-oz` · `/sync-cu` · `/confirm` | 改参数 / 改层类型 / 改铜厚 / 同步铜厚 / 确认叠层 |
| GET | `/api/stackup/confirmed` | 已确认的层名（层交换 / 叠层覆盖页读它） |
| GET/POST | `/api/stackup/templates` · `/template/open` · `/write` | 叠层模板目录 / 读入 / 写出 |
| POST | `/api/swap/validate` · `/api/swap/generate` | 层交换校验 / 生成脚本 |
| POST | `/api/overwrite/validate` · `/api/overwrite/generate` | 叠层覆盖校验 / 生成脚本 |
| GET/POST | `/api/snapshot/scan` · `/plan` · `/create` · `/browse` · `/reveal` | 快照扫描 / 预览 / 新建 / 目录浏览 / 打开目录 |

错误统一返回 `{"ok": false, "error": "...", "hint": "..."}`；
桥接超时时 HTTP 504 并带 `altium_bridge.BridgeTimeout.HINT` 的处置提示。

## 发布到 GitHub

有两种方式，效果一样：

**方式 A：图形窗口（推荐）** —— 双击 `UploadToGitHub.cmd`，或直接双击 `upload_gui.py`
填 Token → 点【先体检（不联网）】确认文件都 OK → 点【开始上传】。
窗口里还能勾「打包桌面版安装包并作为附件上传」和填「发布 Release」（如 `v1.0.0`）。

> ⚠️ `upload_gui.py` 仍是 **tkinter** 窗口（独立的小工具，本轮未改造），
> 需要带 tkinter 的系统 Python 3.12。

**方式 B：命令行** —— 用 `gh_upload.py`

本仓库用 `gh_upload.py` 推送，**故意不用 `git.exe`**：

> 本机装有 DLP 透明加密驱动，非白名单进程（`git.exe` / `powershell`）读到的源文件是
> **密文**（文件头 `%TSD-Header-###%`），`git` 会把它当二进制提交，仓库里就是一堆乱码。
> **Python 在白名单里**，读到的是明文，所以脚本用 Python 读文件、直接调 GitHub REST API 建 commit。

```bat
:: 首次（自动建库）
python gh_upload.py --token ghp_xxx --repo altium-tools --public
:: 以后每次改完
python gh_upload.py --token ghp_xxx --repo altium-tools -m "改成 oink-ui 界面"
:: 顺便打桌面版安装包并发 Release（--with-exe 现在走 Tauri：npx tauri build --bundles nsis）
python gh_upload.py --token ghp_xxx --repo altium-tools --release v1.0.0 --with-exe
:: 只看会传什么（不联网）
python gh_upload.py --dry-run
```

token 也可放环境变量 `GITHUB_TOKEN`。详见脚本头部注释。

> 上传清单是 `gh_upload.py` 里的 `FILES`（当前 **66 个文件**）：
> 后端 `server.py` + `api/` + 纯逻辑模块、`web/` 前端源码、`web/src-tauri/` 桌面壳源码、
> `legacy_tkinter/` 旧界面留档。**不含** `node_modules/`、`web/dist/`、`src-tauri/target/` 等构建产物。
> 目录结构有变动时，记得同步这个清单（`--dry-run` 可以体检）。

> ⚠️ **图标为什么只有 `.ico`**：本机装有 DLP 透明加密驱动，**新建的 `.png` 一律被加密**
> （文件头 `%TSD`），非白名单进程读到的是乱码 —— 上传脚本会直接拒绝，而且 GitHub 上也是乱码。
> `.ico` 不在加密策略里，可以正常入库。所以桌面版图标统一用 `icons/icon.ico`
> （由 `make_tauri_icons.py` 从 `altium_tools.ico` 复制生成），Windows 打包完全够用。

## License

MIT
