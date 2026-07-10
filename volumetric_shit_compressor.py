#!/usr/bin/env python3
"""
volumetric_shit_compressor.py

把一个结构清晰的 web 项目(html + 外链 css/js)打包成一个交互错杂、
无注释、无法一眼看懂结构的巨型单文件 HTML，用于整蛊朋友。

原理:
  1. 从入口 html 里找出所有 <link rel="stylesheet" href=...> 和 <script src=...>
  2. 读入对应文件内容, 连同 html 里原有的内联 <style>/<script> 一起收集
  3. 用 terser / csscompressor 去注释 + 压缩 (JS 若是 ES Module 入口, 先用
     esbuild 递归打包所有本地 import)
  4. 在"安全边界"(css 规则结尾 '}' / js 语句结尾 ';' 或代码块结尾 '}',
     且正确跳过字符串/模板字符串内部的同类字符) 把 css 和 js 各自切成 N 块
  5. 把这些块打散插入到 body 内的不同位置, 但块与块之间保持原有相对顺序
     (所以 css 层叠顺序、js 执行顺序都不会被破坏, 功能不受影响, 只是
     肉眼看起来乱七八糟)
  6. 去掉所有 html 注释, 压平缩进换行, 输出一个巨大的单文件 html

用法:
  python volumetric_shit_compressor.py <project_dir> <entry_html> -o output.html [--chunks 6] [--seed 42]

示例:
  python volumetric_shit_compressor.py ./myproject index.html -o output.html --chunks 8
"""

import argparse
import random
import re
from pathlib import Path

import shutil
import subprocess

try:
    from csscompressor import compress as css_compress
except ImportError:
    css_compress = None

# 优先用 terser (支持 ES6+ 模板字符串/箭头函数等, 不会像 jsmin 那样
# 误伤反引号模板字符串内部的空白, 从而改变实际显示文本)
def find_bin(name: str) -> str:
    """依次在 PATH / 当前目录 node_modules / 脚本所在目录 node_modules 里找可执行文件"""
    found = shutil.which(name)
    if found:
        return found
    for base in (Path.cwd(), Path(__file__).parent):
        candidate = base / "node_modules" / ".bin" / name
        if candidate.exists():
            return str(candidate)
    return name  # 找不到就直接用名字, 后面调用会报错/被捕获


_TERSER_BIN = find_bin("terser")
_ESBUILD_BIN = find_bin("esbuild")


def bundle_es_module(entry_path: Path) -> str:
    """
    用 esbuild 把一个 ES Module 入口文件(及其递归 import 的所有本地模块)
    正确打包成一个语义等价的单文件 js (依赖关系/作用域/求值顺序都由
    esbuild 保证正确, 不用自己手写脆弱的 import 解析器)。
    打包失败时(比如没装 esbuild, 或引用了 npm 包而不是本地文件)会打印
    警告并退回到"只读入口文件原文"的旧行为 —— 这种情况下如果确实有
    本地相对路径 import, 打出的最终 html 大概率会在浏览器里报错,
    需要你自己检查一下。
    """
    try:
        result = subprocess.run(
            [_ESBUILD_BIN, str(entry_path), "--bundle", "--format=iife"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
        else:
            print(
                f"[警告] esbuild 打包 {entry_path.name} 失败, 将退回读取原文 "
                f"(内部 import 的相对路径文件很可能无法在最终 html 里正常工作):\n"
                f"{result.stderr}",
            )
    except Exception as e:
        print(
            f"[警告] 未能调用 esbuild ({e}), 将退回读取原文 "
            f"(如果 {entry_path.name} 里有 import 本地文件, 建议先 `npm install esbuild`)",
        )
    return entry_path.read_text(encoding="utf-8", errors="ignore")




# ---------- 基础工具 ----------

def strip_html_comments(html: str) -> str:
    return re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)


def minify_css(css: str) -> str:
    if css_compress:
        try:
            return css_compress(css)
        except Exception:
            pass
    # 兜底: 简单去注释 + 压空白
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    css = re.sub(r"\s+", " ", css)
    return css.strip()


def minify_js(js: str) -> str:
    try:
        result = subprocess.run(
            [_TERSER_BIN, "-c", "--comments", "false"],
            input=js,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    # 兜底: 只去掉块注释与行注释开头的整行(尽量保守, 避免误伤字符串)
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.DOTALL)
    js = re.sub(r"(?m)^\s*//.*$", "", js)
    return js.strip()


# ---------- 安全分块 (跳过字符串/模板字符串) ----------

def _find_top_level_boundaries(code: str, boundary_chars: set) -> list:
    """
    扫描 code, 找出所有"深度为0且不在字符串内"的 boundary_chars 位置(char之后的index)。
    用于在这些安全边界处切分代码而不破坏语法。
    """
    depth = 0
    in_str = None  # None / "'" / '"' / '`'
    escape = False
    boundaries = []
    i = 0
    n = len(code)
    while i < n:
        c = code[i]
        if in_str:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == in_str:
                in_str = None
        else:
            if c in ("'", '"', "`"):
                in_str = c
            elif c in "({[":
                depth += 1
            elif c in ")}]":
                depth = max(0, depth - 1)
                if depth == 0 and c in boundary_chars:
                    boundaries.append(i + 1)
            elif depth == 0 and c in boundary_chars:
                boundaries.append(i + 1)
        i += 1
    return boundaries


def split_into_chunks(code: str, n_chunks: int, boundary_chars: set) -> list:
    code = code.strip()
    if not code:
        return []
    if n_chunks <= 1:
        return [code]

    boundaries = _find_top_level_boundaries(code, boundary_chars)
    boundaries = [b for b in boundaries if 0 < b < len(code)]
    if not boundaries:
        return [code]

    # 从候选边界里等距挑 n_chunks-1 个切点
    step = len(boundaries) / n_chunks
    chosen = sorted({boundaries[int(step * k)] for k in range(1, n_chunks) if int(step * k) < len(boundaries)})

    chunks = []
    prev = 0
    for pos in chosen:
        piece = code[prev:pos].strip()
        if piece:
            chunks.append(piece)
        prev = pos
    tail = code[prev:].strip()
    if tail:
        chunks.append(tail)
    return chunks if chunks else [code]


# ---------- 收集资源 ----------

LINK_CSS_RE = re.compile(
    r'<link\b[^>]*rel=["\']stylesheet["\'][^>]*href=["\']([^"\']+)["\'][^>]*/?>'
    r'|<link\b[^>]*href=["\']([^"\']+)["\'][^>]*rel=["\']stylesheet["\'][^>]*/?>',
    re.IGNORECASE,
)
SCRIPT_SRC_RE = re.compile(
    r'<script\b([^>]*)\bsrc=["\']([^"\']+)["\']([^>]*)>\s*</script>', re.IGNORECASE
)
INLINE_STYLE_RE = re.compile(r"<style\b[^>]*>(.*?)</style>", re.IGNORECASE | re.DOTALL)
INLINE_SCRIPT_RE = re.compile(
    r'<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>', re.IGNORECASE | re.DOTALL
)


def collect_and_strip(html: str, base_dir: Path):
    css_parts = []
    js_parts = []

    def css_link_sub(m):
        href = m.group(1) or m.group(2)
        fpath = (base_dir / href).resolve()
        if fpath.exists():
            css_parts.append(fpath.read_text(encoding="utf-8", errors="ignore"))
        return ""

    html = LINK_CSS_RE.sub(css_link_sub, html)

    module_entries_bundled = 0

    def script_src_sub(m):
        nonlocal module_entries_bundled
        attrs = f"{m.group(1) or ''} {m.group(3) or ''}"
        src = m.group(2)
        is_module = bool(re.search(r'type\s*=\s*["\']module["\']', attrs, re.IGNORECASE))
        fpath = (base_dir / src).resolve()
        if fpath.exists():
            if is_module:
                js_parts.append(bundle_es_module(fpath))
                module_entries_bundled += 1
            else:
                js_parts.append(fpath.read_text(encoding="utf-8", errors="ignore"))
        return ""

    html = SCRIPT_SRC_RE.sub(script_src_sub, html)

    if module_entries_bundled > 1:
        print(
            "[提示] 检测到多个 <script type=\"module\"> 入口, 每个都会被独立打包。"
            "如果它们之间 import 了同一个共享模块(比如共享状态的 store.js), "
            "打包后会各自持有一份独立副本, 而不是像浏览器原生 ES Module 那样"
            "只共享同一份实例 —— 如果那个共享模块里有需要跨入口共享的状态,"
            "行为可能会和原项目不一致, 建议检查一下。"
        )

    def inline_style_sub(m):
        css_parts.append(m.group(1))
        return ""

    html = INLINE_STYLE_RE.sub(inline_style_sub, html)

    def inline_script_sub(m):
        js_parts.append(m.group(1))
        return ""

    html = INLINE_SCRIPT_RE.sub(inline_script_sub, html)

    return html, "\n".join(css_parts), "\n".join(js_parts)


# ---------- 打散插入 ----------

CLOSING_TAG_RE = re.compile(r"</[a-zA-Z][a-zA-Z0-9\-]*>")
SELF_CLOSING_OR_VOID_RE = re.compile(
    r"<(?:br|hr|img|input|meta|link|source|track|area|col|embed|wbr)\b[^>]*/?>",
    re.IGNORECASE,
)


def scatter_into_body(html: str, wrapped_chunks: list, rng: random.Random) -> str:
    """
    把 wrapped_chunks (已经是 '<style>...</style>' 或 '<script>...</script>' 字符串的列表,
    且列表顺序即为需要保持的相对顺序) 打散插入到 <body> 内部的随机标签之后,
    但保持它们在结果中出现的相对顺序不变。
    """
    body_match = re.search(r"<body\b[^>]*>", html, re.IGNORECASE)
    end_match = re.search(r"</body>", html, re.IGNORECASE)
    if not body_match or not end_match:
        # 没有明显的 body, 直接全部拼在末尾
        return html + "\n" + "\n".join(wrapped_chunks)

    body_start = body_match.end()
    body_end = end_match.start()
    body_content = html[body_start:body_end]

    # 找到 body 内所有"闭合标签之后"/"自闭合标签之后"的位置作为可插入点。
    # 这样插入的内容会成为兄弟节点, 而不是被塞进某个还有意义文本内容的
    # 元素(如 <p>/<button>)内部, 避免污染该元素的 textContent/innerHTML。
    insertion_points = [m.end() for m in CLOSING_TAG_RE.finditer(body_content)]
    insertion_points += [m.end() for m in SELF_CLOSING_OR_VOID_RE.finditer(body_content)]
    insertion_points = sorted(set(insertion_points))
    if not insertion_points:
        insertion_points = [len(body_content)]

    # 为每个 chunk 随机选一个插入点, 但保证多个 chunk 若选到同一点时,
    # 仍按原始 chunk 顺序排列(稳定排序即可保证相对顺序不被打乱)
    picks = [(rng.choice(insertion_points), idx, chunk) for idx, chunk in enumerate(wrapped_chunks)]
    picks.sort(key=lambda x: (x[0], x[1]))  # 按插入点位置排序, 位置相同则按原顺序

    # 从后往前插入, 避免位置偏移
    picks.sort(key=lambda x: x[0], reverse=True)
    new_body = body_content
    # 需要保证同一插入点多个 chunk 时相对顺序正确: 因为是从后往前插入同一点,
    # 后插入的会排在前面, 所以这里对同一位置的分组要按原始 idx 逆序插入
    from itertools import groupby
    grouped = []
    for pos, group in groupby(sorted(picks, key=lambda x: -x[0]), key=lambda x: x[0]):
        group_list = sorted(list(group), key=lambda x: x[1], reverse=True)  # idx 逆序
        grouped.append((pos, group_list))

    for pos, group_list in grouped:
        insert_text = "".join(item[2] for item in group_list)
        new_body = new_body[:pos] + insert_text + new_body[pos:]

    return html[:body_start] + new_body + html[body_end:]


# ---------- 主流程 ----------

def bundle(project_dir: str, entry_html: str, out_path: str, n_chunks: int = 6, seed: int = None):
    base_dir = Path(project_dir).resolve()
    entry_path = base_dir / entry_html
    if not entry_path.exists():
        raise FileNotFoundError(f"入口文件不存在: {entry_path}")

    rng = random.Random(seed)

    html = entry_path.read_text(encoding="utf-8", errors="ignore")
    html = strip_html_comments(html)

    html, raw_css, raw_js = collect_and_strip(html, base_dir)

    css_min = minify_css(raw_css) if raw_css.strip() else ""
    js_min = minify_js(raw_js) if raw_js.strip() else ""

    css_chunks = split_into_chunks(css_min, n_chunks, boundary_chars={"}"})
    js_chunks = split_into_chunks(js_min, n_chunks, boundary_chars={";", "}"})

    wrapped = []
    for c in css_chunks:
        wrapped.append(f"<style>{c}</style>")
    for j in js_chunks:
        wrapped.append(f"<script>{j}</script>")

    rng.shuffle(wrapped)  # 打乱 style/script 块之间的"物理书写顺序"(不影响各自内部顺序,
                          # 因为 css_chunks/js_chunks 各自列表内部顺序已在下面保留)

    # 重新保证: css 内部相对顺序 + js 内部相对顺序都不因 shuffle 改变
    # 上面的 shuffle 是打乱 "css块和js块混合列表" 的整体顺序,
    # 但 scatter_into_body 里对相同插入点用 idx 保序, 不同插入点则看物理位置,
    # 而不同 <style>/<script> 标签本身在文档中天然按书写顺序生效,
    # 所以只要 wrapped 列表里 css_chunks 彼此的先后关系、js_chunks 彼此的先后关系
    # 保持不变即可(css 与 css 之间/js 与 js 之间不能相对换序), 因此改为:

    # CSS 块打散插入 body 各处是安全的: 浏览器只关心 <style> 标签之间的
    # 相对先后顺序(层叠优先级), 不关心它们在 DOM 树里具体挂在哪个位置。
    css_wrapped = [f"<style>{c}</style>" for c in css_chunks]
    html = scatter_into_body(html, css_wrapped, rng)

    # JS 块则统一放在 </body> 之前(这本身也是网页常见最佳实践的位置),
    # 保证执行时全部 DOM 已解析完毕, 不会因为脚本被插到某个元素"之前"
    # 而在该脚本试图操作那个元素时找不到它、导致页面直接报错。
    # 仍然拆成多个互相看起来无关的 <script> 标签, 阅读体验依旧混乱。
    js_wrapped = [f"<script>{j}</script>" for j in js_chunks]
    if js_wrapped:
        end_match = re.search(r"</body>", html, re.IGNORECASE)
        if end_match:
            pos = end_match.start()
            html = html[:pos] + "".join(js_wrapped) + html[pos:]
        else:
            html = html + "".join(js_wrapped)

    # 压平空白, 让它看起来更像一坨
    html = re.sub(r">\s+<", "><", html)
    html = re.sub(r"[ \t]{2,}", " ", html)
    html = html.strip()

    Path(out_path).write_text(html, encoding="utf-8")
    return out_path


def main():
    parser = argparse.ArgumentParser(description="把 web 项目打包成一个难以理解的巨型 html (恶作剧用)")
    parser.add_argument("project_dir", help="项目根目录")
    parser.add_argument("entry_html", help="入口 html 文件名(相对 project_dir)")
    parser.add_argument("-o", "--output", default="vsc_output.html", help="输出文件路径")
    parser.add_argument("--chunks", type=int, default=6, help="css/js 各自切成几块打散插入")
    parser.add_argument("--seed", type=int, default=None, help="随机种子, 固定后每次结果一致")
    args = parser.parse_args()

    out = bundle(args.project_dir, args.entry_html, args.output, args.chunks, args.seed)
    print(f"完成 -> {out}")


if __name__ == "__main__":
    main()
