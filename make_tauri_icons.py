"""\u751f\u6210 Tauri \u56fe\u6807\uff08web/src-tauri/icons/\u3002

\u26a0\ufe0f \u672c\u673a\u88c5\u6709 DLP \u900f\u660e\u52a0\u5bc6\u9a71\u52a8\uff1a**\u65b0\u5efa\u7684 .png \u4f1a\u88ab\u52a0\u5bc6**\uff08\u6587\u4ef6\u5934 %TSD\uff09\uff0c
   \u975e\u767d\u540d\u5355\u8fdb\u7a0b\u8bfb\u51fa\u6765\u662f\u4e71\u7801\uff0c\u4e0a\u4f20\u5230 GitHub \u4e5f\u4f1a\u88ab\u62d2\u7edd\u3002
   \u800c .ico \u4e0d\u5728\u52a0\u5bc6\u7b56\u7565\u91cc\uff0c\u53ef\u4ee5\u6b63\u5e38\u4f7f\u7528\u3002
   \u56e0\u6b64\u684c\u9762\u7248\u56fe\u6807\u53ea\u7528 icon.ico\uff08Windows \u6253\u5305\u5df2\u8db3\u591f\uff09\uff0cPNG \u4e0d\u5165\u5e93\u3002
"""
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "altium_tools.ico")
OUT = os.path.join(HERE, "web", "src-tauri", "icons")


def main():
    if not os.path.isfile(SRC):
        raise SystemExit("\u7f3a\u5c11\u6e90\u56fe\u6807\uff1a%s\uff08\u8dd2 python make_icon.py \u751f\u6210\uff09" % SRC)
    os.makedirs(OUT, exist_ok=True)
    dst = os.path.join(OUT, "icon.ico")
    shutil.copyfile(SRC, dst)
    with open(dst, "rb") as f:
        head = f.read(4)
    if head.startswith(b"%TSD"):
        raise SystemExit("\u5199\u51fa\u7684 .ico \u4e5f\u88ab DLP \u52a0\u5bc6\u4e86\uff0c\u8bf7\u68c0\u67e5\u52a0\u5bc6\u7b56\u7565")
    print("\u5df2\u5199\u5165 %s (%d B)" % (dst, os.path.getsize(dst)))
    print("\u63d0\u9192\uff1a\u684c\u9762\u7248\u56fe\u6807\u53ea\u7528 .ico\uff1bPNG \u4f1a\u88ab DLP \u52a0\u5bc6\uff0c\u4e0d\u5165\u5e93\u3002")


if __name__ == "__main__":
    main()
