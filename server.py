"""Altium 工具集 —— 本地 HTTP 服务（后端）。

职责：
  * 提供 JSON API（`/api/*`）给 React + oink-ui 前端调用；
  * 托管前端构建产物 `web/dist`（静态文件 + SPA 回退）。

只依赖标准库。启动：

    python server.py                # 默认 127.0.0.1:8765，自动开浏览器
    python server.py --port 9000 --no-browser
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import posixpath
import socket
import sys
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import altium_bridge as ab            # noqa: E402
from api import (                    # noqa: E402
    bridge_service,
    config_store,
    dialog_service,
    midpoint_service,
    overwrite_service,
    paths,
    snapshot_service,
    stackup_service,
    swap_service,
    coreslot_service,
    pourcut_service,
    winding_service,
    schport_service,
    schwire_service,
)

DEFAULT_PORT = 8765
DEFAULT_HOST = "127.0.0.1"

# ==================================================================== 路由
def _h_health(h, q, body):
    return {"ok": True, "app": "Altium 工具集", "version": "2.0",
            "bridge": bridge_service.status(),
            "config": paths.config_path()}


def _h_debug(h, q, body):
    """前端启动诊断上报：写到 %TEMP%\\altium_diag.json，便于无界面排查。"""
    try:
        import tempfile
        path = os.path.join(tempfile.gettempdir(), "altium_diag.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(body or {}, f, ensure_ascii=False, indent=2)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}
    return {"ok": True, "path": path}


def _h_config_get(h, q, body):
    return {"ok": True, "config": config_store.get_config()}


def _h_config_put(h, q, body):
    cfg = config_store.update_config(body or {})
    return {"ok": True, "config": cfg}


def _h_bridge_status(h, q, body):
    return {"ok": True, "status": bridge_service.status()}


def _h_bridge_close(h, q, body):
    bridge_service.close()
    return {"ok": True, "status": bridge_service.status()}


def _h_bridge_connect(h, q, body):
    return {"ok": True, "status": bridge_service.connect()}


def _h_coreslot_scan(h, q, body):
    return coreslot_service.scan()


def _h_coreslot_create(h, q, body):
    return coreslot_service.create((body or {}).get("ids") or [])


def _h_coreslot_delete(h, q, body):
    return coreslot_service.delete((body or {}).get("ids") or [])


def _h_pourcut_scan(h, q, body):
    return pourcut_service.scan()


def _h_pourcut_apply(h, q, body):
    return pourcut_service.apply()


def _h_schwire_scan(h, q, body):
    return schwire_service.scan()


def _h_schwire_apply(h, q, body):
    return schwire_service.apply(str((body or {}).get("action") or "add"),
                                (body or {}).get("items") or [])


def _h_schport_scan(h, q, body):
    return schport_service.scan()


def _h_schport_sync(h, q, body):
    return schport_service.sync(str((body or {}).get("child_path") or ""))


def _h_winding_scan(h, q, body):
    return winding_service.scan(bool((body or {}).get("include_vias")))


def _h_winding_apply(h, q, body):
    return winding_service.apply((body or {}).get("token") or "")


def _h_winding_mirror(h, q, body):
    return winding_service.mirror_copy(
        (body or {}).get("token") or "",
        bool((body or {}).get("exclude_top_bot")))


def _h_winding_read_axis(h, q, body):
    return winding_service.read_axis()


def _h_winding_read_shift(h, q, body):
    return winding_service.read_shift()


def _h_winding_operate(h, q, body):
    return winding_service.operate((body or {}).get("token") or "")


def _h_winding_translate(h, q, body):
    return winding_service.translate_copy((body or {}).get("token") or "")


def _h_winding_delete(h, q, body):
    return winding_service.delete((body or {}).get("layers") or [],
                                  (body or {}).get("token") or "")


def _h_pcb_stackup(h, q, body):
    return {"ok": True, "stackup": bridge_service.copper_layers()}


def _h_midpoint_meta(h, q, body):
    return {"ok": True, "meta": midpoint_service.meta()}


def _h_midpoint_read(h, q, body):
    orient = (body or {}).get("orient") or "v"
    return midpoint_service.read(orient)


def _h_midpoint_draw(h, q, body):
    b = body or {}
    orient = b.get("orient") or "v"
    try:
        start = float(b.get("start"))
        length = float(b.get("length"))
        width = float(b.get("width", 4.0))
    except (TypeError, ValueError):
        raise ValueError("参数格式错误：起点 / 长度 / 线宽 必须是数字。")
    if length <= 0:
        raise ValueError("长度必须为正数。")
    return midpoint_service.draw(orient, start, length, width,
                                 str(b.get("layer") or ""), bool(b.get("force")))


def _h_stackup_state(h, q, body):
    return stackup_service.STATE.state()


def _h_stackup_params(h, q, body):
    return stackup_service.STATE.set_params(body or {})


def _h_stackup_row_type(h, q, body):
    b = body or {}
    return stackup_service.STATE.set_row_type(int(b.get("index", -1)),
                                              str(b.get("type") or "P"))


def _h_stackup_row_oz(h, q, body):
    b = body or {}
    return stackup_service.STATE.set_row_oz(int(b.get("index", -1)),
                                            str(b.get("oz") or ""))


def _h_stackup_sync_cu(h, q, body):
    stackup_service.STATE.sync_cu()
    return stackup_service.STATE.state()


def _h_stackup_confirm(h, q, body):
    return stackup_service.STATE.confirm()


def _h_stackup_confirmed(h, q, body):
    return {"ok": True, **stackup_service.STATE.confirmed()}


def _h_stackup_templates(h, q, body):
    return stackup_service.STATE.list_templates((q.get("dir") or [None])[0])


def _h_stackup_template_open(h, q, body):
    path = str((body or {}).get("path") or "")
    if not path:
        raise ValueError("没有选择模板文件")
    res = stackup_service.STATE.open_template(path)
    return {**res, "state": stackup_service.STATE.state()}


def _h_stackup_default_out(h, q, body):
    return {"ok": True, "path": stackup_service.STATE.default_out_path()}


def _h_stackup_write(h, q, body):
    b = body or {}
    out = b.get("outPath") or None
    src = b.get("srcFile") if "srcFile" in b else None
    return stackup_service.STATE.write(out, src)

def _h_swap_validate(h, q, body):
    b = body or {}
    return swap_service.validate(str(b.get("a") or ""), str(b.get("b") or ""))


def _h_swap_generate(h, q, body):
    b = body or {}
    return swap_service.generate(str(b.get("a") or ""), str(b.get("b") or ""))


def _h_swap_preview(h, q, body):
    return swap_service.preview((q.get("path") or [""])[0])


def _h_overwrite_validate(h, q, body):
    b = body or {}
    return overwrite_service.validate(str(b.get("a") or ""), str(b.get("b") or ""))


def _h_overwrite_generate(h, q, body):
    b = body or {}
    return overwrite_service.generate(str(b.get("a") or ""), str(b.get("b") or ""),
                                      bool(b.get("repour")),
                                      str(b.get("copyMode") or "api"))


def _h_overwrite_preview(h, q, body):
    return overwrite_service.preview((q.get("path") or [""])[0])


def _h_script_open_dir(h, q, body):
    d = paths.script_out_dir("scripts", "altium_swap")
    os.makedirs(d, exist_ok=True)
    try:
        os.startfile(d)  # noqa: S606
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"打开目录失败: {e}")
    return {"ok": True, "dir": d}


def _h_snapshot_config(h, q, body):
    return {"ok": True, "config": snapshot_service.config()}


def _h_snapshot_config_put(h, q, body):
    return {"ok": True, "config": snapshot_service.save_config(body or {})}


def _h_snapshot_scan(h, q, body):
    return snapshot_service.scan((q.get("root") or [""])[0])


def _h_snapshot_plan(h, q, body):
    return snapshot_service.plan((q.get("root") or [""])[0])


def _h_snapshot_create(h, q, body):
    root = str((body or {}).get("root") or "")
    return {"ok": True, **snapshot_service.create(root)}


def _h_snapshot_browse(h, q, body):
    return {"ok": True, **snapshot_service.browse((q.get("path") or [""])[0])}


def _h_snapshot_reveal(h, q, body):
    return snapshot_service.reveal(str((body or {}).get("path") or ""))


def _h_dialog_folder(h, q, body):
    body = body or {}
    initial = str(body.get("dir") or (q.get("dir") or [""])[0] or "")
    return dialog_service.ask_folder(
        title=str(body.get("title") or "选择文件夹"),
        initialdir=initial,
    )


def _h_dialog_file(h, q, body):
    body = body or {}
    kind = str(body.get("kind") or "stackup")
    initial = str(body.get("dir") or "")
    if kind == "stackup":
        title = "选择叠层模板（.stackup）"
        initial = initial or paths.stackup_dir()
        patterns = [("叠层文件", "*.stackup"), ("所有文件", "*.*")]
    else:
        title = str(body.get("title") or "选择文件")
        patterns = None
    return dialog_service.ask_open(title=title, initialdir=initial, patterns=patterns)


ROUTES = {
    ("GET", "/api/health"): _h_health,
    ("POST", "/api/debug"): _h_debug,
    ("GET", "/api/config"): _h_config_get,
    ("PUT", "/api/config"): _h_config_put,
    ("GET", "/api/bridge/status"): _h_bridge_status,
    ("POST", "/api/bridge/close"): _h_bridge_close,
    ("POST", "/api/bridge/connect"): _h_bridge_connect,
    ("POST", "/api/coreslot/scan"): _h_coreslot_scan,
    ("POST", "/api/coreslot/create"): _h_coreslot_create,
    ("POST", "/api/coreslot/delete"): _h_coreslot_delete,
    ("POST", "/api/pourcut/scan"): _h_pourcut_scan,
    ("POST", "/api/pourcut/apply"): _h_pourcut_apply,
    ("POST", "/api/schwire/scan"): _h_schwire_scan,
    ("POST", "/api/schwire/apply"): _h_schwire_apply,
    ("POST", "/api/schport/scan"): _h_schport_scan,
    ("POST", "/api/schport/sync"): _h_schport_sync,
    ("POST", "/api/winding/scan"): _h_winding_scan,
    ("POST", "/api/winding/apply"): _h_winding_apply,
    ("POST", "/api/winding/mirror"): _h_winding_mirror,
    ("POST", "/api/winding/translate"): _h_winding_translate,
    ("POST", "/api/winding/read_axis"): _h_winding_read_axis,
    ("POST", "/api/winding/read_shift"): _h_winding_read_shift,
    ("POST", "/api/winding/operate"): _h_winding_operate,
    ("POST", "/api/winding/delete"): _h_winding_delete,
    ("GET", "/api/pcb/stackup"): _h_pcb_stackup,
    ("GET", "/api/midpoint/meta"): _h_midpoint_meta,
    ("POST", "/api/midpoint/read"): _h_midpoint_read,
    ("POST", "/api/midpoint/draw"): _h_midpoint_draw,
    ("GET", "/api/stackup/state"): _h_stackup_state,
    ("POST", "/api/stackup/params"): _h_stackup_params,
    ("POST", "/api/stackup/row-type"): _h_stackup_row_type,
    ("POST", "/api/stackup/row-oz"): _h_stackup_row_oz,
    ("POST", "/api/stackup/sync-cu"): _h_stackup_sync_cu,
    ("POST", "/api/stackup/confirm"): _h_stackup_confirm,
    ("GET", "/api/stackup/confirmed"): _h_stackup_confirmed,
    ("GET", "/api/stackup/templates"): _h_stackup_templates,
    ("POST", "/api/stackup/template/open"): _h_stackup_template_open,
    ("GET", "/api/stackup/default-out-path"): _h_stackup_default_out,
    ("POST", "/api/stackup/write"): _h_stackup_write,
    ("POST", "/api/swap/validate"): _h_swap_validate,
    ("POST", "/api/swap/generate"): _h_swap_generate,
    ("GET", "/api/swap/preview"): _h_swap_preview,
    ("POST", "/api/overwrite/validate"): _h_overwrite_validate,
    ("POST", "/api/overwrite/generate"): _h_overwrite_generate,
    ("GET", "/api/overwrite/preview"): _h_overwrite_preview,
    ("POST", "/api/script/open-dir"): _h_script_open_dir,
    ("GET", "/api/snapshot/config"): _h_snapshot_config,
    ("PUT", "/api/snapshot/config"): _h_snapshot_config_put,
    ("GET", "/api/snapshot/scan"): _h_snapshot_scan,
    ("GET", "/api/snapshot/plan"): _h_snapshot_plan,
    ("POST", "/api/snapshot/create"): _h_snapshot_create,
    ("GET", "/api/snapshot/browse"): _h_snapshot_browse,
    ("POST", "/api/snapshot/reveal"): _h_snapshot_reveal,
    ("POST", "/api/dialog/folder"): _h_dialog_folder,
    ("POST", "/api/dialog/file"): _h_dialog_file,
}

# ==================================================================== 服务
class Handler(BaseHTTPRequestHandler):
    server_version = "AltiumTools/2.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):   # 静默（只在控制台打印关键信息）
        pass

    def _send_json(self, code: int, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods",
                         "GET,POST,PUT,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _read_body(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n <= 0:
            return {}
        try:
            data = json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def _handle(self, method: str):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        q = parse_qs(parsed.query)

        if path.startswith("/api/"):
            fn = ROUTES.get((method, path))
            if fn is None:
                self._send_json(404, {"ok": False, "error": "接口不存在",
                                      "path": path})
                return
            try:
                body = self._read_body() if method in ("POST", "PUT") else {}
                self._send_json(200, fn(self, q, body))
            except ab.BridgeTimeout as e:
                self._send_json(504, {"ok": False,
                                      "error": f"{type(e).__name__}: {e}",
                                      "hint": ab.BridgeTimeout.HINT})
            except ab.BridgeError as e:
                self._send_json(502, {"ok": False,
                                      "error": f"{type(e).__name__}: {e}"})
            except ValueError as e:
                self._send_json(400, {"ok": False, "error": str(e)})
            except FileNotFoundError as e:
                self._send_json(404, {"ok": False, "error": str(e)})
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                self._send_json(500, {"ok": False,
                                      "error": f"{type(e).__name__}: {e}"})
            return

        self._serve_static(path)

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PUT(self):
        self._handle("PUT")

    def do_DELETE(self):
        self._handle("DELETE")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _serve_static(self, path: str):
        dist = paths.web_dist()
        if path in ("/", ""):
            path = "/index.html"
        rel = posixpath.normpath(path).lstrip("/")
        target = os.path.join(dist, rel.replace("/", os.sep))
        if not os.path.abspath(target).startswith(os.path.abspath(dist)):
            self._send_json(403, {"ok": False, "error": "非法路径"})
            return
        if not os.path.isfile(target):
            target = os.path.join(dist, "index.html")      # SPA 回退
        if not os.path.isfile(target):
            body = ("<h1>前端尚未构建</h1><p>请在 web/ 目录执行 "
                    "<code>npm install &amp;&amp; npm run build</code>。</p>"
                    ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        ctype = mimetypes.guess_type(target)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",
                                                  "application/json"):
            ctype += "; charset=utf-8"
        with open(target, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _free_port(host: str, port: int) -> int:
    for p in range(port, port + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, p))
                return p
            except OSError:
                continue
    return port


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Altium 工具集（oink-ui 版）")
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--no-browser", action="store_true",
                    help="不自动打开浏览器")
    ap.add_argument("--strict-port", action="store_true",
                    help="端口被占用时直接退出（不自动顺延）；桌面版用")
    args = ap.parse_args(argv)

    port = args.port if args.strict_port else _free_port(args.host, args.port)

    server_cls = ThreadingHTTPServer
    if args.strict_port:
        # 严格模式：不允许复用端口，Windows 上否则第二个实例会「抢绑」同一端口
        class _StrictServer(ThreadingHTTPServer):
            allow_reuse_address = False

        server_cls = _StrictServer

    try:
        httpd = server_cls((args.host, port), Handler)
    except OSError as e:
        print(f"[ERROR] 端口 {args.host}:{port} 无法绑定：{e}",
              file=sys.stderr)
        print("        （可能有另一个 Altium 工具集实例正在运行）",
              file=sys.stderr)
        return 2

    url = f"http://{args.host}:{port}/"
    print("=" * 58)
    print("  Altium 工具集（oink-ui 版）已启动")
    print(f"  地址：{url}")
    if os.environ.get("ALTUM_HOME"):
        print("  模式：桌面版托管（关掉窗口即退出）")
    else:
        print("  关闭：在本窗口按 Ctrl+C")
    print("=" * 58)

    # 原生文件对话框（tkinter 专用线程）——浏览器拿不到本机路径时由后端弹窗
    try:
        dialog_service.start()
    except Exception as exc:  # noqa: BLE001
        print(f"  （文件对话框未就绪：{exc}）")

    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n正在退出 …")
    finally:
        bridge_service.close()
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
