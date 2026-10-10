#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成「叠层覆盖」的 DelphiScript（.pas + .PrjScr）。

功能：把 A 层的内容**删除**，再把 B 层的内容**复制**到 A 层；B 层原内容**保留**。

与 swap_script.py 的关系
------------------------
两者独立：本模块自带完整模板（含 LayerByName / StackLayerNames / DumpReport），
因为 Altium 一次只加载一个 .pas，生成的脚本必须自包含。
命名/归档/落盘报告等约定与 swap_script.py 保持一致：
  * 文件名带时间戳：overwrite_layer_YYYYMMDD_HHMMSS.pas / .PrjScr
  * 报告写到 .PcbDoc 同目录的 overwrite_layer_report.txt
  * 过旧套件移动到 _old/

复制/删除用的都是生产脚本（eda-agent 的 PCB.pas）里在跑的写法：
  * 复制：Prim.Replicate（多边形/区域用 ReplicateWithChildren）
          -> Board.BeginModify / AddPCBObject / EndModify
          -> 改 Layer -> SendMessageToRobots(PCBM_BoardRegisteration)
          -> 有网络的挂回 Net.AddPCBObject
  * 删除：Board.RemovePCBObject(Obj)

层名 -> 具体层：**运行时按显示名向板子查**（LayerByName），
绝不拿名字里的数字去拼 eMidLayerN（板子层名被叠层设计重排过）。
"""
from __future__ import annotations

import os
import re
import shutil
import time

PRUNE_ERRORS: list = []
KEEP_SETS = 10
KEEP_BAKS = 20

STEM_PREFIX = "overwrite_layer"
MAX_MID = 30


class LayerPickError(ValueError):
    """层名不合法。"""


def validate_pair(name_a: str, name_b: str) -> tuple[str, str]:
    a = (name_a or "").strip()
    b = (name_b or "").strip()
    if not a or not b:
        raise LayerPickError("A/B 两层都要选")
    if a == b:
        raise LayerPickError("A 和 B 不能是同一层")
    return a, b


def default_stem() -> str:
    """每次一套独立文件名（时间戳），互不覆盖。"""
    return STEM_PREFIX + "_" + time.strftime("%Y%m%d_%H%M%S")


# --------------------------------------------------------------------- 模板
_TEMPLATE = r'''{-----------------------------------------------------------------------------}
{ @@STEM@@.pas - Overwrite layer A with the contents of layer B.               }
{                                                                             }
{       1. delete every copyable primitive on layer A                         }
{       2. copy every primitive of layer B onto layer A                       }
{       3. layer B itself is left untouched                                   }
{                                                                            }
{ GENERATED FILE - do not hand-edit.                                          }
{ Regenerate from the GUI (Altium Tools > layer overwrite tab).               }
{                                                                            }
{ Layer A : @@NAME_A@@                                                        }
{ Layer B : @@NAME_B@@                                                        }
{                                                                            }
{ Run: File > Run Script > @@STEM@@.PrjScr > OverwriteLayer                   }
{ NOTE: nothing is saved. Press Ctrl+S after checking the report.             }
{-----------------------------------------------------------------------------}
Var
    Board      : IPCB_Board;
    LayerA     : TLayer;
    LayerB     : TLayer;
    FoundA     : Boolean;
    FoundB     : Boolean;
    CntA0      : Integer;
    CntB0      : Integer;
    Deleted    : Integer;
    Copied     : Integer;
    Failed     : Integer;
    CntA1      : Integer;
    CntB1      : Integer;
    TmpStr     : String;
    DelFailCount : Integer;
    KindsStr   : String;
    KindsSeen  : String;
    OneKind    : String;

{-----------------------------------------------------------------------------}
{ Primitive classes that take part. Pads are deliberately excluded: they      }
{ belong to components and relaying them would damage the footprint.          }
{-----------------------------------------------------------------------------}
Function CopySet : TSet;
Begin
    Result := MkSet(eTrackObject, eArcObject, eFillObject, eRegionObject,
                    ePolyObject, eTextObject);
End;

{-----------------------------------------------------------------------------}
{ Resolve a layer by its DISPLAY NAME (what the user sees and picked).        }
{ Must NOT assume L(number) == eMidLayer(number): the board's layers are      }
{ renamed by the stackup design, so the name and the MidLayer index are       }
{ unrelated. LayerObj.LayerID is the TLayer value.                            }
{-----------------------------------------------------------------------------}
Function LayerByName(Nm : String; Var Ok : Boolean) : TLayer;
Var
    LayerStack : IPCB_LayerStack_V7;
    LayerObj   : IPCB_LayerObject_V7;
    LName      : String;
Begin
    Ok := False;
    Result := eTopLayer;
    If Board = Nil Then Exit;
    LayerStack := Board.LayerStack_V7;
    If LayerStack = Nil Then Exit;
    LayerObj := LayerStack.FirstLayer;
    While LayerObj <> Nil Do
    Begin
        Try LName := LayerObj.Name; Except LName := ''; End;
        If LName = Nm Then
        Begin
            Try
                Result := LayerObj.LayerID;
                Ok := True;
            Except
                Ok := False;
            End;
            Exit;
        End;
        LayerObj := LayerStack.NextLayer(LayerObj);
    End;
End;

{ All names in the stack, for a helpful error message. }
Function StackLayerNames : String;
Var
    LayerStack : IPCB_LayerStack_V7;
    LayerObj   : IPCB_LayerObject_V7;
    LName, Acc : String;
Begin
    Acc := '';
    If Board = Nil Then
    Begin
        Result := '(no board)';
        Exit;
    End;
    LayerStack := Board.LayerStack_V7;
    If LayerStack = Nil Then
    Begin
        Result := '(no layer stack)';
        Exit;
    End;
    LayerObj := LayerStack.FirstLayer;
    While LayerObj <> Nil Do
    Begin
        Try LName := LayerObj.Name; Except LName := '?'; End;
        If Acc <> '' Then Acc := Acc + ', ';
        Acc := Acc + LName;
        LayerObj := LayerStack.NextLayer(LayerObj);
    End;
    Result := Acc;
End;

{ Write the report to a file next to the .PcbDoc (the dialogs disappear). }
Procedure DumpReport(Txt : String);
Var
    SL : TStringList;
Begin
    Try
        SL := TStringList.Create;
        SL.Text := Txt;
        SL.SaveToFile(ExtractFilePath(Board.FileName) + 'overwrite_layer_report.txt');
        SL.Free;
    Except
    End;
End;

{ Find a net by name - board iterator over eNetObject (same as the           }
{ production eda-agent script PCB.pas).                         }
Function FindNetByName(BD : IPCB_Board; NetName : String) : IPCB_Net;
Var
    It  : IPCB_BoardIterator;
    Net : IPCB_Net;
Begin
    Result := Nil;
    If BD = Nil Then Exit;
    It := BD.BoardIterator_Create;
    It.AddFilter_ObjectSet(MkSet(eNetObject));
    It.AddFilter_LayerSet(AllLayers);
    It.AddFilter_Method(eProcessAll);
    Net := It.FirstPCBObject;
    While Net <> Nil Do
    Begin
        If Net.Name = NetName Then
        Begin
            Result := Net;
            Break;
        End;
        Net := It.NextPCBObject;
    End;
    BD.BoardIterator_Destroy(It);
End;

Function CountOnLayer(L : TLayer) : Integer;
Var
    It : IPCB_BoardIterator;
    P  : IPCB_Primitive;
Begin
    Result := 0;
    It := Board.BoardIterator_Create;
    It.AddFilter_ObjectSet(CopySet);
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

{ Delete the copyable primitives sitting on one layer. Repeat until empty so }
{ that the live iterator cannot hide anything by shifting under us.          }
Function DeleteOnLayer(L : TLayer) : Integer;
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
        It.AddFilter_ObjectSet(CopySet);
        It.AddFilter_LayerSet(MkSet(L));
        It.AddFilter_Method(eProcessAll);
        P := It.FirstPCBObject;
        While P <> Nil Do
        Begin
            If P.Layer = L Then
            Begin
                Try
                    Board.RemovePCBObject(P);
                    Result := Result + 1;
                    Any := True;
                Except
                    { Do not swallow this: a failure here is why a layer
                      keeps objects it was told to erase. Record the kind. }
                    DelFailCount := DelFailCount + 1;
                    Try
                        OneKind := 'objid=' + IntToStr(Ord(P.ObjectId));
                        If Pos('|' + OneKind + '|', KindsSeen) = 0 Then
                        Begin
                            KindsSeen := KindsSeen + '|' + OneKind + '|';
                            If KindsStr <> '' Then KindsStr := KindsStr + ', ';
                            KindsStr := KindsStr + OneKind;
                        End;
                    Except End;
                End;
            End;
            P := It.NextPCBObject;
        End;
        Board.BoardIterator_Destroy(It);
        Passes := Passes + 1;
    Until (Not Any) Or (Passes >= 60);
End;

{ Copy every primitive of FromLayer onto ToLayer. FromLayer is untouched.    }
Function CopyLayerInto(FromLayer, ToLayer : TLayer; Var Fail : Integer) : Integer;
Var
    It      : IPCB_BoardIterator;
    P       : IPCB_Primitive;
    NewP    : IPCB_Primitive;
    NetObj  : IPCB_Net;
    NetName : String;
    TouchedStr : String;
    RestStr    : String;
    PipePos    : Integer;
    Poly    : IPCB_Polygon;
    Passes  : Integer;
    Any     : Boolean;
Begin
    Result := 0;
    Fail := 0;
    TouchedStr := '';
    { The production script wraps every board mutation in these two calls.
      Without that pour context Rebuild pours EMPTY copper - which is how the
      layer lost all its copper on the earlier attempt. }
    Try PCBServer.PreProcess; Except End;
    Passes := 0;
    Repeat
        Any := False;
        It := Board.BoardIterator_Create;
        It.AddFilter_ObjectSet(CopySet);
        It.AddFilter_LayerSet(MkSet(FromLayer));
        It.AddFilter_Method(eProcessAll);
        P := It.FirstPCBObject;
        While P <> Nil Do
        Begin
            If (P.Layer = FromLayer) And (P.Layer <> ToLayer) Then
            Begin
                NewP := Nil;
                { A polygon must be copied WITH its fill (its children),
                  otherwise the copy is an empty shell and connects to
                  nothing. ReplicateWithChildren is not on the base
                  interface, so hold the source in a variable of the
                  concrete interface first (the production script documents
                  this subtype requirement). If that call is unavailable on
                  this build, fall back to plain Replicate.
                  Do NOT call Rebuild on the copy: a fresh copy has no fill
                  yet, and re-pouring it produces EMPTY copper - that is how
                  the layer ended up with no copper at all. }
                { ReplicateWithChildren does not exist on this build - tried on
                  the base interface AND on a concretely typed IPCB_Polygon
                  variable; both Undeclared. Plain Replicate copies the
                  outline, and the re-pour step below restores the fill -
                  which is why PreProcess/PostProcess wrap this routine. }
                Try
                    NewP := P.Replicate;
                Except
                    NewP := Nil;
                End;

                If NewP = Nil Then
                Begin
                    Fail := Fail + 1;
                End
                Else
                Begin
                    Try
                        Board.BeginModify;
                        Board.AddPCBObject(NewP);
                        Board.EndModify;

                        { Register the new primitive right after adding it -
                          the API notes warn that AddPCBObject alone may not
                          register it with the editors. }
                        PCBServer.SendMessageToRobots(Board.I_ObjectAddress,
                            c_Broadcast, PCBM_BoardRegisteration,
                            NewP.I_ObjectAddress);

                        { Change the layer with exactly the ceremony the layer
                          swap page uses (that one is verified to keep the
                          connectivity intact): the PCBM_BeginModify /
                          PCBM_EndModify robot pair around the assignment -
                          NOT NewP.BeginModify / NewP.EndModify. }
                        PCBServer.SendMessageToRobots(NewP.I_ObjectAddress,
                            c_Broadcast, PCBM_BeginModify, c_NoEventData);
                        Try
                            NewP.Layer := ToLayer;
                        Except
                        End;
                        PCBServer.SendMessageToRobots(NewP.I_ObjectAddress,
                            c_Broadcast, PCBM_EndModify, c_NoEventData);

                        { Hang the copy back on its net. The API doc is explicit:
                          Net.AddPCBObject(Obj) is the correct way, do NOT write
                          Prim.Net. Writing it threw here, and that skipped the
                          AddPCBObject line as well - so the copy ended up with no
                          net at all and would not connect to anything. Each step
                          now has its own guard so one failure cannot skip the rest. }
                        NetName := '';
                        Try
                            If P.Net <> Nil Then NetName := P.Net.Name;
                        Except
                        End;
                        If NetName <> '' Then
                        Begin
                            If Pos('|' + NetName + '|', TouchedStr) = 0 Then
                                TouchedStr := TouchedStr + '|' + NetName + '|';
                        End;
                        Begin
                            NetObj := Nil;
                            Try NetObj := FindNetByName(Board, NetName); Except NetObj := Nil; End;
                            If NetObj <> Nil Then
                            Begin
                                Try
                                    NetObj.AddPCBObject(NewP);
                                Except
                                    Fail := Fail + 1;
                                End;
                            End;
                        End;

                        { Re-pour the copied polygon, otherwise only the outline
                          comes over and nothing connects. Needs the pour context
                          from PreProcess/PostProcess. Concrete-interface
                          variable first, no cast syntax. }
                        If NewP.ObjectId = ePolyObject Then
                        Begin
                            Poly := Nil;
                            Try Poly := NewP; Except Poly := Nil; End;
                            If Poly <> Nil Then
                            Begin
                                @@REBUILD_CALL@@
                            End;
                        End;

                        Result := Result + 1;
                        Any := True;
                    Except
                        Fail := Fail + 1;
                    End;
                End;
            End;
            P := It.NextPCBObject;
        End;
        Board.BoardIterator_Destroy(It);
        Passes := Passes + 1;
    Until (Not Any) Or (Passes >= 60);

    Try PCBServer.PostProcess; Except End;

    { Re-analyse the connectivity of every net we touched. Copying copper as a
      plain region does not by itself make the connectivity engine treat it as
      plane copper, so ask it to rebuild those nets.
      The net list is walked as a pipe-separated STRING on purpose:/n      TStringList.Count and TStringList.Get do not exist in this
      DelphiScript build, so that class is no longer relied on here. }
    RestStr := TouchedStr;
    While RestStr <> '' Do
    Begin
        PipePos := Pos('|', RestStr);
        If PipePos > 0 Then
        Begin
            NetName := Copy(RestStr, 1, PipePos - 1);
            RestStr := Copy(RestStr, PipePos + 1, Length(RestStr));
        End
        Else
        Begin
            NetName := RestStr;
            RestStr := '';
        End;
        If NetName <> '' Then
        Begin
            NetObj := Nil;
            Try NetObj := FindNetByName(Board, NetName); Except NetObj := Nil; End;
            If NetObj <> Nil Then
            Begin
                @@ANALYZE_CALL@@
            End;
        End;
    End;
End;

{-----------------------------------------------------------------------------}
{ Read-only: dump every design rule (name + scope) next to the .PcbDoc.       }
{ Connect Style / Air Gap live in RULES (PlaneConnectStyle / PlaneClearance / }
{ PolygonConnectStyle), not on primitives - so this is how we see what the    }
{ board actually has before touching anything.                                }
{-----------------------------------------------------------------------------}
Procedure DumpRules;
Var
    It  : IPCB_BoardIterator;
    R   : IPCB_Rule;
    SL  : TStringList;
    Acc : String;
Begin
    If Board = Nil Then Exit;
    Acc := 'DESIGN RULES on ' + ExtractFileName(Board.FileName) + #13#10 +
           '(name | scope_1 | scope_2)' + #13#10 +
           '============================================================' + #13#10;
    Try
        It := Board.BoardIterator_Create;
        It.AddFilter_ObjectSet(MkSet(eRuleObject));
        It.AddFilter_LayerSet(AllLayers);
        It.AddFilter_Method(eProcessAll);
        R := It.FirstPCBObject;
        While R <> Nil Do
        Begin
            Acc := Acc + R.Name + ' | ';
            Try Acc := Acc + R.Scope1Expression; Except Acc := Acc + '?'; End;
            Acc := Acc + ' | ';
            Try Acc := Acc + R.Scope2Expression; Except Acc := Acc + '?'; End;
            Acc := Acc + #13#10;
            R := It.NextPCBObject;
        End;
        Board.BoardIterator_Destroy(It);
    Except
    End;
    Try
        SL := TStringList.Create;
        SL.Text := Acc;
        SL.SaveToFile(ExtractFilePath(Board.FileName) + 'overwrite_layer_rules.txt');
        SL.Free;
    Except
    End;
End;

Procedure OverwriteLayer;
Begin
    Board := PCBServer.GetCurrentPCBBoard;
    If Board = Nil Then
    Begin
        ShowMessage('No PCB document is active.' + #13#10 +
                    'Open the .PcbDoc and try again.');
        Exit;
    End;

    { Resolve the two layers BY NAME (never by index). }
    LayerA := LayerByName('@@NAME_A@@', FoundA);
    If Not FoundA Then
    Begin
        ShowMessage('Aborted: no layer named ''@@NAME_A@@'' on this board.'
                    + #13#10 + 'The stack layers on this board:' + #13#10
                    + StackLayerNames);
        Exit;
    End;
    LayerB := LayerByName('@@NAME_B@@', FoundB);
    If Not FoundB Then
    Begin
        ShowMessage('Aborted: no layer named ''@@NAME_B@@'' on this board.'
                    + #13#10 + 'The stack layers on this board:' + #13#10
                    + StackLayerNames);
        Exit;
    End;

    DumpRules;                  { read-only: dump the board rules first }
    DelFailCount := 0;
    KindsStr := '';
    KindsSeen := '';
    CntA0 := CountOnLayer(LayerA);
    CntB0 := CountOnLayer(LayerB);

    TmpStr := 'About to overwrite layer A with layer B.' + #13#10 +
              '------------------------------------------------' + #13#10 +
              'layer A  @@NAME_A@@ : ' + IntToStr(CntA0) + '  (will be erased)' + #13#10 +
              'layer B  @@NAME_B@@ : ' + IntToStr(CntB0) + '  (kept as is)' + #13#10 +
              '------------------------------------------------' + #13#10 +
              #13#10 + 'Press OK to run.';
    ShowMessage(TmpStr);

    Deleted := DeleteOnLayer(LayerA);
    Copied  := CopyLayerInto(LayerB, LayerA, Failed);

    CntA1 := CountOnLayer(LayerA);
    CntB1 := CountOnLayer(LayerB);

    Try Board.ViewManager_FullUpdate; Except End;
    Try PCBServer.PostProcess; Except End;

    { CommaText, Count and Get on TStringList ALL turned out not to exist in
      this DelphiScript build (the compiler flagged CommaText first, then
      Count). KindsStr is therefore accumulated as a plain string with a
      Pos()-based dedupe; Pos/Copy/Length are proven in production code. }
    If KindsStr = '' Then KindsStr := 'none';

    TmpStr := '*** NOT SAVED YET ***   Press Ctrl+S to keep the result.' +
              #13#10 + '(Closing the document without saving = the change is lost.)' +
              #13#10 + #13#10 +
              'Overwrite finished.' + #13#10 + @@REPOUR_REPORT_LINE@@
              '------------------------------------------------' + #13#10 +
              'erased on A : ' + IntToStr(Deleted) + #13#10 +
              'copied B->A : ' + IntToStr(Copied) +
              '   (failed ' + IntToStr(Failed) + ')' + #13#10 +
              '------------------------------------------------' + #13#10 +
              'layer            before -> after' + #13#10 +
              '@@NAME_A@@ : ' + IntToStr(CntA0) + ' -> ' + IntToStr(CntA1) + #13#10 +
              '@@NAME_B@@ : ' + IntToStr(CntB0) + ' -> ' + IntToStr(CntB1) + #13#10 +
              '------------------------------------------------' + #13#10 +
              'delete failures: ' + IntToStr(DelFailCount) +
              '  (kinds: ' + KindsStr + ')' + #13#10 +
              'expected: A -> ' + IntToStr(CntB0) +
              ' , B unchanged at ' + IntToStr(CntB0) + #13#10 + #13#10 +
              'Ctrl+S to keep, Ctrl+Z to undo.' + #13#10 + #13#10 +
              'Design rules (name + scope) were written to' + #13#10 +
              'overwrite_layer_rules.txt next to the .PcbDoc.';

    DumpReport(TmpStr);
    ShowMessage(TmpStr);
End;
'''

PRJ = ("[Design]\r\nVersion=1.0\r\nHierarchyMode=0\r\n\r\n"
       "[Document1]\r\nDocumentPath=@@PASNAME@@\r\n")


def build_pas(name_a: str, name_b: str, stem: str = "",
              repour: bool = False) -> str:
    """生成 .pas 正文（纯 ASCII，CRLF 由调用方负责）。"""
    a, b = validate_pair(name_a, name_b)

    # 重铺开关。
    #   用户实测结论：把源层的铜覆盖到目标层、**且不重铺**，源层已铺好的形状
    #   （热焊盘辐条/间隙已经是"铜的几何"）会原样保留；一旦重铺，就会按目标层
    #   的 connect style 规则重算 —— 于是目标层变成规则的默认值（Direct），
    #   源层的形状丢失。所以这里默认 **不重铺**。
    #   注意代价：本模块用 Prim.Replicate 复制多边形，只带轮廓不带填充，
    #   所以"不重铺"时多边形可能保持未铺铜状态 —— 需要时把开关打开即可。
    if repour:
        rebuild_call = "Try Poly.Rebuild; Except End;"
        analyze_call = "Try Board.AnalyzeNet(NetObj); Except End;"
        report_line = "'repour        : ON  (polygons rebuilt)' + #13#10 +"
        mode = "REPOUR"
    else:
        rebuild_call = "{ repour skipped by choice - copied copper kept as-is }"
        analyze_call = "{ AnalyzeNet skipped by choice }"
        report_line = "'repour        : OFF (copied copper kept as-is)' + #13#10 +"
        mode = "NO-REPOUR"

    out = _TEMPLATE
    for tok, val in (("@@NAME_A@@", a), ("@@NAME_B@@", b),
                     ("@@STEM@@", stem or STEM_PREFIX),
                     ("@@REBUILD_CALL@@", rebuild_call),
                     ("@@ANALYZE_CALL@@", analyze_call),
                     ("@@REPOUR_REPORT_LINE@@", report_line),
                     ("@@REPOUR_MODE@@", mode)):
        out = out.replace(tok, val)
    if "@@" in out:
        raise LayerPickError("模板里还有未替换的占位符: "
                             + ", ".join(sorted(set(re.findall(r"@@\w+@@", out)))))
    return out


def prune_old(out_dir: str, keep_sets: int = 0, keep_baks: int = 0,
              log=None) -> list:
    """把过旧的套件/备份**移动**到 _old/（不删除）。"""
    keep_sets = keep_sets or KEEP_SETS
    keep_baks = keep_baks or KEEP_BAKS
    moved = []
    try:
        names = os.listdir(out_dir)
    except OSError:
        return moved
    stems = sorted({m.group(1) for n in names
                    for m in [re.fullmatch(
                        re.escape(STEM_PREFIX) + r"_\d{8}_\d{6}\.(pas|PrjScr)", n)]
                    if m})
    victims = []
    if len(stems) > keep_sets:
        for st in stems[:-keep_sets]:
            for ext in (".pas", ".PrjScr"):
                victims.append(st + ext)
    baks = sorted((n for n in names if ".bak_" in n),
                  key=lambda n: (os.path.getmtime(os.path.join(out_dir, n)), n),
                  reverse=True)
    victims += baks[keep_baks:]
    if not victims:
        return moved
    dest = os.path.join(out_dir, "_old")
    os.makedirs(dest, exist_ok=True)
    for n in victims:
        src = os.path.join(out_dir, n)
        if not os.path.isfile(src):
            continue
        tgt = os.path.join(dest, n)
        if os.path.exists(tgt):
            tgt = os.path.join(dest, "%s.%d" % (n, int(time.time())))
        try:
            shutil.move(src, tgt)
            moved.append(n)
        except Exception as e:
            PRUNE_ERRORS.append("%s: %s" % (n, e))
    if log and moved:
        log("   归档 %d 个旧文件 -> _old/" % len(moved))
    return moved


def write_script(out_dir: str, name_a: str, name_b: str,
                 stem: str = "", repour: bool = False) -> tuple[str, str]:
    """生成 <stem>.pas + <stem>.PrjScr，返回两个路径。"""
    os.makedirs(out_dir, exist_ok=True)
    if not stem:
        stem = default_stem()
    pas = os.path.join(out_dir, stem + ".pas")
    prj = os.path.join(out_dir, stem + ".PrjScr")
    body = build_pas(name_a, name_b, stem=stem, repour=repour)
    body = body.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")
    with open(pas, "wb") as f:
        f.write(body.encode("ascii"))
    with open(prj, "wb") as f:
        f.write(PRJ.replace("@@PASNAME@@", stem + ".pas").encode("ascii"))
    prune_old(out_dir)
    return pas, prj


if __name__ == "__main__":
    import sys
    a = sys.argv[1] if len(sys.argv) > 1 else "L5_P"
    b = sys.argv[2] if len(sys.argv) > 2 else "L7_B"
    rp = (len(sys.argv) > 3 and sys.argv[3].lower() in ("1", "on", "true", "repour"))
    _HERE = os.path.dirname(os.path.abspath(__file__))
    # 与 overwrite_page.py 的 SCRIPT_DIR 算法保持一致（仓库根/scripts/altium_swap）。
    # 原来写 here/altium_swap，会落到 gui/altium_tools/altium_swap —— 与 GUI 路径不一致。
    out = os.path.join(os.path.dirname(os.path.dirname(_HERE)),
                       "scripts", "altium_swap")
    p1, p2 = write_script(out, a, b, repour=rp)
    print("written:", p1)
    print("written:", p2)
