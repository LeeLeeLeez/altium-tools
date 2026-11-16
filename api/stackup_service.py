"""叠层设计 —— 纯逻辑状态机（参数 → 序列 → 计算 → 确认 → 写出 .stackup）。

移植自旧版 `stackup_page.py`：那里一半是 UI、一半是状态机，
这里只保留状态机与文件读写，界面交给 React。

对外只暴露一个进程级单例 `STATE`，页面之间通过它共享
「已确认的层名」（层交换页 / 叠层覆盖页都要读）。
"""

from __future__ import annotations

import os
import threading
import time

import stackup_build as BK
import stackup_design as D
import stackup_file as SF

from . import config_store
from . import paths

# 类型 → 色块颜色
TYPE_COLOR = {
    "P": "#2563EB",   # 原边 蓝
    "S": "#16A34A",   # 副边 绿
    "A": "#0EA5E9",   # 副边A 青
    "B": "#14B8A6",   # 副边B 青绿
    "G": "#6B7280",   # GND 灰
}
TYPE_LABEL = {"P": "P 原边", "S": "S 副边", "A": "A 副边A",
               "B": "B 副边B", "G": "G GND"}
TYPE_FROM_LABEL = {v: k for k, v in TYPE_LABEL.items()}
CU_CHOICES = [D.cu_oz_text(x) for x in D.CU_OZ_OPTIONS]

PARAM_KEYS = ("Lp", "Ls", "Lgnd", "gnd", "Np", "Ns",
              "ozP", "ozS", "ozG", "dPP", "dSS", "dPS")


def _fmt_mm(um: float) -> str:
    return f"{um / 1000.0:.4f}"


class StackupState:
    """叠层设计的全部状态。线程安全（HTTP 请求可能并发）。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.params: dict = {}
        self.rect = "fullwave"
        self.cumode = "global"
        self.seq: list = []
        self.cu_oz: list = []
        self.confirmed_names = None
        self.confirmed_seq = None
        self.confirm_label = "未确认 —— 点「确认叠层」固定当前叠层"
        self.src_file = None
        self.tpl_copper = 0
        self.tpl_dielectric = 0
        self.last_error = None
        self._result = None
        self._pending_confirm = None
        self.load_cfg()
        self.rebuild(keep_edits=False)

    # ================================================================ 配置
    def load_cfg(self) -> None:
        cfg = config_store.get_config()
        for k in PARAM_KEYS:
            self.params[k] = str(cfg.get(k, config_store.DEFAULTS.get(k, "")))
        self.rect = str(cfg.get("rect") or "fullwave")
        self.cumode = str(cfg.get("cumode") or "global")
        saved = list(cfg.get("stk_confirmed") or [])
        self._pending_confirm = saved or None

    def save_cfg(self) -> None:
        patch = {k: self.params.get(k, "") for k in PARAM_KEYS}
        patch["rect"] = self.rect
        patch["cumode"] = self.cumode
        patch["stk_confirmed"] = list(self.confirmed_names or [])
        config_store.update_config(patch)

    # ================================================================ 参数
    def _num(self, key, default=0.0) -> float:
        try:
            return float(self.params.get(key))
        except (TypeError, ValueError):
            return default

    def _int(self, key, default=0) -> int:
        try:
            return int(float(self.params.get(key)))
        except (TypeError, ValueError):
            return default

    def _p(self) -> dict:
        return dict(
            Lp=max(0, self._int("Lp", 8)),
            Ls=max(0, self._int("Ls", 8)),
            Lgnd=max(0, self._int("Lgnd", 2)),
            gnd=str(self.params.get("gnd", "")).strip(),
            rect=self.rect,
            Np=self._num("Np", 32),
            Ns=self._num("Ns", 4),
            cumode=self.cumode,
            ozP=self._num("ozP", 2) or 2.0,
            ozS=self._num("ozS", 2) or 2.0,
            ozG=self._num("ozG", 4) or 4.0,
            dPP=self._num("dPP", 200),
            dSS=self._num("dSS", 300),
            dPS=self._num("dPS", 150),
        )

    def set_params(self, patch: dict) -> dict:
        """改参数 → 重建序列 → 重算。"""
        with self._lock:
            for k, v in (patch or {}).items():
                if k in PARAM_KEYS:
                    self.params[k] = str(v)
                elif k == "rect":
                    self.rect = str(v)
                elif k == "cumode":
                    self.cumode = str(v)
            self.rebuild(keep_edits=True)
            self.save_cfg()
            return self.state()

    # ================================================================ 序列
    def rebuild(self, keep_edits: bool = True) -> dict:
        p = self._p()
        old_oz = list(self.cu_oz)
        try:
            seq = D.build_seq(p["Lp"], p["Ls"], p["Lgnd"], p["rect"], p["gnd"])
        except ValueError as e:
            self.last_error = str(e)
            return {"ok": False, "error": str(e)}
        self.last_error = None
        self.seq = seq
        # 「按原副边」模式下逐层铜厚由全局值推导，不保留旧编辑；
        # 「逐层单独指定」模式下才保留用户手改过的铜厚。
        if keep_edits and p["cumode"] == "perlayer" and len(old_oz) == len(seq):
            self.cu_oz = list(old_oz)
        else:
            cu = D.cu_list_from_global(seq, p["ozP"], p["ozS"], p["ozG"])
            self.cu_oz = [x / D.OZ_TO_UM for x in cu]
        self._recompute()
        self.invalidate("重建序列")
        self._restore_pending_confirm()
        return {"ok": True}

    def _restore_pending_confirm(self) -> None:
        """启动时：配置里存的确认层名与当前重建结果一致 ⇒ 自动恢复确认。"""
        pend = self._pending_confirm
        if not pend:
            return
        now = D.layer_names(self.seq) if self.seq else []
        if list(pend) == list(now):
            self.confirmed_names = list(now)
            self.confirmed_seq = list(self.seq)
            self.confirm_label = ("已确认 " + str(len(now))
                                  + " 个铜层（来自配置）")
        self._pending_confirm = None

    def set_row_type(self, index: int, type_key: str) -> dict:
        with self._lock:
            if not (0 <= index < len(self.seq)):
                raise ValueError("行号越界")
            self.seq[index] = type_key
            self._recompute()
            self.invalidate("层类型/层名改动")
            self.save_cfg()
            return self.state()

    def set_row_oz(self, index: int, oz_text: str) -> dict:
        with self._lock:
            try:
                val = float(oz_text)
            except (TypeError, ValueError):
                return self.state()
            if not (0 <= index < len(self.cu_oz)):
                raise ValueError("行号越界")
            self.cu_oz[index] = val
            self._recompute()
            return self.state()

    def sync_cu(self) -> dict:
        """按原副边同步铜厚。"""
        p = self._p()
        for i, t in enumerate(self.seq):
            self.cu_oz[i] = (p["ozP"] if t == "P"
                             else (p["ozG"] if t == "G" else p["ozS"]))
        self._recompute()
        return {"ok": True, "message":
                f"已按原副边同步 {len(self.seq)} 层铜厚"
                f"（P←{p['ozP']:g}oz, S/A/B←{p['ozS']:g}oz, G←{p['ozG']:g}oz）"}

    def _gap_after(self, i: int):
        """第 i 层与第 i+1 层之间的介质厚度（µm）；最后一层返回 None。"""
        if i >= len(self.seq) - 1:
            return None
        p = self._p()
        a, b = self.seq[i], self.seq[i + 1]
        if a == "G" or b == "G":
            return p["dSS"]
        if a == "P" and b == "P":
            return p["dPP"]
        if a == "P" or b == "P":
            return p["dPS"]
        return p["dSS"]

    # ================================================================ 计算
    def _compute(self):
        if not self.seq:
            return None
        p = self._p()
        if p["cumode"] == "perlayer":
            cu_um = D.cu_list_from_oz(self.cu_oz)
            mode = "逐层单独指定"
        else:
            cu_um = D.cu_list_from_global(self.seq, p["ozP"], p["ozS"], p["ozG"])
            mode = (f"按原副边（P {D.cu_um_label(p['ozP']):g}µm / "
                    f"S {D.cu_um_label(p['ozS']):g}µm / "
                    f"G {D.cu_um_label(p['ozG']):g}µm）")
        t = D.thickness(self.seq, cu_um, p["dPP"], p["dSS"], p["dPS"])
        ATp, ATs = D.ampere_turns(p["Np"], p["Lp"], p["Ns"], p["Ls"], p["rect"])
        m = D.mmf(self.seq, ATp, ATs, p["rect"])
        parP, parS = D.parallel_per_turn(p["Lp"], p["Np"], p["Ls"], p["Ns"],
                                          p["rect"])
        return dict(t=t, m=m, mode=mode, cu_um=cu_um,
                    iface=D.interfaces(self.seq),
                    errs=D.validate(p["Lp"], p["Ls"], p["Lgnd"], p["rect"],
                                    p["Np"], p["Ns"]),
                    ATp=ATp, ATs=ATs,
                    labels=D.layer_labels(self.seq, parP, parS))

    def _recompute(self) -> None:
        self._result = self._compute()

    # ================================================================ 确认
    def invalidate(self, reason: str = "") -> None:
        """叠层设计一旦改动，之前的确认即失效。"""
        if self.confirmed_names is None:
            return
        self.confirmed_names = None
        self.confirmed_seq = None
        self.confirm_label = "⚠️ 叠层已改动 —— 需重新确认"

    def confirm(self) -> dict:
        if not self.seq:
            return {"ok": False, "error": "没有可确认的叠层序列"}
        names = D.layer_names(self.seq)
        self.confirmed_names = list(names)
        self.confirmed_seq = list(self.seq)
        self.confirm_label = (f"已确认 {len(names)} 个铜层"
                              f"（{names[0]} … {names[-1]}）")
        self.save_cfg()
        return {"ok": True, "confirmedNames": names,
                "confirmedSeq": self.confirmed_seq,
                "label": self.confirm_label,
                "message": "✅ 已确认叠层：" + str(len(names)) + " 个铜层\n   "
                           + " / ".join(names[:4]) + " … " + names[-1]}

    def confirmed(self) -> dict:
        return {"confirmed": bool(self.confirmed_names),
                "names": list(self.confirmed_names or []),
                "count": len(self.confirmed_names or []),
                "label": self.confirm_label}

    # ================================================================ 文件
    def list_templates(self, folder: str | None = None) -> dict:
        d = folder or paths.stackup_dir()
        files = []
        try:
            names = sorted(os.listdir(d))
        except OSError as e:
            return {"ok": False, "error": f"目录不可读：{e}", "dir": d,
                    "files": []}
        for n in names:
            if not n.lower().endswith(".stackup"):
                continue
            p = os.path.join(d, n)
            try:
                st = os.stat(p)
            except OSError:
                continue
            files.append({"name": n, "path": p, "size": st.st_size,
                          "mtime": time.strftime("%Y-%m-%d %H:%M",
                                                 time.localtime(st.st_mtime))})
        return {"ok": True, "dir": d, "files": files}

    def open_template(self, path: str) -> dict:
        s = SF.Stackup(path)
        cop = [l for l in s.physical if l.is_copper]
        die = [l for l in s.physical if l.is_dielectric]
        self.src_file = path
        self.tpl_copper = len(cop)
        self.tpl_dielectric = len(die)
        label = (f"模板：{os.path.basename(path)}\n"
                 f"铜 {len(cop)} 层 / 介质 {len(die)} 层\n"
                 f"当前铜层名：{', '.join(l.name for l in cop[:3])} …")
        note = None
        if len(cop) != len(self.seq):
            note = (f"ℹ️ 模板铜层 {len(cop)} 层，当前设计 {len(self.seq)} 层"
                    f" —— 写出时会要求两者一致。")
        return {"ok": True, "path": path, "copper": len(cop),
                "dielectric": len(die), "label": label, "note": note}

    def default_out_path(self) -> str:
        """默认写出路径 —— 文件名一律带时间戳，避免覆盖上一版。"""
        ts = time.strftime("%Y%m%d_%H%M%S")
        if self.src_file:
            base = os.path.splitext(os.path.basename(self.src_file))[0]
            return os.path.join(os.path.dirname(self.src_file),
                                f"{base}_design_{ts}.stackup")
        d = paths.stackup_dir()
        if not os.path.isdir(d):
            d = paths.app_dir()
        return os.path.join(d, f"stackup_design_{ts}.stackup")

    def build_output(self, src_file: str | None, out_path: str) -> dict:
        """写出 `.stackup`（不弹窗）。

        - `src_file` 给了 ⇒ **模板模式**：套用板子导出的文件，保留材料 /
          Feature / Via Span 等设置，只改「铜层厚度 + 层名」与「内侧介质厚度」。
        - `src_file` 为 None ⇒ **从零生成**：按 AD 自带预设的 token 形状生成，
          但材料 / Dk / 过孔跨度为本工具默认值。
        """
        r = self._compute()
        if not r:
            raise ValueError("当前没有可用的叠层序列")
        p = self._p()
        if p["cumode"] == "perlayer":
            cu_um = D.cu_list_from_oz(self.cu_oz)
        else:
            cu_um = D.cu_list_from_global(self.seq, p["ozP"], p["ozS"], p["ozG"])
        names = D.layer_names(self.seq)
        mm = SF.MIL_TO_MM
        gaps = [self._gap_after(i) for i in range(len(self.seq) - 1)]

        if not src_file:
            cu_mil = [u / 1000.0 / mm for u in cu_um]
            diel_mil = [g / 1000.0 / mm for g in gaps]
            kinds = ["plane" if t == "G" else "signal" for t in self.seq]
            diel_types = [2 if i % 2 else 1 for i in range(len(gaps))]
            txt = BK.build_stackup_text(len(self.seq), names, cu_mil, diel_mil,
                                        kinds=kinds, diel_types=diel_types)
            blob = b"\xef\xbb\xbf" + txt.encode("utf-8")
            with open(out_path, "wb") as f:
                f.write(blob)
            return dict(ok=True, mode="从零生成", out=out_path, size=len(blob),
                        changed=True, names=names, cu_um=cu_um, gaps=gaps,
                        n_cop=len(self.seq), n_die=len(self.seq) + 1)

        s = SF.Stackup(src_file)
        cop = [l for l in s.physical if l.is_copper]
        die = [l for l in s.physical if l.is_dielectric]
        if len(cop) != len(self.seq):
            raise ValueError(f"模板铜层 {len(cop)} 层，设计 {len(self.seq)} 层，"
                             f"必须一致。")
        inner = die[1:-1]
        if len(inner) != max(0, len(self.seq) - 1):
            raise ValueError(f"模板内侧介质 {len(inner)} 个，"
                             f"设计需要 {len(self.seq) - 1} 个。")

        for lay, um, nm in zip(cop, cu_um, names):
            lay.set_thickness(f"{um / 1000.0 / mm:.4f}mil")   # 三份同步
            lay.set("NAME", nm)
            for k, _v, _i in list(lay.tokens):
                if k.endswith("}NAME"):
                    lay.set(k, nm)

        for i, lay in enumerate(inner):
            g = gaps[i]
            if g is not None:
                lay.set_thickness(f"{g / 1000.0 / mm:.4f}mil")

        changed, size = s.save(out_path)
        return dict(ok=True, mode="套用模板", out=out_path, size=size,
                    changed=changed, names=names, cu_um=cu_um, gaps=gaps,
                    n_cop=len(cop), n_die=len(die))

    def write(self, out_path: str | None = None,
              src_file: str | None = None) -> dict:
        out = out_path or self.default_out_path()
        src = self.src_file if src_file is None else src_file
        res = self.build_output(src, out)
        extra = ("" if src else
                 "\n   ⚠️ 从零生成：材料/Dk/过孔跨度用本工具默认值，"
                 "不含你板子已有的材料库/阻抗等设置")
        res["message"] = (
            f"✅ 已写出（{res['mode']}）{res['out']}"
            f"（{res['size']} 字节）\n"
            f"   铜 {res['n_cop']} 层改名：{res['names'][0]} / "
            f"{res['names'][1]} … {res['names'][-1]}\n"
            f"   介质 {res['n_die']} 层"
            f"（中间 {len(res['gaps'])} 段按设计）" + extra + "\n"
            f"   下一步：LSM → File → Load Stackup From File… → "
            f"选该文件 → File → Save to PCB")
        return res

    # ================================================================ 对外状态
    def state(self) -> dict:
        with self._lock:
            r = self._compute()
            names = D.layer_names(self.seq) if self.seq else []
            rows = []
            for i, t in enumerate(self.seq):
                oz = self.cu_oz[i] if i < len(self.cu_oz) else 0.0
                rows.append({
                    "i": i + 1,
                    "name": names[i] if i < len(names) else "",
                    "type": t,
                    "typeLabel": TYPE_LABEL.get(t, t),
                    "oz": oz,
                    "ozText": D.cu_oz_text(oz),
                    "gap": self._gap_after(i),
                })

            result = None
            mmf_series = []
            if r:
                t, m = r["t"], r["m"]
                counts = {k: self.seq.count(k) for k in "PSABG"}
                warn = ("⚠️ " + "\n⚠️ ".join(r["errs"]) + "\n\n") if r["errs"] else ""
                text = (
                    warn +
                    f"层数 {len(self.seq)}    P {counts['P']} / S {counts['S']} / "
                    f"A {counts['A']} / B {counts['B']} / G {counts['G']}\n"
                    f"铜厚模式：{r['mode']}\n\n"
                    f"总板厚（铜+介质）  {_fmt_mm(t['total'])} mm\n"
                    f"  铜合计           {_fmt_mm(t['cu'])} mm\n"
                    f"  介质合计         {_fmt_mm(t['diel'])} mm\n"
                    f"仿真厚度(去最外2层) {_fmt_mm(t['simTotal'])} mm\n\n"
                    f"安匝 ATp/ATs       {r['ATp']:.3f} / {r['ATs']:.3f} A\n"
                    f"原副边界面数       {r['iface']}\n"
                    f"MMF peak           {m['peak']:.1f} A\n"
                    f"MMF integral       {m['integral']:.1f} A\n"
                    f"MMF 对称偏差       {m['sym']:.1f} A\n\n"
                    f"层名序列：\n  " + " - ".join(names[:3]) + " … "
                    + " - ".join(names[-2:])
                )
                result = {
                    "total": t["total"], "cu": t["cu"], "diel": t["diel"],
                    "simTotal": t["simTotal"],
                    "cuSim": t.get("cuSim"), "dielSim": t.get("dielSim"),
                    "mode": r["mode"], "ATp": r["ATp"], "ATs": r["ATs"],
                    "iface": r["iface"], "errors": r["errs"], "counts": counts,
                    "mmf": {"peak": m["peak"], "integral": m["integral"],
                            "sym": m["sym"]},
                    "labels": r["labels"], "names": names, "text": text,
                }
                mmf_series = [{
                    "state": i,
                    "mmfAfter": st.get("mmfAfter", []),
                    "peak": st.get("peak"),
                    "integral": st.get("integral"),
                    "net": st.get("net"),
                } for i, st in enumerate(m.get("states", []))]

            strip = []
            labels = r["labels"] if r else []
            for i, t in enumerate(self.seq):
                strip.append({
                    "index": i + 1, "type": t,
                    "label": labels[i] if i < len(labels) else "",
                    "color": TYPE_COLOR.get(t, "#cccccc"),
                })

            tpl_label = "未读入模板 —— 写出时将「从零生成」"
            if self.src_file:
                tpl_label = (f"模板：{os.path.basename(self.src_file)}\n"
                             f"铜 {self.tpl_copper} 层 / "
                             f"介质 {self.tpl_dielectric} 层")

            return {
                "ok": True,
                "params": {k: str(self.params.get(k, "")) for k in PARAM_KEYS},
                "rect": self.rect,
                "cumode": self.cumode,
                "seq": list(self.seq),
                "names": names,
                "rows": rows,
                "result": result,
                "mmfSeries": mmf_series,
                "strip": strip,
                "confirmed": {"names": self.confirmed_names,
                              "seq": self.confirmed_seq,
                              "label": self.confirm_label},
                "template": {"srcFile": self.src_file, "label": tpl_label,
                             "copper": self.tpl_copper,
                             "dielectric": self.tpl_dielectric},
                "cuMode": {"globalEditable": self.cumode != "perlayer",
                           "perLayerEditable": self.cumode == "perlayer"},
                "typeLabels": [{"value": k, "label": v}
                               for k, v in TYPE_LABEL.items()],
                "cuChoices": CU_CHOICES,
                "error": self.last_error,
            }


STATE = StackupState()
