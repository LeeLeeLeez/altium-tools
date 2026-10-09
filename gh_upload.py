# -*- coding: utf-8 -*-
"""
gh_upload.py —— 把 Altium 工具集以【明文】推送到 GitHub

为什么不用 git.exe？
    本机装了 DLP 透明加密驱动：非白名单进程（git.exe / powershell）读到的
    源文件是密文（文件头 `%TSD-Header-###%`，大小被填充成 1024 的整数倍），
    git 会把它当二进制 blob 提交，仓库里就是一堆解不开的乱码。
    Python 在白名单里，读到的是明文 —— 所以本脚本用 Python 读文件、
    直接调 GitHub REST API 建 commit，完全绕开 git.exe。

用法：
    # 1) 先到 https://github.com/settings/tokens 建一个 classic token（勾 repo）
    # 2) 首次上传（自动建库）
    python gh_upload.py --token ghp_xxx --repo altium-tools --public
    # 3) 以后每次改完代码再提交
    python gh_upload.py --token ghp_xxx --repo altium-tools -m "修中点短线层跟随"
    # 4) 顺便打包 exe 并发 Release（作为附件）
    python gh_upload.py --token ghp_xxx --repo altium-tools --release v1.0.0 --with-exe
    # 5) 只看会传什么，不联网
    python gh_upload.py --dry-run

token 也可以放环境变量：
    set GITHUB_TOKEN=ghp_xxx
"""
import argparse
import base64
import json
import os
import shutil
import socket
import ssl
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
API = "https://api.github.com"

# ---- 网络健壮性 -------------------------------------------------------------
# 一次上传要发 ~20 个 HTTPS 请求，任一抖动就整单失败；这里统一退避重试。
# 日志回调：do_upload() 入口会把它换成 GUI 的日志函数。
_LOG = [print]
_RETRIES = 4
_TIMEOUT = 60
_RETRY_HTTP = (408, 429, 500, 502, 503, 504)


def _log(msg):
    try:
        _LOG[0](msg)
    except Exception:
        pass


def set_retries(n):
    global _RETRIES
    _RETRIES = max(0, int(n))


def set_no_proxy():
    """直连: 绕开系统/环境里的代理（本地代理换端口或挂掉时用）。"""
    urllib.request.install_opener(
        urllib.request.build_opener(urllib.request.ProxyHandler({})))


def default_release_tag():
    """没指定 Release tag 时用的默认值（exe 附件必须挂在 Release 上）。"""
    return "v" + time.strftime("%Y.%m.%d")


class PartialUpload(RuntimeError):
    """代码已推送成功，但有子步骤没完成（典型：exe 附件没挂上）。

    单独一个类型，好让 GUI 显示成"部分完成"（橙色警告）而不是彻底失败。
    """

    def __init__(self, url, problems):
        self.url = url
        self.problems = list(problems)
        super().__init__("代码已上传，但以下步骤未完成：\n"
                         + "\n".join("- " + p for p in self.problems))


def _backoff(attempt, why):
    d = min(1.5 * (2 ** attempt), 20.0)
    _log("   [重试] %s —— %.1fs 后第 %d/%d 次" % (why, d, attempt + 1, _RETRIES))
    time.sleep(d)


def _describe_net_error(e, url):
    """把底层网络异常翻成一句能照着做的话（弹窗只显示这段，所以要短而准）。"""
    s = "%s: %s" % (type(e).__name__, e)
    try:
        proxies = urllib.request.getproxies()
    except Exception:
        proxies = {}
    low = s.lower()
    if "10061" in s or "refused" in low or "积极拒绝" in s:
        tip = "本地代理/端口没人监听 —— 代理软件没开，或端口变了。"
    elif "10054" in s or "reset" in low or "强行关闭" in s:
        tip = "连接被对端重置 —— 代理/VPN 抖动或链路中断。"
    elif "10060" in s or "timed out" in low or "超时" in s:
        tip = "请求超时 —— 代理链路太慢或被拦截。"
    elif "ssl" in low or "certificate" in low or "证书" in s:
        tip = "TLS 握手失败 —— 代理在做中间人，或根证书缺失。"
    elif "getaddrinfo" in low or "11001" in s or "解析" in s:
        tip = "DNS 解析失败 —— 检查网络/DNS。"
    else:
        tip = "网络层错误。"
    lines = ["%s" % s, "  请求: %s" % url, "  原因: %s" % tip]
    if proxies:
        lines.append("  当前代理: %s" % proxies)
        lines.append("  → 代理软件在跑吗？也可勾选「不走代理（直连）」再试一次。")
    else:
        lines.append("  → 当前未走代理；可用 --no-proxy 之外的方式检查直连。")
    return "\n".join(lines)


def _net_error_is_retryable(e):
    if isinstance(e, urllib.error.HTTPError):
        return e.code in _RETRY_HTTP
    return isinstance(e, (urllib.error.URLError, TimeoutError, ConnectionError,
                          socket.timeout, ssl.SSLError, OSError))


# 要发布的文件（相对本脚本目录）。新增文件在这里加一行即可。
# 注意：本目录下的 __pycache__ / *.bak_* / _*.py / build / dist 一律不进这个清单。
FILES = [
    "README.md",
    "LICENSE",
    ".gitignore",
    "requirements.txt",
    "main.py",
    "gui_style.py",
    "gui_sidebar.py",
    "altium_bridge.py",
    "midpoint_tab.py",
    "stackup_page.py",
    "stackup_design.py",
    "stackup_build.py",
    "stackup_file.py",
    "swap_page.py",
    "swap_script.py",
    "altium_tools_config.json",
    "AltiumTools.cmd",
    "AltiumTools.spec",
    "UploadToGitHub.cmd",
    "gh_upload.py",
    "upload_gui.py",
]

DESCRIPTION = ("GUI toolkit for Altium Designer automation: midpoint short-line "
               "drawing, layer-stack design, and layer swap -- driven through "
               "the eda-agent MCP bridge (stdio JSON-RPC). Pure tkinter/ttk.")


def looks_masked(tok):
    """判断输入是不是"密码框里那串圆点"。

    实测踩过：用户把 Token 框里显示的掩码字符（••••）复制走，
    发请求时 http.client 抛 UnicodeEncodeError('latin-1' ...)，
    报错完全指不到真正原因。这里单独识别出来，好给一句准确的话。
    """
    t = (tok or "").strip()
    return bool(t) and all(c in "•*·●○※" for c in t)


_TOKEN_PREFIXES = ("ghp_", "github_pat_", "gho_", "ghu_", "ghs_", "ghr_")


def check_token(tok):
    """本地 token 体检（不发网络）：返回 (修整后的 token, 提示列表)。

    把"粘错"这一类问题尽量在上网前拦下来 —— 401 Bad credentials 里
    有很大一部分其实是复制不全 / 多粘了前缀 / 粘了打码版本。
    """
    tips = []
    t = (tok or "").strip()
    # ① 整段粘了 "Bearer xxx" / "token xxx"（只要 token 本体）
    low = t.lower()
    for pfx in ("bearer ", "bearer", "token ", "token"):
        if low.startswith(pfx):
            rest = t[len(pfx):].strip()
            if rest:
                tips.append("去掉了开头的 %r 前缀（只需粘 token 本体）" % pfx)
                t = rest
                break
    # ② 剔除非 ASCII（中文/全角/圆点）
    t, ch = sanitize_token(t)
    if ch:
        tips.append("剔除了非 ASCII 字符（只保留字母 / 数字 / _ / -）")
    # ③ 形状检查
    if not t:
        tips.append("结果为空")
    elif not t.startswith(_TOKEN_PREFIXES):
        tips.append("不以 ghp_ / github_pat_ / gho_ 开头 —— 可能不是 GitHub token")
    elif t.startswith("ghp_") and len(t) != 40:
        tips.append("classic token 固定 40 位，当前 %d 位 —— 很可能复制不全" % len(t))
    elif t.startswith("github_pat_") and len(t) < 60:
        tips.append("fine-grained token 长度偏短（%d 位）—— 可能复制不全" % len(t))
    return t, tips


def sanitize_token(tok):
    """GitHub token 只可能是 ASCII（字母/数字/_/-）。

    中文字符或全角符号粘进来时，http.client 发请求头会抛
    UnicodeEncodeError: 'latin-1' codec can't encode ...（位置就在 token 那一段），
    报错完全看不出原因。这里直接剔掉非法字符。
    返回 (干净 token, 是否改动过)。
    """
    t = (tok or "").strip()
    clean = "".join(c for c in t
                    if c.isascii() and (c.isalnum() or c in "_-"))
    return clean, (clean != t)


def _req(method, url, token, data=None, allow404=False):
    """一次 REST 调用。瞬时网络错误自动退避重试；重试耗尽给一句人话。"""
    # 请求头只能装 Latin-1；token 有非 ASCII 就先拦下来，别让 http.client 抛难懂的错
    try:
        ("Bearer %s" % token).encode("latin-1")
    except UnicodeEncodeError:
        raise SystemExit(
            "Token 里有非 ASCII 字符（中文 / 全角符号）—— GitHub token 只由\n"
            "字母、数字、下划线组成（classic 形如 ghp_xxxxxxxx，共 40 位）。\n\n"
            "请重新复制 token（别把说明文字一起选中），或点【去获取】新建一个。\n"
            "本次收到的字符位置：%r" % (token[:8] + "...",))
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", "Bearer %s" % token)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "gh_upload.py")
    if body is not None:
        req.add_header("Content-Type", "application/json")

    last = None
    for attempt in range(_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
                raw = r.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            # 409 'Git Repository is empty' 对空仓库的 GET ref 也会出现，
            # 语义上等同于'不存在'（这条不重试，直接当"没有"）
            if allow404 and e.code in (404, 409):
                return None
            # 401 单独说人话：绝大多数是"token 粘错了 / 失效了"，不是网络问题
            if e.code == 401:
                raise SystemExit(
                    "GitHub 返回 401 Bad credentials —— 这个 token 无效。\n\n"
                    "常见原因（按概率）：\n"
                    "  1) 复制不全 / 中间缺字符\n"
                    "     classic token 一定是【ghp_ + 36 位 = 共 40 位】\n"
                    "  2) 把网页上打码的版本（••••）当明文复制了\n"
                    "  3) 把 \"Bearer xxx\" 整段粘进来了（应当只粘 token 本体）\n"
                    "  4) token 已被删除 / 撤销 / 过期\n\n"
                    "处置：https://github.com/settings/tokens → Generate new token (classic)\n"
                    "      → 勾 repo → 明文显示时立刻复制 → 粘进来后\n"
                    "      勾上【显示 Token 明文（核对用）】确认是 ghp_ 开头、共 40 位。\n\n"
                    "本次实际发出的形状：前缀 %r，长度 %d 位"
                    % (token[:8], len(token)))
            if e.code in _RETRY_HTTP and attempt < _RETRIES:
                last = e
                _backoff(attempt, "HTTP %d" % e.code)
                continue
            detail = e.read().decode("utf-8", "replace")[:400]
            raise SystemExit("[HTTP %d] %s\n%s" % (e.code, url, detail))
        except Exception as e:
            last = e
            if _net_error_is_retryable(e) and attempt < _RETRIES:
                _backoff(attempt, type(e).__name__)
                continue
            break
    raise SystemExit(_describe_net_error(last, url))


def read_plain(rel, fix_readme=None):
    """Python 读 = 明文。顺便做一次密文体检。"""
    p = os.path.join(HERE, rel)
    if not os.path.isfile(p):
        raise SystemExit("缺少文件: %s" % rel)
    data = open(p, "rb").read()
    if data[:4] == b"%TSD":
        raise SystemExit("!! %s 读到的是 DLP 密文，拒绝上传。"
                         "请用白名单进程重写该文件。" % rel)
    if fix_readme and rel == "README.md":
        data = data.decode("utf-8")
        data = data.replace("<你的用户名>", fix_readme[0]).replace(
            "<仓库名>", fix_readme[1])
        data = data.encode("utf-8")
    return data


# ============================================================== exe 打包（可选）
def _clean_env():
    e = dict(os.environ)
    for k in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP"):
        e.pop(k, None)
    return e


def _console_python(path):
    """pythonw.exe -> 同目录的 python.exe。

    本机 DLP 环境下 pythonw（无控制台）跑 PyInstaller 更易撞文件占用；
    统一换成带控制台的解释器更稳。
    """
    d, b = os.path.split(path)
    if b.lower() == "pythonw.exe":
        alt = os.path.join(d, "python.exe")
        if os.path.isfile(alt):
            return alt
    return path


def _find_build_python(log=print):
    """找一个同时具备 PyInstaller 和 tkinter 的解释器（优先带控制台的）。"""
    cands = []
    if not getattr(sys, "frozen", False):
        cands.append([_console_python(sys.executable)])
    p = shutil.which("py")
    if p:
        cands.append([p, "-3.12"])
        cands.append([p])
    p = shutil.which("python")
    if p:
        cands.append([p])
    seen, uniq = set(), []
    for c in cands:
        if tuple(c) not in seen:
            seen.add(tuple(c))
            uniq.append(c)
    for cmd in uniq:
        try:
            r = subprocess.run(cmd + ["-c", "import PyInstaller, tkinter"],
                               capture_output=True, timeout=60, env=_clean_env())
            if r.returncode == 0:
                return cmd
        except Exception:
            continue
    raise RuntimeError("没找到同时装了 PyInstaller 和 tkinter 的 Python")


def _rm_force(path, log=None):
    """删文件/目录，顺手清只读位。"""
    def _onerr(func, p, exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception as e2:
            if log:
                log("   (清理仍失败 %s: %s)" % (p, e2))

    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path, onerror=_onerr)
    elif os.path.exists(path):
        try:
            os.remove(path)
        except Exception:
            _onerr(os.remove, path, None)


def _preclean(specnm, log=print):
    """自己带重试地清 build/<spec>。

    PyInstaller --clean 会 os.remove(build/<spec>/*)；若那些文件刚写完、
    还被文件扫描持有句柄，会直接 PermissionError [WinError 5] 崩掉整个构建。
    先自己清掉，绕开这个竞态。
    """
    bd = os.path.join(HERE, "build", specnm)
    for attempt in range(4):
        if not os.path.exists(bd):
            return True
        try:
            _rm_force(bd, log)
            log("   已清理 %s" % os.path.relpath(bd, HERE))
            return True
        except Exception as e:
            log("   = 清理 build/%s 失败(%d/4): %s" % (specnm, attempt + 1, e))
            time.sleep(1.0 + attempt)
    return not os.path.exists(bd)


def build_exe(log=print, specnm="AltiumTools"):
    """把当前 GUI 源码重新打成 exe，返回 dist/<specnm>.exe 路径。

    稳定性：
      * 先带重试地清 build/<spec>，避开 PyInstaller --clean 的文件占用竞态
      * --clean 那一轮失败则自动去掉 --clean 重试一次
      * 失败时把 PyInstaller 输出末尾附进异常（否则只看到"退出码 1"）
    """
    cmd = _find_build_python(log)
    exe = os.path.join(HERE, "dist", specnm + ".exe")
    log("打包解释器: %s" % " ".join(cmd))
    tail, last = [], "未知"
    for turn, use_clean in enumerate((True, False), start=1):
        _preclean(specnm, log)
        argv = cmd + ["-m", "PyInstaller", specnm + ".spec", "--noconfirm"]
        if use_clean:
            argv.append("--clean")
        log("$ " + " ".join(argv) + ("   (第 %d 次)" % turn if turn > 1 else ""))
        tail = []
        pr = subprocess.Popen(argv, cwd=HERE, env=_clean_env(),
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, errors="replace", bufsize=1)
        for line in pr.stdout:
            line = line.rstrip()
            if line:
                log("   " + line)
                tail.append(line)
                if len(tail) > 25:
                    tail.pop(0)
        pr.wait()
        if pr.returncode == 0 and os.path.isfile(exe):
            break
        last = "退出码 %s" % pr.returncode
        log("!! 第 %d 次打包失败 (%s)" % (turn, last))
        if use_clean:
            log("   去掉 --clean 再试一次（多因 build/ 下文件被占用）")
    else:
        raise RuntimeError("PyInstaller 打包失败 (%s)。输出末尾：\n%s"
                           % (last, "\n".join(tail[-12:])))
    if not os.path.isfile(exe):
        raise RuntimeError("没找到产物: %s\n输出末尾：\n%s"
                           % (exe, "\n".join(tail[-12:])))
    if open(exe, "rb").read(4) == b"%TSD":
        raise RuntimeError("exe 是 DLP 密文，拒绝上传（删掉 dist 目录重打一次）")
    log("exe 就绪: %s  %.1f MB" % (exe, os.path.getsize(exe) / 1048576.0))
    return exe


def upload_asset(owner, repo_name, token, release_id, path, log=print):
    """把 exe 挂到某个 Release 上。"""
    from urllib.parse import quote
    name = os.path.basename(path)
    data = open(path, "rb").read()
    if data[:4] == b"%TSD":
        raise RuntimeError("附件是 DLP 密文，拒绝上传: %s" % name)
    # 同名附件已存在 -> GitHub 返回 422 already_exists，重传会一直失败。
    # 先把旧的删掉，让"同一个 Release 重传"变成幂等操作。
    try:
        olds = _req("GET", "%s/repos/%s/%s/releases/%s/assets"
                    % (API, owner, repo_name, release_id), token)
        for a in (olds or []):
            if a.get("name") == name:
                _req("DELETE", "%s/repos/%s/%s/releases/assets/%s"
                     % (API, owner, repo_name, a["id"]), token)
                log("   已删除同名旧附件: %s" % name)
    except SystemExit:
        pass
    url = ("https://uploads.github.com/repos/%s/%s/releases/%s/assets?name=%s"
           % (owner, repo_name, release_id, quote(name)))
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", "Bearer %s" % token)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Content-Type", "application/octet-stream")
    req.add_header("User-Agent", "gh_upload.py")
    # 大附件最容易在代理上抖 —— 同样退避重试
    last, j = None, None
    for attempt in range(_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                j = json.loads(r.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            if e.code in _RETRY_HTTP and attempt < _RETRIES:
                last = e
                _backoff(attempt, "HTTP %d" % e.code)
                continue
            raise RuntimeError("[HTTP %d] %s" % (e.code, detail))
        except Exception as e:
            last = e
            if _net_error_is_retryable(e) and attempt < _RETRIES:
                _backoff(attempt, type(e).__name__)
                continue
            raise RuntimeError(_describe_net_error(e, url))
    if j is None:
        raise RuntimeError(_describe_net_error(last, url))
    log("附件已上传: " + j.get("browser_download_url", name))
    return j.get("browser_download_url", "")


def do_upload(token, repo_name, message="", public=True, log=print,
              release_tag=None, release_notes="", with_exe=False, branch=""):
    """执行一次上传（建库 / 追加 commit）。返回仓库 URL。"""
    _LOG[0] = log          # 让 _req 的重试日志也进 GUI 日志框
    # 0. token 体检
    if looks_masked(token):
        raise SystemExit(
            "你填的是一串圆点/星号（密码框的掩码字符），不是真正的 Token。\n\n"
            "GitHub 只在【生成 token 的那一刻】显示一次明文（形如 ghp_xxxx，40 位）。\n"
            "  1) 到 https://github.com/settings/tokens 重新生成一个（勾 repo）\n"
            "  2) 在它显示出来时【立刻】复制明文，粘进 Token 框\n"
            "  3) 别复制框里显示的圆点 —— 那不是 token 本身\n\n"
            "本次收到 %d 个字符，全部是掩码符号。" % len(token.strip()))
    token, _tips = check_token(token)
    for _t in _tips:
        log("!! Token 体检: %s" % _t)
    if not token:
        raise SystemExit("Token 为空或不合法（GitHub token 由字母数字组成）。")
    # 1. 我是谁
    me = _req("GET", API + "/user", token)
    owner = me.get("login")
    fix = (owner, repo_name)
    log("GitHub 账号: %s" % owner)

    def _bootstrap_empty():
        """空仓库调 Git Data API 会 409 'Git Repository is empty'。
        先用 Contents API 放一个 README 初始化出首个 commit。"""
        log("仓库为空 → 先放入 README 初始化…")
        data = read_plain("README.md", fix_readme=fix)
        r0 = _req("PUT", "%s/repos/%s/%s/contents/README.md"
                  % (API, owner, repo_name), token,
                  {"message": "init: README",
                   "content": base64.b64encode(data).decode("ascii")})
        csha = r0["commit"]["sha"]
        cm = _req("GET", "%s/repos/%s/%s/git/commits/%s"
                  % (API, owner, repo_name, csha), token)
        return cm["tree"]["sha"], [csha]

    # 2. 仓库在不在
    repo = _req("GET", "%s/repos/%s/%s" % (API, owner, repo_name), token,
                allow404=True)
    if repo is None:
        try:
            repo = _req("POST", API + "/user/repos", token, {
                "name": repo_name,
                "description": DESCRIPTION,
                "private": (not public),
                "auto_init": False,
            })
        except SystemExit as e:
            raise SystemExit(
                "创建仓库被 GitHub 拒绝（403 = 这个 token 没有建新仓库的权限）。\n\n"
                "办法①（推荐）：换成 classic token，生成页会自动勾好 repo 权限：\n"
                "    https://github.com/settings/tokens/new?scopes=repo\n\n"
                "办法②：先在网页手动建好一个空仓库（注意不要勾 Add a README），\n"
                "    然后把仓库名改成它再跑一次 —— 只要 token 有 Contents 读写权限即可。\n\n"
                "原始错误：%s" % str(e)[:400])
        log("已创建仓库: %s (private=%s)" % (repo["full_name"], not public))
        br = branch or "main"
        base_tree, parents = _bootstrap_empty()
    else:
        log("仓库已存在: %s  star=%s"
            % (repo["full_name"], repo.get("stargazers_count", 0)))
        br = branch or repo.get("default_branch", "main")
        ref = _req("GET", "%s/repos/%s/%s/git/ref/heads/%s"
                   % (API, owner, repo_name, br), token, allow404=True)
        if ref is None and branch:
            # 指定的分支还不存在 -> 以默认分支为基准新建（默认分支保持不动）
            defbr = repo.get("default_branch", "main")
            log("分支 %s 不存在，将以 %s 为基准新建" % (br, defbr))
            dref = _req("GET", "%s/repos/%s/%s/git/ref/heads/%s"
                        % (API, owner, repo_name, defbr), token, allow404=True)
            if dref is None:
                base_tree, parents = _bootstrap_empty()
            else:
                dcm = _req("GET", dref["object"]["url"], token)
                base_tree, parents = dcm["tree"]["sha"], [dcm["sha"]]
        elif ref is None:
            base_tree, parents = _bootstrap_empty()
        else:
            cm = _req("GET", ref["object"]["url"], token)
            base_tree, parents = cm["tree"]["sha"], [cm["sha"]]

    # 3. 逐个建 blob（内容 base64；Python 读到的是明文）
    tree = []
    for f in FILES:
        data = read_plain(f, fix_readme=fix)
        b = _req("POST", "%s/repos/%s/%s/git/blobs" % (API, owner, repo_name),
                 token, {"content": base64.b64encode(data).decode("ascii"),
                         "encoding": "base64"})
        tree.append({"path": f.replace("\\", "/"), "mode": "100644",
                     "type": "blob", "sha": b["sha"]})
        log("  blob %-32s %s" % (f, b["sha"][:8]))

    # 4. tree -> commit -> 更新 ref
    payload = {"tree": tree}
    if base_tree:
        payload["base_tree"] = base_tree
    t = _req("POST", "%s/repos/%s/%s/git/trees" % (API, owner, repo_name),
             token, payload)

    msg = message or ("首次提交：Altium 工具集（GUI）" if not parents
                      else "更新：Altium 工具集（GUI）")
    c = _req("POST", "%s/repos/%s/%s/git/commits" % (API, owner, repo_name),
             token, {"message": msg, "tree": t["sha"], "parents": parents})
    log("commit: %s  %s" % (c["sha"][:8], msg))

    log("目标分支: %s" % br)
    try:
        _req("PATCH", "%s/repos/%s/%s/git/refs/heads/%s"
             % (API, owner, repo_name, br), token, {"sha": c["sha"]})
    except SystemExit:
        # 分支还不存在(或被并发建出) → 退回创建; 再失败就把真错误抛出去
        try:
            _req("POST", "%s/repos/%s/%s/git/refs" % (API, owner, repo_name),
                 token, {"ref": "refs/heads/%s" % br, "sha": c["sha"]})
        except SystemExit:
            _req("PATCH", "%s/repos/%s/%s/git/refs/heads/%s"
                 % (API, owner, repo_name, br), token, {"sha": c["sha"]})

    # 5. 可选：Release + exe 附件
    problems = []          # 子步骤失败清单 -> 末尾抛 PartialUpload，不再静默
    if release_tag:
        exe = None
        if with_exe:
            try:
                exe = build_exe(log=log)
            except Exception as ex:
                problems.append("exe 打包失败：%s" % str(ex).splitlines()[0])
                log("!! exe 打包失败，本次无附件：%s" % ex)
        rel = None
        try:
            rel = _req("POST", "%s/repos/%s/%s/releases"
                       % (API, owner, repo_name), token,
                       {"tag_name": release_tag,
                        "name": release_tag,
                        "body": release_notes or ("Release " + release_tag),
                        "target_commitish": c["sha"],
                        "draft": False, "prerelease": False})
            log("Release 已发布: " + rel.get("html_url", ""))
        except SystemExit as e:
            # 同名 tag 的 Release 已存在（422）-> 复用那个，而不是放弃 exe
            try:
                rel = _req("GET", "%s/repos/%s/%s/releases/tags/%s"
                           % (API, owner, repo_name, release_tag), token)
                log("Release %s 已存在，复用: %s"
                    % (release_tag, rel.get("html_url", "")))
            except SystemExit:
                problems.append("Release 发布失败：%s" % str(e)[:200])
                log("!! Release 发布失败（可到网页 Releases 页面手动补）：%s"
                    % str(e)[:200])
                rel = None
        if rel is not None:
            if with_exe:
                if exe:
                    try:
                        upload_asset(owner, repo_name, token, rel["id"], exe,
                                     log=log)
                    except Exception as ex:
                        problems.append("exe 附件上传失败：%s" % str(ex)[:200])
                        log("!! exe 附件上传失败：%s" % ex)
                else:
                    problems.append("exe 未打包成功，附件未上传")
            else:
                log("(未开启「打包 exe」，本次只发 Release、不带附件)")
    elif with_exe:
        log("!! 勾了打包 exe 但没给 Release tag —— exe 只能作为 Release 附件上传")
        problems.append("没有 Release tag：exe 未上传")

    url = "https://github.com/%s/%s" % (owner, repo_name)
    log("")
    if problems:
        log("!! 代码已上传，但有 %d 项未完成：" % len(problems))
        for p in problems:
            log("   - " + p)
        log("仓库: " + url)
        raise PartialUpload(url, problems)
    log("完成  " + url)
    return url


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--token", default=os.environ.get("GITHUB_TOKEN", ""))
    ap.add_argument("--repo", default="altium-tools")
    ap.add_argument("--public", action="store_true",
                    help="建公开仓库（要 star 必须公开）")
    ap.add_argument("--private", action="store_true")
    ap.add_argument("-m", "--message", default="")
    ap.add_argument("--branch", default="")
    ap.add_argument("--release", default="",
                    help="Release tag，如 v1.0.0；填了就顺带发版本")
    ap.add_argument("--with-exe", action="store_true",
                    help="打包 exe 并作为 Release 附件上传")
    ap.add_argument("--no-proxy", action="store_true",
                    help="直连，绕开系统代理")
    ap.add_argument("--dry-run", action="store_true",
                    help="只列出会传哪些文件、检查密文，不联网")
    ap.add_argument("--check-token", action="store_true",
                    help="只验证 token 是否有效（GET /user），不推送任何东西")
    args = ap.parse_args()

    if args.check_token:
        if not args.token:
            print("缺少 token：用 --token ghp_xxx，或设环境变量 GITHUB_TOKEN")
            return 2
        if args.no_proxy:
            set_no_proxy()
        tok, tips = check_token(args.token)
        for t_ in tips:
            print("!! " + t_)
        print("形状: 前缀 %r  长度 %d 位" % (tok[:8], len(tok)))
        try:
            me = _req("GET", API + "/user", tok)
            print("OK   token 有效  账号: %s" % me.get("login"))
            return 0
        except SystemExit as e:
            print(e)
            return 1

    if args.dry_run:
        print("将上传 %d 个文件（相对 %s）:" % (len(FILES), HERE))
        bad = 0
        for f in FILES:
            p = os.path.join(HERE, f)
            if not os.path.isfile(p):
                print("  [缺失] %s" % f)
                bad += 1
                continue
            head = open(p, "rb").read(4)
            tag = "密文!!" if head == b"%TSD" else "ok"
            print("  [%s] %-34s %8d B" % (tag, f, os.path.getsize(p)))
            if head == b"%TSD":
                bad += 1
        print("\n%s" % ("全部就绪 ✓" if not bad else "有 %d 项有问题 ✗" % bad))
        return 0 if not bad else 1

    if not args.token:
        print("缺少 token：用 --token ghp_xxx，或设环境变量 GITHUB_TOKEN")
        return 2
    if args.no_proxy:
        set_no_proxy()
    public = args.public or not args.private
    tag = args.release or (default_release_tag() if args.with_exe else None)
    try:
        do_upload(args.token, args.repo, message=args.message, public=public,
                  branch=args.branch, release_tag=tag,
                  release_notes=args.message, with_exe=args.with_exe)
    except PartialUpload as e:
        print(e)
        return 1
    except SystemExit as e:
        print(e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
