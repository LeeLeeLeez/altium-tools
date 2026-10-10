#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Altium (eda-agent) 桥接访问层 —— 供 GUI 与命令行脚本共用。

设计
----
eda-agent 是一个 stdio MCP server（`eda-agent.exe --no-dashboard serve`）。
本模块以子进程 + JSON-RPC 方式驱动它，**不依赖宿主的工具调用通道**，
因此 GUI / 脚本 / 定时任务都能独立运行。

接口
----
    cli = AltiumBridge()                  # 连接（懒启动子进程）
    cli.selected_tracks()                 # 读当前选中的 track 列表
    cli.query_tracks(layer=..., x1=...)   # 按过滤条件查 track
    cli.place_tracks([...])               # 批量放置 track
    cli.delete_track(x, y, layer)         # 删最近的一条 track
    cli.close()                           # 收尾

🔴 本机实测的铁律（写死在代码里，别再踩）
------------------------------------------
1. **坐标量化 = 截断（floor），不是四舍五入**
     提交 13994.8288 -> 落盘 13994（不是 13995）
     提交 14060.3199 -> 落盘 14060
     提交 13720.8199 -> 落盘 13720
   => 验证时两种候选都要查，否则会把成功误报为失败。见 `quantize_mil()`。

2. **`placed` 回执不可信**，只是「提交成功」。必须另起一次读回验证。

3. **`pcb_place_tracks` 是纯追加、无幂等** => 重跑必产生重合线。
   落笔前先查目标位置是否已有同规格线（`find_duplicate()`）。

4. **删除回执里的 `distance_mils` 只是"命中距离"**，不代表删对了对象。
   删完必须按坐标过滤回读复核。

5. **AD 弹模态时脚本引擎会被堵死** => 桥接超时/无响应。
   用 Win32 侧工具（app_list_open_dialogs / app_press_dialog_button）清理，
   但**关掉模态会连带终止 StartMCPServer 脚本**，需用户重开轮询。
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field

# ------------------------------------------------------------------ 配置
EDA_AGENT_EXE = r"E:\AI_model\eda-agent\.venv\Scripts\eda-agent.exe"
EDA_AGENT_ARGS = ["--no-dashboard", "serve"]

# Windows: 不让子进程弹控制台窗口。eda-agent.exe 是控制台程序，从 pythonw.exe
# （无控制台）启动它时系统会自动新建控制台窗口。CREATE_NO_WINDOW 抑制该行为。
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


class BridgeError(RuntimeError):
    """桥接调用失败（工具报错 / 返回异常）。"""


class BridgeTimeout(RuntimeError):
    """桥接无响应 —— 通常是 AD 弹了模态，或轮询循环已停。"""

    HINT = (
        "AD 可能弹了模态对话框，或 MCP 轮询循环已停止。处理办法：\n"
        "  1) 用 app_list_open_dialogs 查看并关闭对话框；\n"
        "  2) 在 AD 里重开轮询：File > Run Script... > Altium_API >\n"
        "     Dispatcher.pas > StartMCPServer > Run"
    )


def quantize_mil(v: float) -> int:
    """把浮点 mil 量化成桥接实际会写入的整数。

    🔴 实测为**截断**而非四舍五入：13994.8288 -> 13994。
    """
    return int(v)


def quantize_candidates(v: float) -> list[int]:
    """量化候选值（截断优先，再给四舍五入值），用于读回验证时避免误判。"""
    out: list[int] = []
    for c in (int(v), int(round(v))):
        if c not in out:
            out.append(c)
    return out


# ------------------------------------------------------------------ MCP 客户端
class MCPClient:
    """极简 MCP stdio 客户端（JSON-RPC 2.0）。"""

    def __init__(self, exe: str = EDA_AGENT_EXE, args: list[str] | None = None,
                 timeout: float = 60.0):
        if not os.path.exists(exe):
            raise BridgeError(f"找不到 MCP 可执行文件: {exe}")
        self.timeout = timeout
        self._id = 0
        self._lock = threading.Lock()
        self.proc = subprocess.Popen(
            [exe, *(args if args is not None else EDA_AGENT_ARGS)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
            bufsize=1,
            # 🔴 eda-agent.exe 是**控制台程序**。从无控制台的 GUI
            # （pythonw.exe）启动它时，Windows 会给子进程**新建一个控制台窗口**
            # —— 表现为"一点「读取选中对象」就弹黑框"。
            # CREATE_NO_WINDOW 让它静默运行（std 流已经全是 PIPE，不需要控制台）。
            creationflags=_NO_WINDOW,
        )
        self._handshake()

    # -- 底层 ---------------------------------------------------------
    def _send(self, obj: dict) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(obj) + "\n")
        self.proc.stdin.flush()

    def _read_reply(self, want_id: int) -> dict:
        assert self.proc.stdout is not None
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            line = self.proc.stdout.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("id") == want_id:
                return msg
        raise BridgeTimeout(f"no reply for id={want_id} within {self.timeout}s")

    def call(self, method: str, params: dict | None = None):
        with self._lock:
            self._id += 1
            mid = self._id
            self._send({"jsonrpc": "2.0", "id": mid, "method": method,
                        "params": params or {}})
            reply = self._read_reply(mid)
        if "error" in reply:
            raise BridgeError(f"{method} failed: {reply['error']}")
        return reply.get("result")

    def notify(self, method: str, params: dict | None = None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def _handshake(self) -> None:
        self.call("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "altium_gui", "version": "1.0"},
        })
        self.notify("notifications/initialized")

    # -- 工具调用 -----------------------------------------------------
    def tool(self, name: str, arguments: dict) -> dict:
        """调用一个 MCP 工具，并把 text content 解析成 dict 返回。"""
        res = self.call("tools/call", {"name": name, "arguments": arguments})
        parts: list[str] = []
        if isinstance(res, dict):
            for item in res.get("content", []):
                if item.get("type") == "text":
                    parts.append(item.get("text", ""))
        blob = "\n".join(parts).strip()
        if not blob:
            return {}
        try:
            return json.loads(blob)
        except json.JSONDecodeError:
            return {"_raw": blob}

    def close(self) -> None:
        try:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass


# ------------------------------------------------------------------ 数据模型
@dataclass
class Track:
    layer: str
    x1: float
    y1: float
    x2: float
    y2: float
    width: float = 0.0
    object_id: str = ""

    @property
    def is_vertical(self) -> bool:
        return abs(self.x1 - self.x2) < 1e-6

    @property
    def is_horizontal(self) -> bool:
        return abs(self.y1 - self.y2) < 1e-6

    def as_row(self) -> str:
        d = "竖直" if self.is_vertical else ("水平" if self.is_horizontal else "斜线")
        ln = ((self.x2 - self.x1) ** 2 + (self.y2 - self.y1) ** 2) ** 0.5
        return (f"{self.layer:<12} {d}  "
                f"({self.x1:g}, {self.y1:g}) -> ({self.x2:g}, {self.y2:g})  "
                f"长 {ln:.2f} mil  宽 {self.width:g}")


# ------------------------------------------------------------------ 桥接封装
class AltiumBridge:
    """面向本项目的桥接封装：把常用操作 + 本机铁律打包。"""

    def __init__(self, exe: str = EDA_AGENT_EXE, timeout: float = 60.0):
        self._mcp = MCPClient(exe, timeout=timeout)

    # -- 生命周期 -----------------------------------------------------
    def close(self) -> None:
        self._mcp.close()

    def __enter__(self) -> "AltiumBridge":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- 文档 ---------------------------------------------------------
    # ------------------------------------------------------------ 通用透传
    def tool(self, name: str, arguments: dict | None = None) -> dict:
        """直接调用任意 eda-agent 工具（本文件没包成语义方法的那些）。"""
        return self._mcp.tool(name, arguments or {})

    def layer_stackup(self) -> dict:
        """读当前 PCB 的真实叠层：按 order 排列的各层（含层名与铜厚）。

        返回 {'layers': [{'name','order','copper_thickness_mils',
                          'dielectric_type','dielectric_height_mils',
                          'dielectric_constant'}, ...], 'layer_count', 'board_name'}
        """
        return self._mcp.tool("pcb_get_layer_stackup", {})

    def active_document(self) -> dict:
        return self._mcp.tool("app_get_active_document", {})

    # -- 选中 ---------------------------------------------------------
    def selected_objects(self, properties: str = "ObjectId,Layer,X1,Y1,X2,Y2,Width") -> list[dict]:
        return self._mcp.tool("pcb_get_selected_objects",
                              {"properties": properties}).get("objects", [])

    def selected_tracks(self) -> list[Track]:
        return [_to_track(o) for o in self.selected_objects()]

    def deselect_all(self) -> dict:
        return self._mcp.tool("obj_deselect_all", {})

    def select_tracks(self, filter_: str) -> dict:
        """按过滤条件选中 track。⚠️ 选择是**累加**的（不会替换）。"""
        return self._mcp.tool("obj_select",
                              {"object_type": "eTrackObject", "filter": filter_})

    # -- 查询 ---------------------------------------------------------
    def query_tracks(self, layer: str | None = None, x1: float | None = None,
                     y1: float | None = None, limit: int = 0) -> list[Track]:
        conds = []
        if layer:
            conds.append(f"Layer={layer}")
        if x1 is not None:
            conds.append(f"X1={quantize_mil(x1)}")
        if y1 is not None:
            conds.append(f"Y1={quantize_mil(y1)}")
        return [_to_track(o) for o in self._mcp.tool("obj_query", {
            "object_type": "eTrackObject",
            "properties": "ObjectId,Layer,X1,Y1,X2,Y2,Width",
            "scope": "active_doc",
            "filter": "|".join(conds),
            "limit": limit,
        }).get("objects", [])]

    # -- 写入 ---------------------------------------------------------
    def place_tracks(self, tracks: list[dict]) -> dict:
        return self._mcp.tool("pcb_place_tracks", {"tracks": tracks})

    def place_vline(self, x: float, y1: float, y2: float,
                    layer: str, width: float = 4.0) -> dict:
        return self.place_tracks([{
            "x1": x, "y1": y1, "x2": x, "y2": y2,
            "width": width, "layer": layer,
        }])

    def place_hline(self, y: float, x1: float, x2: float,
                    layer: str, width: float = 4.0) -> dict:
        """水平线：Y 固定，X 从 x1 到 x2。"""
        return self.place_tracks([{
            "x1": x1, "y1": y, "x2": x2, "y2": y,
            "width": width, "layer": layer,
        }])

    def find_duplicate_h(self, y: float, x1: float, x2: float,
                         layer: str) -> list[Track]:
        """目标位置是否已有同规格水平线（防重）。"""
        hits = []
        for qy in quantize_candidates(y):
            for t in self.query_tracks(layer=layer, y1=qy, limit=50):
                if (quantize_mil(t.x1) == quantize_mil(x1)
                        and quantize_mil(t.x2) == quantize_mil(x2)):
                    hits.append(t)
            if hits:
                break
        return hits

    def verify_hline(self, y: float, x1: float, x2: float,
                     layer: str) -> tuple[Track | None, list[Track]]:
        """读回验证：返回 (命中的线, 该 Y 上的全部线)。

        🔴 用「截断/四舍五入」两种候选查，避免把成功误报成失败。
        """
        all_hits: list[Track] = []
        found: Track | None = None
        for qy in quantize_candidates(y):
            hits = self.query_tracks(layer=layer, y1=qy, limit=50)
            if not hits:
                continue
            all_hits = hits
            for t in hits:
                if (quantize_mil(t.x1) == quantize_mil(x1)
                        and quantize_mil(t.x2) == quantize_mil(x2)):
                    found = t
                    break
            break
        return found, all_hits

    def delete_track(self, x: float, y: float, layer: str) -> dict:
        return self._mcp.tool("pcb_delete_object", {
            "x": quantize_mil(x), "y": quantize_mil(y),
            "layer": layer, "object_type": "track",
        })

    # -- 验证（关键） -------------------------------------------------
    def find_duplicate(self, x: float, y1: float, y2: float,
                       layer: str) -> list[Track]:
        """目标位置是否已有同规格竖线（防重）。"""
        hits = []
        for qx in quantize_candidates(x):
            for t in self.query_tracks(layer=layer, x1=qx, limit=50):
                if (quantize_mil(t.y1) == quantize_mil(y1)
                        and quantize_mil(t.y2) == quantize_mil(y2)):
                    hits.append(t)
            if hits:
                break
        return hits

    def verify_vline(self, x: float, y1: float, y2: float,
                     layer: str) -> tuple[Track | None, list[Track]]:
        """读回验证：返回 (命中的线, 该 X 上的全部线)。

        🔴 用「截断/四舍五入」两种候选查，避免把成功误报成失败。
        """
        all_hits: list[Track] = []
        found: Track | None = None
        for qx in quantize_candidates(x):
            hits = self.query_tracks(layer=layer, x1=qx, limit=50)
            if not hits:
                continue
            all_hits = hits
            for t in hits:
                if (quantize_mil(t.y1) == quantize_mil(y1)
                        and quantize_mil(t.y2) == quantize_mil(y2)):
                    found = t
                    break
            break
        return found, all_hits


def _to_track(o: dict) -> Track:
    def f(k, d=0.0):
        v = o.get(k, "")
        try:
            return float(v)
        except (TypeError, ValueError):
            return d
    return Track(
        layer=str(o.get("Layer", "")),
        x1=f("X1"), y1=f("Y1"), x2=f("X2"), y2=f("Y2"),
        width=f("Width"), object_id=str(o.get("ObjectId", "")),
    )


# ------------------------------------------------------------------ 几何
def midpoint_of_two_horizontals(tracks: list[Track]) -> float:
    """两条水平线的 Y 中点；不满足条件时抛 ValueError（消息可直接显示给用户）。"""
    if len(tracks) != 2:
        raise ValueError(f"需要恰好选中 2 条线，当前选中 {len(tracks)} 个对象。")
    for t in tracks:
        if not t.is_horizontal:
            raise ValueError(
                f"选中对象不是水平线：({t.x1:g}, {t.y1:g}) -> ({t.x2:g}, {t.y2:g})")
    layers = {t.layer for t in tracks}
    if len(layers) != 1:
        raise ValueError(f"两条线不在同一层：{sorted(layers)}")
    if abs(tracks[0].y1 - tracks[1].y1) < 1e-9:
        raise ValueError(f"两条线 Y 相同（{tracks[0].y1:g}），无法取中点。")
    return (tracks[0].y1 + tracks[1].y1) / 2.0


def midpoint_of_two_verticals(tracks: list[Track]) -> float:
    """两条竖线的 X 中点；不满足条件时抛 ValueError（消息可直接显示给用户）。"""
    if len(tracks) != 2:
        raise ValueError(f"需要恰好选中 2 条线，当前选中 {len(tracks)} 个对象。")
    for t in tracks:
        if not t.is_vertical:
            raise ValueError(
                f"选中对象不是竖直线：({t.x1:g}, {t.y1:g}) -> ({t.x2:g}, {t.y2:g})")
    layers = {t.layer for t in tracks}
    if len(layers) != 1:
        raise ValueError(f"两条线不在同一层：{sorted(layers)}")
    if abs(tracks[0].x1 - tracks[1].x1) < 1e-9:
        raise ValueError(f"两条线 X 相同（{tracks[0].x1:g}），无法取中点。")
    return (tracks[0].x1 + tracks[1].x1) / 2.0
