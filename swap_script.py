#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按要求交换的两层生成 DelphiScript（.pas + .PrjScr）。

为什么是"生成"而不是"写死一个脚本"
----------------------------------
用户在 GUI 里从**已确认的叠层设计**里挑两个层名，所以目标层是运行期才知道的。
生成器把层符号写进脚本，并**自动跳过这两层**去挑中转容器。

层名 → AD 内部层符号
--------------------
本工具的叠层设计层名规则是 `top` / `L<k>_<类型>` / `Bot`（k 从 1 起），
与 AD 铜层栈一一对应：

    top   -> eTopLayer
    Lk_x  -> eMidLayer{k}
    Bot   -> eBottomLayer

⚠️ 生成出来的脚本里**一律使用符号常量**，绝不出现 `TLayer` 的数值 ——
枚举从 `eTopLayer` 起连续，写数字极易静默指错层（已实测踩过）。
"""

from __future__ import annotations

import os
import re

MAX_MID = 30            # AD 最多 MidLayer30


class LayerPickError(ValueError):
    """层名无法映射 / 选择不合法。"""


def symbol_for_name(name: str) -> str:
    """叠层设计里的层名 → AD DelphiScript 层符号。"""
    n = (name or "").strip()
    if n == "top":
        return "eTopLayer"
    if n == "Bot":
        return "eBottomLayer"
    m = re.fullmatch(r"[Ll](\d+)(?:_[PSABG])?", n)
    if m:
        k = int(m.group(1))
        if not 1 <= k <= MAX_MID:
            raise LayerPickError(f"层名 {name!r} 的序号 {k} 超出 1..{MAX_MID}")
        return f"eMidLayer{k}"
    raise LayerPickError(f"无法把层名 {name!r} 映射到 AD 层符号")


def is_mid(sym: str) -> bool:
    return sym.startswith("eMidLayer") and sym != "eBottomLayer"


def validate_pair(name_a: str, name_b: str) -> tuple[str, str]:
    sa, sb = symbol_for_name(name_a), symbol_for_name(name_b)
    if sa == sb:
        raise LayerPickError("两个层不能是同一层")
    return sa, sb


def _candidates(sym_a: str, sym_b: str) -> list[str]:
    """中转容器候选：所有 MidLayer，跳过被交换的两层。"""
    skip = {sym_a, sym_b}
    return [f"eMidLayer{i}" for i in range(1, MAX_MID + 1)
            if f"eMidLayer{i}" not in skip]


def build_pas(name_a: str, name_b: str) -> str:
    """生成交换脚本正文（纯 ASCII，CRLF 由调用方负责）。"""
    sa, sb = validate_pair(name_a, name_b)
    cands = _candidates(sa, sb)
    if not cands:
        raise LayerPickError("没有可用的中转候选层")

    picks = "\n".join(f"    If TryPick({c}) Then Exit;" for c in cands)

    # 🔴 不能用 str.format：模板里满是用作 Pascal 注释的 { }，
    #    format 会把它们当占位符。用唯一的 @@TOKEN@@ 显式替换。
    out = _TEMPLATE
    for tok, val in (("@@NAME_A@@", name_a), ("@@NAME_B@@", name_b),
                     ("@@SYM_A@@", sa), ("@@SYM_B@@", sb),
                     ("@@NPICK@@", str(len(cands))), ("@@PICKS@@", picks)):
        out = out.replace(tok, val)
    if "@@" in out:
        raise LayerPickError("模板里还有未替换的占位符: "
                             + ", ".join(sorted(set(re.findall(r"@@\w+@@", out)))))
    return out


_TEMPLATE = r'''{-----------------------------------------------------------------------------}
{ swap_layers.pas - Swap ALL primitives between two copper layers.             }
{                                                                             }
{ GENERATED FILE - do not hand-edit.                                           }
{ Regenerate from the GUI (Altium Tools > layer swap tab).                     }
{                                                                             }
{ Layer A : @@NAME_A@@   (@@SYM_A@@) }
{ Layer B : @@NAME_B@@   (@@SYM_B@@) }
{                                                                             }
{ Excluded, by construction:                                                  }
{   - vias         -> live on eMultiLayer, never matched by the layer filter  }
{   - board cutout -> lives on eMultiLayer, never matched by the layer filter }
{   - components   -> can only exist on Top/Bottom, must NOT be relayered     }
{                                                                             }
{ Method: intermediate container                                              }
{   Step 1  A -> container (auto-picked free layer, @@NPICK@@ candidates tried)   }
{   Step 2  B -> A                                                            }
{   Step 3  container -> B                                                    }
{                                                                             }
{ A single-pass in-place swap is unsafe: once the A primitives land on B, any  }
{ "move everything on B" filter would also pick them up again and move them    }
{ straight back. The container makes every step unambiguous.                   }
{                                                                             }
{ Layers are addressed by the SYMBOLIC constants eTopLayer / eMidLayerN /      }
{ eBottomLayer. Do NOT replace them with numbers - the TLayer enum does not    }
{ start where it looks like it does, and a wrong number silently targets the   }
{ wrong layer.                                                                 }
{                                                                             }
{ Run: File > Run Script > swap_layers.PrjScr > SwapLayers                    }
{-----------------------------------------------------------------------------}

Const
    MAX_PASSES = 60;    { runaway guard for the repeat-until-empty loop }

Var
    Board      : IPCB_Board;
    LayerA     : TLayer;
    LayerB     : TLayer;
    BoxLayer   : TLayer;      { the container, chosen at run time }
    BoxIdx     : Integer;
    CntAA      : Integer;
    CntBA      : Integer;
    CntBoxA    : Integer;
    CntViaA    : Integer;
    CntCutA    : Integer;
    CntCompA   : Integer;
    CntAB      : Integer;
    CntBB      : Integer;
    CntBoxB    : Integer;
    CntViaB    : Integer;
    CntCutB    : Integer;
    CntCompB   : Integer;
    Moved1     : Integer;
    Moved2     : Integer;
    Moved3     : Integer;
    Leftover   : Integer;
    TmpStr     : String;

{-----------------------------------------------------------------------------}
{ Primitive types that participate in the swap.                                }
{ Deliberately NOT included: eViaObject (excluded by requirement),             }
{ eComponentObject (cannot be relayered to an inner layer).                    }
{-----------------------------------------------------------------------------}
Function SwapObjectSet : TSet;
Begin
    Result := MkSet(eTrackObject, eArcObject, eFillObject,
                    eRegionObject, eTextObject, ePadObject);
End;

{-----------------------------------------------------------------------------}
{ Map an index 1..30 to the matching eMidLayerN constant.                      }
{ Written as an explicit Case so no arithmetic is done on the enum type.       }
{-----------------------------------------------------------------------------}
Function MidLayerByIndex(N : Integer) : TLayer;
Begin
    Result := eMidLayer1;
    Case N Of
        1: Result := eMidLayer1;
        2: Result := eMidLayer2;
        3: Result := eMidLayer3;
        4: Result := eMidLayer4;
        5: Result := eMidLayer5;
        6: Result := eMidLayer6;
        7: Result := eMidLayer7;
        8: Result := eMidLayer8;
        9: Result := eMidLayer9;
        10: Result := eMidLayer10;
        11: Result := eMidLayer11;
        12: Result := eMidLayer12;
        13: Result := eMidLayer13;
        14: Result := eMidLayer14;
        15: Result := eMidLayer15;
        16: Result := eMidLayer16;
        17: Result := eMidLayer17;
        18: Result := eMidLayer18;
        19: Result := eMidLayer19;
        20: Result := eMidLayer20;
        21: Result := eMidLayer21;
        22: Result := eMidLayer22;
        23: Result := eMidLayer23;
        24: Result := eMidLayer24;
        25: Result := eMidLayer25;
        26: Result := eMidLayer26;
        27: Result := eMidLayer27;
        28: Result := eMidLayer28;
        29: Result := eMidLayer29;
        30: Result := eMidLayer30;
    Else
        Result := eMidLayer1;
    End;
End;

{-----------------------------------------------------------------------------}
{ Count the swappable primitives sitting on one layer.                         }
{-----------------------------------------------------------------------------}
Function CountOnLayer(L : TLayer) : Integer;
Var
    It : IPCB_BoardIterator;
    P  : IPCB_Primitive;
Begin
    Result := 0;
    It := Board.BoardIterator_Create;
    It.AddFilter_ObjectSet(SwapObjectSet);
    It.AddFilter_LayerSet(MkSet(L));
    It.AddFilter_Method(eProcessAll);
    P := It.FirstPCBObject;
    While P <> Nil Do
    Begin
        If P.Layer = L Then Result := Result + 1;
        P := It.NextPCBObject;
    End;
    Board.BoardIterator_Destroy(It);
End;

{-----------------------------------------------------------------------------}
{ Vias. Must stay put.                                                         }
{-----------------------------------------------------------------------------}
Function CountVias : Integer;
Var
    It : IPCB_BoardIterator;
    P  : IPCB_Primitive;
Begin
    Result := 0;
    It := Board.BoardIterator_Create;
    It.AddFilter_ObjectSet(MkSet(eViaObject));
    It.AddFilter_LayerSet(AllLayers);
    It.AddFilter_Method(eProcessAll);
    P := It.FirstPCBObject;
    While P <> Nil Do
    Begin
        Result := Result + 1;
        P := It.NextPCBObject;
    End;
    Board.BoardIterator_Destroy(It);
End;

{-----------------------------------------------------------------------------}
{ Regions on Multi-Layer = board cutouts. Must stay put.                       }
{-----------------------------------------------------------------------------}
Function CountMultiLayerRegions : Integer;
Var
    It : IPCB_BoardIterator;
    P  : IPCB_Primitive;
Begin
    Result := 0;
    It := Board.BoardIterator_Create;
    It.AddFilter_ObjectSet(MkSet(eRegionObject));
    It.AddFilter_LayerSet(MkSet(eMultiLayer));
    It.AddFilter_Method(eProcessAll);
    P := It.FirstPCBObject;
    While P <> Nil Do
    Begin
        If P.Layer = eMultiLayer Then Result := Result + 1;
        P := It.NextPCBObject;
    End;
    Board.BoardIterator_Destroy(It);
End;

{-----------------------------------------------------------------------------}
{ Components sitting on either of the two layers. Reported, never moved.       }
{-----------------------------------------------------------------------------}
Function CountComponentsOnBoth : Integer;
Var
    It : IPCB_BoardIterator;
    P  : IPCB_Primitive;
Begin
    Result := 0;
    It := Board.BoardIterator_Create;
    It.AddFilter_ObjectSet(MkSet(eComponentObject));
    It.AddFilter_LayerSet(AllLayers);
    It.AddFilter_Method(eProcessAll);
    P := It.FirstPCBObject;
    While P <> Nil Do
    Begin
        If (P.Layer = LayerA) Or (P.Layer = LayerB) Then Result := Result + 1;
        P := It.NextPCBObject;
    End;
    Board.BoardIterator_Destroy(It);
End;

{-----------------------------------------------------------------------------}
{ Per-type census of one layer - used to explain a refusal.                    }
{-----------------------------------------------------------------------------}
Function LayerBreakdown(L : TLayer) : String;
Var
    It : IPCB_BoardIterator;
    P  : IPCB_Primitive;
    Tr, Ar, Fi, Re, Te, Pa : Integer;
Begin
    Tr := 0; Ar := 0; Fi := 0; Re := 0; Te := 0; Pa := 0;
    It := Board.BoardIterator_Create;
    It.AddFilter_ObjectSet(SwapObjectSet);
    It.AddFilter_LayerSet(MkSet(L));
    It.AddFilter_Method(eProcessAll);
    P := It.FirstPCBObject;
    While P <> Nil Do
    Begin
        If P.Layer = L Then
        Begin
            If P.ObjectId = eTrackObject Then Tr := Tr + 1
            Else If P.ObjectId = eArcObject Then Ar := Ar + 1
            Else If P.ObjectId = eFillObject Then Fi := Fi + 1
            Else If P.ObjectId = eRegionObject Then Re := Re + 1
            Else If P.ObjectId = eTextObject Then Te := Te + 1
            Else If P.ObjectId = ePadObject Then Pa := Pa + 1;
        End;
        P := It.NextPCBObject;
    End;
    Board.BoardIterator_Destroy(It);
    Result := 'track ' + IntToStr(Tr) + ', arc ' + IntToStr(Ar) +
              ', fill ' + IntToStr(Fi) + ', region ' + IntToStr(Re) +
              ', text ' + IntToStr(Te) + ', pad ' + IntToStr(Pa);
End;

{-----------------------------------------------------------------------------}
{ Container candidates. TryPick sets BoxLayer when the layer is empty.         }
{-----------------------------------------------------------------------------}
Function TryPick(L : TLayer; Idx : Integer) : Boolean;
Begin
    Result := False;
    If CountOnLayer(L) = 0 Then
    Begin
        BoxLayer := L;
        BoxIdx := Idx;
        Result := True;
    End;
End;

Function FindFreeLayer : Boolean;
Begin
    Result := True;
@@PICKS@@
    Result := False;
End;

{-----------------------------------------------------------------------------}
{ Relay every primitive on FromLayer to ToLayer.                               }
{                                                                             }
{ The loop restarts the iterator after each object is moved, so a primitive    }
{ skipped by the live iterator is caught on the next pass. It stops when a     }
{ full pass moves nothing.                                                     }
{-----------------------------------------------------------------------------}
Function MoveLayer(FromLayer, ToLayer : TLayer) : Integer;
Var
    It     : IPCB_BoardIterator;
    P      : IPCB_Primitive;
    Any    : Boolean;
    Passes : Integer;
Begin
    Result := 0;
    Passes := 0;
    Repeat
        Any := False;
        It := Board.BoardIterator_Create;
        It.AddFilter_ObjectSet(SwapObjectSet);
        It.AddFilter_LayerSet(MkSet(FromLayer));
        It.AddFilter_Method(eProcessAll);
        P := It.FirstPCBObject;
        While P <> Nil Do
        Begin
            If P.Layer = FromLayer Then
            Begin
                PCBServer.SendMessageToRobots(P.I_ObjectAddress, c_Broadcast,
                                             PCBM_BeginModify, c_NoEventData);
                Try
                    P.Layer := ToLayer;
                Except
                End;
                PCBServer.SendMessageToRobots(P.I_ObjectAddress, c_Broadcast,
                                             PCBM_EndModify, c_NoEventData);
                Result := Result + 1;
                Any := True;
            End;
            P := It.NextPCBObject;
        End;
        Board.BoardIterator_Destroy(It);
        Passes := Passes + 1;
    Until (Not Any) Or (Passes >= MAX_PASSES);
End;

{-----------------------------------------------------------------------------}
{ SwapLayers - entry point called from File > Run Script.                      }
{-----------------------------------------------------------------------------}
Procedure SwapLayers;
Begin
    Board := PCBServer.GetCurrentPCBBoard;
    If Board = Nil Then
    Begin
        ShowMessage('No PCB document is active.' + #13#10 +
                    'Open the .PcbDoc and try again.');
        Exit;
    End;

    LayerA := @@SYM_A@@;
    LayerB := @@SYM_B@@;

    { ---- 0. baseline ---------------------------------------------------- }
    CntAA    := CountOnLayer(LayerA);
    CntBA    := CountOnLayer(LayerB);
    CntViaA  := CountVias;
    CntCutA  := CountMultiLayerRegions;
    CntCompA := CountComponentsOnBoth;

    If (CntAA = 0) And (CntBA = 0) Then
    Begin
        ShowMessage('Nothing to do: both layers are empty.' + #13#10 +
                    '  layer A : 0' + #13#10 + '  layer B : 0');
        Exit;
    End;

    { ---- 0b. pick a free container -------------------------------------- }
    If Not FindFreeLayer Then
    Begin
        ShowMessage('Aborted: no empty MidLayer found to use as the' +
                    #13#10 + 'container (@@NPICK@@ candidates tried).');
        Exit;
    End;

    CntBoxA := CountOnLayer(BoxLayer);

    { ---- 0c. report the plan before touching anything ------------------- }
    TmpStr := 'About to swap two copper layers.' + #13#10 +
              '------------------------------------------------' + #13#10 +
              'layer A  @@NAME_A@@  (@@SYM_A@@) : ' + IntToStr(CntAA) + #13#10 +
              'layer B  @@NAME_B@@  (@@SYM_B@@) : ' + IntToStr(CntBA) + #13#10 +
              'container eMidLayer' + IntToStr(BoxIdx) +
              '    : ' + IntToStr(CntBoxA) + '  (must be 0)' + #13#10 +
              '------------------------------------------------' + #13#10 +
              'not touched: vias ' + IntToStr(CntViaA) +
              ', Multi-Layer regions ' + IntToStr(CntCutA) +
              ', components on A/B ' + IntToStr(CntCompA) + #13#10 +
              '------------------------------------------------' + #13#10 +
              'Steps:  A -> container,  B -> A,  container -> B' + #13#10 +
              #13#10 + 'Press OK to run.';
    ShowMessage(TmpStr);

    { ---- 1. A -> container ---------------------------------------------- }
    Moved1 := MoveLayer(LayerA, BoxLayer);
    If CountOnLayer(BoxLayer) <> Moved1 Then
    Begin
        MoveLayer(BoxLayer, LayerA);         { put them back - leave no mess }
        ShowMessage('Aborted during step 1: only ' +
                    IntToStr(CountOnLayer(BoxLayer)) + ' of ' + IntToStr(Moved1) +
                    ' primitives reached eMidLayer' + IntToStr(BoxIdx) + '.' +
                    #13#10 + 'They have been moved back to @@NAME_A@@.' +
                    #13#10 + 'That layer may not be a real copper layer of this' +
                    #13#10 + 'stack. Try another target pair.');
        Exit;
    End;

    { ---- 2. B -> A ------------------------------------------------------ }
    Moved2 := MoveLayer(LayerB, LayerA);
    { ---- 3. container -> B ---------------------------------------------- }
    Moved3 := MoveLayer(BoxLayer, LayerB);

    { ---- 4. verify ------------------------------------------------------ }
    CntAB    := CountOnLayer(LayerA);
    CntBB    := CountOnLayer(LayerB);
    CntBoxB  := CountOnLayer(BoxLayer);
    CntViaB  := CountVias;
    CntCutB  := CountMultiLayerRegions;
    CntCompB := CountComponentsOnBoth;
    Leftover := CntBoxB;

    Board.ViewManager_FullUpdate;

    TmpStr := 'Swap finished.' + #13#10 +
              '------------------------------------------------' + #13#10 +
              'moved: A->box ' + IntToStr(Moved1) +
              ' | B->A ' + IntToStr(Moved2) +
              ' | box->B ' + IntToStr(Moved3) + #13#10 +
              'container used: eMidLayer' + IntToStr(BoxIdx) + #13#10 +
              '------------------------------------------------' + #13#10 +
              'layer              before -> after' + #13#10 +
              '@@NAME_A@@  (@@SYM_A@@) : ' + IntToStr(CntAA) + ' -> ' + IntToStr(CntAB) + #13#10 +
              '@@NAME_B@@  (@@SYM_B@@) : ' + IntToStr(CntBA) + ' -> ' + IntToStr(CntBB) + #13#10 +
              'container          : ' + IntToStr(CntBoxA) + ' -> ' + IntToStr(CntBoxB) + #13#10 +
              '------------------------------------------------' + #13#10 +
              'must not move:' + #13#10 +
              'vias                ' + IntToStr(CntViaA) + ' -> ' + IntToStr(CntViaB) + #13#10 +
              'cutouts(MultiLyr)   ' + IntToStr(CntCutA) + ' -> ' + IntToStr(CntCutB) + #13#10 +
              'components on A/B   ' + IntToStr(CntCompA) + ' -> ' + IntToStr(CntCompB) + #13#10 +
              '------------------------------------------------' + #13#10 +
              'expected: A -> ' + IntToStr(CntBA) +
              ' , B -> ' + IntToStr(CntAA) +
              ' , container -> 0' + #13#10 +
              'leftover in container: ' + IntToStr(Leftover) + #13#10 +
              #13#10 + 'Ctrl+S to keep, Ctrl+Z to undo.';

    If Leftover > 0 Then
    Begin
        TmpStr := TmpStr + #13#10 + #13#10 +
                  'WARNING: the container still holds ' + IntToStr(Leftover) +
                  ' primitives:' + #13#10 + LayerBreakdown(BoxLayer);
    End;

    ShowMessage(TmpStr);
End;
'''

PRJ = ("[Design]\r\nVersion=1.0\r\nHierarchyMode=0\r\n\r\n"
       "[Document1]\r\nDocumentPath=swap_layers.pas\r\n")


def write_script(out_dir: str, name_a: str, name_b: str) -> tuple[str, str]:
    """生成 swap_layers.pas + swap_layers.PrjScr，返回两个路径。"""
    os.makedirs(out_dir, exist_ok=True)
    pas = os.path.join(out_dir, "swap_layers.pas")
    prj = os.path.join(out_dir, "swap_layers.PrjScr")
    body = build_pas(name_a, name_b)
    body = body.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")
    with open(pas, "wb") as f:
        f.write(body.encode("ascii"))
    with open(prj, "wb") as f:
        f.write(PRJ.encode("ascii"))
    return pas, prj


if __name__ == "__main__":
    import sys
    a = sys.argv[1] if len(sys.argv) > 1 else "top"
    b = sys.argv[2] if len(sys.argv) > 2 else "L1_B"
    p1, p2 = write_script(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "altium_swap"), a, b)
    print("written:", p1)
    print("written:", p2)
