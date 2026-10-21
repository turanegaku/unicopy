#!/usr/bin/env python3
"""IPAmj明朝がセレクタ無しで古い形（住基）を描く字の表を jis-ivs.js に書く。

  python3 tools/build_jis_ivs.py mji.00602.xlsx -o jis-ivs.js

IPAmj明朝は MJ文字情報一覧表の「実装したUCS」を、住基ネット統一文字コードが UCS と一致する字形に割り当てる。
その優先順位が JIS X 0213 の例示字形より上なので、飴 蛸 騙 など第1水準の38字では、
セレクタ無しの符号が IPAmj明朝では古い形、ふつうの書体（Noto・游・ヒラギノ）では新しい形（例示字形）になる。
char-annot・活字帳の文字認識と同じく「セレクタ無し ＝ 例示字形」とし、古い形はセレクタ付きで書き分ける。

見分けの条件は、同じ面区点・同じUCSに
  古い形: X0213 包摂区分2 で、実装したUCS を持つ字形
  新しい形: X0213 包摂区分0 で、実装したUCS を持たない字形（ちょうど1つ）
がそろうこと。区分0 が複数ある 翫 甑 冤 は例示字形を1つに決められないので外す（build-mjmap.py の rep_of と同じ3字）。

IPAmj明朝 が無い PC では Noto で描かれ、セレクタ付きでも新旧が同じ形になる。字形の画像は配らないので、そこは妥協する。
"""
import argparse, importlib.util, json, pathlib, sys, zipfile

here = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('build_mjmap', here / 'build-mjmap.py')
build_mjmap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_mjmap)


def pairs(xlsx_path):
    """面区点の順に (面区点, 基底字, 新しい形のMJ, 新しい形の選択子, 古い形のMJ, 古い形の選択子)。第1・第2水準だけ"""
    with zipfile.ZipFile(xlsx_path) as z:
        shared = build_mjmap.read_shared_strings(z)
        by = {}
        for r in build_mjmap.read_rows(z, shared):
            if r.get('x0213', '').startswith('1-') and r.get('ucs'):
                by.setdefault((r['x0213'], r['ucs']), []).append(r)
    out = []
    for (code, ucs), rows in sorted(by.items()):
        old = [r for r in rows if r.get('houhsetsu') == '2' and r.get('impl') == ucs]
        new = [r for r in rows if r.get('houhsetsu') == '0' and not r.get('impl')]
        if len(old) != 1 or len(new) != 1:
            continue
        sel = lambda r: build_mjmap.ivs_selector(r.get('ivs'), ucs, r['mj'])
        out.append((code, chr(int(ucs[2:], 16)), new[0]['mj'], sel(new[0]), old[0]['mj'], sel(old[0])))
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('xlsx', help='MJ文字情報一覧表 (mji.*.xlsx)')
    p.add_argument('-o', '--out', default='jis-ivs.js')
    a = p.parse_args()

    rows = {}
    for code, base, new_mj, new_sel, old_mj, old_sel in pairs(a.xlsx):
        rows[base] = {'jis': code,
                      'new': [base + chr(int(new_sel, 16)), new_mj],
                      'old': [base + chr(int(old_sel, 16)), old_mj]}
    with open(a.out, 'w', encoding='utf-8') as f:
        f.write(f'/* tools/build_jis_ivs.py が {pathlib.Path(a.xlsx).name} から作る。手で直さない。\n'
                '   IPAmj明朝がセレクタ無しを古い形（住基）で描く字。new は JIS 例示字形、old は古い形で、\n'
                '   それぞれ [セレクタ付きの字, MJ文字図形名]。 */\n'
                f'const JIS_IVS = {json.dumps(rows, ensure_ascii=False, separators=(",", ":"))};\n')
    print(f'{a.out}: {len(rows)} 字', file=sys.stderr)


if __name__ == '__main__':
    main()
