"""画中点短线 —— 纯逻辑（读板子 / 画线 / 读回验证）。

移植自旧版 `midpoint_tab.py` 的 `on_read` / `on_draw`，把 Tkinter 的
`_run` + `_pump` 线程模型换成了「HTTP 请求线程直接跑」：
MCPClient 本身就是同步阻塞的，而 HTTP 服务器每个请求都在自己的线程里。
"""

from __future__ import annotations

import altium_bridge as ab

from . import bridge_service

LEN_PRESETS = (
    ("39 mil  (0.9906 mm)", 39.0),
    ("40 mil  (1.0160 mm)", 40.0),
    ("19.685 mil (0.5 mm)", 19.685),
    ("39.370079 mil (1 mm 精确值)", 39.370079),
)

LAYER_CHOICES = ["", "Mechanical1", "Mechanical2", "Mechanical13",
                 "KeepOutLayer", "TopLayer", "BottomLayer"]


def spec(orient: str) -> dict:
    """一个方向一套文案与配置键。"""
    if orient == "v":
        return {
            "orient": "v",
            "tab": "画竖直短线",
            "title": "在两条竖线的中点画竖直短线",
            "hint": "选中两条竖线 → 读取 → 画线",
            "require": "必须恰好 2 条竖直 track（同一层）",
            "startLabel": "起点 Y (mil)",
            "button": "画中点短线",
            "word": "竖直线",
            "keys": ["mv_start", "mv_len", "mv_width", "mv_layer", "mv_force"],
            "legacy": ["y0", "length", "width", "layer"],
            "defaults": ["6337.0", "39.0", "4.0", ""],
        }
    return {
        "orient": "h",
        "tab": "画水平短线",
        "title": "在两条水平线的中点画水平短线",
        "hint": "选中两条水平线 → 读取 → 画线",
        "require": "必须恰好 2 条水平 track（同一层）",
        "startLabel": "起点 X (mil)",
        "button": "画中点短线",
        "word": "水平线",
        "keys": ["mh_start", "mh_len", "mh_width", "mh_layer", "mh_force"],
        "legacy": ["h_x0", "h_length", "h_width", "h_layer"],
        "defaults": ["6337.0", "39.0", "4.0", ""],
    }


def meta() -> dict:
    return {
        "presets": [{"label": lbl, "value": val} for lbl, val in LEN_PRESETS],
        "layers": LAYER_CHOICES,
        "specs": {"v": spec("v"), "h": spec("h")},
    }


def _track_dict(t) -> dict:
    return {
        "layer": t.layer, "x1": t.x1, "y1": t.y1,
        "x2": t.x2, "y2": t.y2, "width": t.width,
        "objectId": t.object_id,
        "vertical": t.is_vertical, "horizontal": t.is_horizontal,
        "row": t.as_row(),
    }


def read(orient: str) -> dict:
    """读取当前选中对象 + 算中点。"""
    br = bridge_service.get_bridge()
    vertical = orient == "v"
    doc = br.active_document()
    tracks = br.selected_tracks()
    objs = br.selected_objects()

    lines = [f"活动文档：{doc.get('file_name') or '(无)'}",
             f"选中对象：{len(objs)} 个"]
    for t in tracks:
        lines.append("  " + t.as_row())
    if len(objs) != len(tracks):
        lines.append(f"  （其中 {len(objs) - len(tracks)} 个不是 track）")

    want = "竖直线" if vertical else "水平线"
    ok = (all(t.is_vertical for t in tracks) if vertical
          else all(t.is_horizontal for t in tracks))
    mid = None
    if len(tracks) == 2 and ok:
        try:
            mid = (ab.midpoint_of_two_verticals(tracks) if vertical
                   else ab.midpoint_of_two_horizontals(tracks))
            axis = "X" if vertical else "Y"
            lines.append(f"→ 中点 {axis} = {mid:.4f} mil  "
                         f"（量化后 {ab.quantize_mil(mid)}）")
        except ValueError as e:
            lines.append(f"→ {e}")
    elif len(tracks) == 2:
        lines.append(f"→ 选中的不全是{want}，无法取中点。")
    else:
        lines.append(f"→ 需要恰好 2 条{want}。")

    return {
        "ok": True,
        "doc": doc.get("file_name") or "(无)",
        "objects": len(objs),
        "tracks": [_track_dict(t) for t in tracks],
        "lines": lines,
        "mid": mid,
    }


def draw(orient: str, start: float, length: float, width: float,
         layer_override: str = "", force: bool = False) -> dict:
    """在中点画线 —— 先防重，再落笔，最后读回验证。

    铁律（来自 altium_bridge 头部注释）：
      * `pcb_place_tracks` **无幂等** ⇒ 落笔前必须按坐标防重；
      * 桥接回执不可信 ⇒ 落笔后另起一次读回验证。
    """
    br = bridge_service.get_bridge()
    vertical = orient == "v"
    end = start + length
    out: list[str] = []

    tracks = br.selected_tracks()
    if vertical:
        mid = ab.midpoint_of_two_verticals(tracks)     # 校验在内部
        layer = (layer_override or "").strip() or tracks[0].layer
        out.append(f"源线 X：{tracks[0].x1:g} / {tracks[1].x1:g}")
        out.append(f"中点 X：{mid:.4f} mil（量化后 {ab.quantize_mil(mid)}）")
        out.append(f"目标线：({mid:.4f}, {start:g}) -> ({mid:.4f}, {end:g})  "
                   f"layer={layer} width={width:g} len={length:g} mil")
        dup = br.find_duplicate(mid, start, end, layer)
        if dup and not force:
            out.append(f"⚠️ 目标位置已存在 {len(dup)} 条同规格线，已停止"
                       f"（勾选「允许重合」可强制落笔）。")
            return {"ok": True, "skipped": True, "lines": out,
                    "tracks": [_track_dict(t) for t in tracks]}
        res = br.place_vline(mid, start, end, layer, width)
        out.append(f"放置回执：placed={res.get('placed')} "
                   f"failed={res.get('failed')}")
        found, hits = br.verify_vline(mid, start, end, layer)
        axis_txt = f"X={ab.quantize_candidates(mid)}"
        ctr = (found.x1 - mid) if found else 0.0
    else:
        mid = ab.midpoint_of_two_horizontals(tracks)
        layer = (layer_override or "").strip() or tracks[0].layer
        out.append(f"源线 Y：{tracks[0].y1:g} / {tracks[1].y1:g}")
        out.append(f"中点 Y：{mid:.4f} mil（量化后 {ab.quantize_mil(mid)}）")
        out.append(f"目标线：({start:g}, {mid:.4f}) -> ({end:g}, {mid:.4f})  "
                   f"layer={layer} width={width:g} len={length:g} mil")
        dup = br.find_duplicate_h(mid, start, end, layer)
        if dup and not force:
            out.append(f"⚠️ 目标位置已存在 {len(dup)} 条同规格线，已停止"
                       f"（勾选「允许重合」可强制落笔）。")
            return {"ok": True, "skipped": True, "lines": out,
                    "tracks": [_track_dict(t) for t in tracks]}
        res = br.place_hline(mid, start, end, layer, width)
        out.append(f"放置回执：placed={res.get('placed')} "
                   f"failed={res.get('failed')}")
        found, hits = br.verify_hline(mid, start, end, layer)
        axis_txt = f"Y={ab.quantize_candidates(mid)}"
        ctr = (found.y1 - mid) if found else 0.0

    out.append(f"读回验证：{axis_txt} 命中 {len(hits)} 条")
    for t in hits:
        mark = "  <== 本次目标" if (found and t is found) else ""
        out.append("  " + t.as_row() + mark)
    if found:
        out.append(f"✅ 验证通过：({found.x1:g}, {found.y1:g}) -> "
                   f"({found.x2:g}, {found.y2:g})   量化误差 {ctr:+.4f} mil")
    else:
        out.append("❌ 未找到与预期坐标匹配的线，请人工核查。")

    return {
        "ok": True,
        "skipped": False,
        "lines": out,
        "placed": res if isinstance(res, dict) else {},
        "verified": {"found": bool(found), "hits": len(hits)},
        "tracks": [_track_dict(t) for t in tracks],
    }
