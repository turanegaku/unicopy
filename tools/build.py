#!/usr/bin/env python3
"""配布用に index.html / app.css / app.js を1ファイルへ結合する。

開発中は分割したまま index.html を開き、人に渡すときだけこれを通す。
出力は dist/unicopy.html。
"""
import pathlib
import sys

root = pathlib.Path(__file__).resolve().parent.parent
html = (root / "index.html").read_text(encoding="utf-8")

# 埋め込むのはこの2箇所だけ。増えたらここに足す
for ref, name, tag in [
    ('<link rel="stylesheet" href="app.css">', "app.css", "style"),
    ('<script src="app.js"></script>', "app.js", "script"),
]:
    if ref not in html:
        sys.exit(f"index.html に {ref} が無い。参照の書き方を変えたならこのスクリプトも直す")
    body = (root / name).read_text(encoding="utf-8")
    # ref 行の字下げがそのまま開始タグに付くので、閉じタグ側だけ合わせる
    html = html.replace(ref, f"<{tag}>\n{body}  </{tag}>")

out = root / "dist" / "unicopy.html"
out.parent.mkdir(exist_ok=True)
out.write_text(html, encoding="utf-8")
print(f"{out} ({len(html.encode('utf-8')):,} bytes)")
