"""配置持久化 —— 读-合并-写 + 原子落盘。

语义与旧版 `gui_style.load_json_cfg / save_json_cfg` 完全一致：

* 读：default 打底 → 磁盘内容覆盖同名键；文件不存在 / 损坏 / 不是 dict 都静默回退；
* 写：先写 `.tmp` 再 `os.replace` 原子替换，失败返回 False 不抛异常；
* **所有页面共用同一个 JSON ⇒ 必须读-合并-写**，否则后写的会把先写的整段覆盖掉。
"""

from __future__ import annotations

import json
import os
import threading

from . import paths

_LOCK = threading.RLock()

# 首次运行补全用的默认值（键名与旧版 Tkinter 保持一致）
DEFAULTS: dict = {
    # 画中点短线（旧版单 tab 键）
    "y0": 6337.0,
    "length": 39.0,
    "width": 4.0,
    "layer": "",
    # 画中点短线（新键）
    "mv_start": "6337.0",
    "mv_len": "39.0",
    "mv_width": "4.0",
    "mv_layer": "",
    "mh_start": "6337.0",
    "mh_len": "39.0",
    "mh_width": "4.0",
    "mh_layer": "",
    # 叠层设计
    "Lp": "8",
    "Ls": "8",
    "Lgnd": "2",
    "gnd": "",
    "Np": "8",
    "Ns": "4",
    "ozP": "2",
    "ozS": "2",
    "ozG": "4",
    "dPP": "200",
    "dSS": "300",
    "dPS": "150",
    "rect": "fullwave",
    "cumode": "global",
    "stk_confirmed": [],
    # 层交换 / 叠层覆盖
    "swap_a": "",
    "swap_b": "",
    "ow_a": "",
    "ow_b": "",
    # 工程快照
    "snap_root": "",
    "snap_roots": [],
    "snap_last_dst": "",
}


def load_json_cfg(path: str, default: dict | None = None) -> dict:
    """读配置 —— default 打底，磁盘内容覆盖同名键；出错静默回退。"""
    base = dict(default or {})
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            base.update(d)
    except Exception:
        pass
    return base


def save_json_cfg(path: str, data: dict) -> bool:
    """写配置 —— 原子替换；失败返回 False 不抛异常。"""
    try:
        d = os.path.dirname(os.path.abspath(path))
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except Exception:
        return False


def get_config() -> dict:
    """整份配置（默认值 + 磁盘内容）。"""
    with _LOCK:
        return load_json_cfg(paths.config_path(), DEFAULTS)


def update_config(patch: dict) -> dict:
    """读-合并-写，返回落盘后的整份配置。"""
    with _LOCK:
        cfg = load_json_cfg(paths.config_path(), {})
        if isinstance(patch, dict):
            cfg.update(patch)
        save_json_cfg(paths.config_path(), cfg)
        return cfg
