# Altium Tools GUI

A desktop toolkit for **Altium Designer** automation. It drives the running
Altium instance through the **eda-agent MCP bridge** (stdio + JSON-RPC), so it
does not depend on the Altium scripting IDE.

The UI follows the **[oink-ui](https://oink-ui.hachiwii.com) style**: React 18 +
Vite + TypeScript, a grouped sidebar, a large content area, soft corners,
hairline borders, no shadows, light/dark themes, and a single accent colour.

> Since 2026-11 the UI is a **local web application**. The backend is still
> plain Python logic (`altium_bridge`, `stackup_*`, `*_script`) exposed through
> `server.py` as a JSON API. The old Tkinter UI is kept in `legacy_tkinter/`
> for reference only.

## Features

| Group | Page | Description |
|---|---|---|
| Project | **Project snapshot** | Scan date folders, preview a timestamped destination, copy the project |
| Schematic | **Port parent/child sync** | Scan the hierarchy, select a child sheet, add or remove sheet entries in every parent sheet symbol |
| Schematic | **Entry batch wiring** | Scan sheets, symbols and entries; batch-add or remove wires and matching net labels outside each symbol |
| PCB | **Midpoint short line** | Draw short lines at the midpoint of two vertical/horizontal tracks |
| PCB | **Stackup design** | Calculate and generate stackups (layer table, MMF chart, results, `.stackup` output) |
| PCB | **Layer swap** | Reorder or swap layer names using the confirmed stackup |
| PCB | **Stackup overwrite** | Clear layer A, then copy layer B into A while keeping B |
| PCB | **Core slot** | Find similar closed TopOverlay contours and add/remove board cutouts |
| PCB | **Copper cutout** | Merge a selected polygon and Polygon Cutout into the pour outline |
| PCB | **Winding matrix** | Select four boundaries, scan the winding range, copy layers, mirror/translate to the lower post, and delete copied layers |

## Requirements

- **Windows** + **Altium Designer** (tested with AD22 and 25.8.1.18; process
  name `X2`)
- **Python 3.12** (standard library only; Tkinter is not required for the web UI)
- **Node.js 18+ / npm** (only when changing or rebuilding the frontend)
- **Rust toolchain (MSVC)** — only when rebuilding the desktop executable:
  `https://static.rust-lang.org/rustup/dist/x86_64-pc-windows-msvc/rustup-init.exe`
  ```bat
  rustup-init.exe -y --profile minimal --default-toolchain stable-x86_64-pc-windows-msvc --no-modify-path
  ```
  Also requires **Microsoft C++ Build Tools** (MSVC v143 + Windows SDK) and
  **Edge WebView2 Runtime** (included with Windows 11).
- The bridge starts the eda-agent MCP server automatically as a child process.

## Running

### Option 1: Desktop shortcut (recommended)

```bat
run-web.cmd
```

The launcher restarts the backend, waits for port 8765, then opens the UI in an
Edge app window. The desktop shortcut uses `run-web-silent.vbs` so no console
window appears.

### Option 2: Command line

```bat
python server.py
python server.py --port 9000 --no-browser
```

### Option 3: Frontend development

```bat
:: terminal 1 - backend
python server.py --no-browser

:: terminal 2 - frontend on 5173, API proxied to 8765
cd web
npm install
npm run dev
```

### Rebuild the frontend

```bat
cd web
npm install
npm run build
```

The output is written to `web/dist/` and served by `server.py`.

### Desktop build (Tauri)

```bat
cd web
npm install
npm run tauri:build
npm run tauri:build -- --no-bundle
```

Use `npm run tauri:build`, not a bare `cargo build --release`: the Tauri CLI
embeds `web/dist` and removes `build.devUrl`.

## Layout

```text
altium_tools/
├── server.py                  # HTTP server: JSON API + static frontend
├── api/                       # Backend services
│   ├── paths.py               # Paths: outputs, config, frontend dist
│   ├── config_store.py        # Merge-on-write config storage
│   ├── bridge_service.py      # Altium MCP bridge singleton
│   ├── midpoint_service.py    # Midpoint short lines
│   ├── stackup_service.py     # Stackup state machine
│   ├── swap_service.py        # Layer swap script generation
│   ├── overwrite_service.py   # Layer overwrite script generation
│   ├── snapshot_service.py    # Project snapshots
│   ├── schport_service.py     # Parent/child sheet port sync
│   ├── schwire_service.py     # Entry batch wiring
│   └── winding_service.py     # Winding scan, copy, mirror, translate, delete
├── web/                       # React 18 + Vite + TypeScript frontend
│   ├── src/App.tsx            # App shell and navigation
│   ├── src/pages/             # Feature pages
│   └── src-tauri/             # Tauri v2 desktop shell
├── altium_bridge.py           # eda-agent MCP stdio bridge
├── stackup_design.py          # Stackup calculations
├── stackup_build.py           # Stackup generation
├── stackup_file.py            # .stackup text format
├── swap_script.py             # Layer swap script generation
├── overwrite_script.py        # Layer overwrite script generation
├── snapshot_core.py           # Snapshot core
├── legacy_tkinter/            # Legacy Tkinter UI (reference only)
└── altium_tools_config.json   # Persisted settings
```

## HTTP API

| Method | Path | Description |
|---|---|---|
| GET | `/api/health` | Health check and bridge status |
| GET/PUT | `/api/config` | Read/merge/write configuration |
| GET | `/api/bridge/status` | Altium bridge status |
| POST | `/api/bridge/connect` | Connect or reconnect Altium |
| GET | `/api/pcb/stackup` | Current PCB copper layers |
| POST | `/api/coreslot/scan` `create` `delete` | Find contours and manage board cutouts |
| POST | `/api/pourcut/scan` `apply` | Inspect and merge copper cutouts |
| POST | `/api/winding/scan` | Scan the winding range and build a copy plan |
| POST | `/api/winding/apply` | Copy source layers within the upper post |
| POST | `/api/winding/read_axis` | Read the selected horizontal mirror line |
| POST | `/api/winding/read_shift` | Read the Y offset from two selected components |
| POST | `/api/winding/operate` | Run mirror + translation and return the lower-layer scan |
| POST | `/api/winding/delete` | Delete selected copied layers |
| POST | `/api/schport/scan` `sync` | Scan hierarchy and sync parent sheet entries |
| POST | `/api/schwire/scan` `apply` | Scan symbols/entries and add or remove wires/labels |
| POST | `/api/midpoint/read` `draw` | Read selection and draw midpoint lines |
| GET/POST | `/api/stackup/*` | Stackup state, parameters, templates, confirm/write |
| POST | `/api/swap/validate` `generate` | Validate and generate layer swap scripts |
| POST | `/api/overwrite/validate` `generate` | Validate and generate overwrite scripts |
| GET/POST | `/api/snapshot/*` | Scan, plan, create, browse and reveal snapshots |

Errors use `{"ok": false, "error": "...", "hint": "..."}`. A bridge timeout
returns HTTP 504 with the `altium_bridge.BridgeTimeout.HINT` guidance.

## Notes

- Deep links: `http://127.0.0.1:8765/?page=stackup` opens a page directly.
- The frontend is responsive: three/two-column layouts collapse to one column
  on narrow screens, and tables avoid horizontal scrolling at common resolutions.
- When the Altium MCP polling loop is interrupted, restart it from
  `File > Run Script > Altium_API > Dispatcher.pas > StartMCPServer`.

## License

MIT
