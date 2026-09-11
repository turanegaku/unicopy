#!/usr/bin/env python3
"""MJ文字情報一覧表(xlsx) と MJ縮退マップ(json) を index.html 用の 1 ファイルに統合する。

  python3 tools/build-mjmap.py mji.00602.xlsx MJShrinkMap.1.2.0.json -o mjmap.json

xlsx は字形(IVS)を、縮退マップは縮退グラフを持つ。両者は MJ文字図形名で 1:1 に対応する。
標準ライブラリのみで読む。この xlsx は strict OOXML なので名前空間が通常と違う点に注意。
"""
import argparse, json, re, sys, zipfile
import xml.etree.ElementTree as ET
from datetime import date

# strict OOXML。通常の schemas.openxmlformats.org ではない
NS = '{http://purl.oclc.org/ooxml/spreadsheetml/main}'

# 縮退マップのキー。出力の src はこの順序に対応する
SRC_KEYS = [
    'JIS包摂規準・UCS統合規則',
    '法務省告示582号別表第四',
    '法務省戸籍法関連通達・通知',
    '辞書類等による関連字',
    '読み・字形による類推',
]

# 使う列だけ拾う (C:MJ文字図形名 D:対応するUCS F:実装したMoji_JohoコレクションIVS N:X0213)
COLS = {'C': 'mj', 'D': 'ucs', 'F': 'ivs', 'N': 'x0213'}

IVS_RE = re.compile(r'^([0-9A-F]{4,5})_([0-9A-F]{5})$')


def read_shared_strings(z):
    out = []
    for _, el in ET.iterparse(z.open('xl/sharedStrings.xml'), events=('end',)):
        if el.tag == NS + 'si':
            out.append(''.join(t.text or '' for t in el.iter(NS + 't')))
            el.clear()
    return out


def read_rows(z, shared):
    """ヘッダ行を飛ばして {'mj':..., 'ucs':...} を yield する。"""
    first = True
    for _, el in ET.iterparse(z.open('xl/worksheets/sheet1.xml'), events=('end',)):
        if el.tag != NS + 'row':
            continue
        rec = {}
        for c in el.iter(NS + 'c'):
            col = c.get('r').rstrip('0123456789')
            name = COLS.get(col)
            if not name:
                continue
            v = c.find(NS + 'v')
            if v is None or v.text is None:
                continue
            rec[name] = shared[int(v.text)] if c.get('t') == 's' else v.text
        el.clear()
        if first:
            first = False
            continue
        if rec.get('mj'):
            yield rec


def ivs_selector(raw, ucs, mj):
    """F列 'BASE_SELECTOR' から選択子だけ返す。基底は必ず対応UCSと一致する前提を検証する。"""
    if not raw:
        return ''
    head = raw.split(';')[0]  # MJ059399/MJ059400 のみ ';' 区切りの2値を持つ
    m = IVS_RE.match(head)
    if not m:
        print(f'warn: {mj} の IVS 形式が不正: {raw!r}', file=sys.stderr)
        return ''
    if ucs and 'U+' + m.group(1) != ucs:
        print(f'warn: {mj} の IVS 基底 {m.group(1)} が 対応UCS {ucs} と不一致', file=sys.stderr)
        return ''
    return m.group(2)


def build(xlsx_path, shrink_path):
    with zipfile.ZipFile(xlsx_path) as z:
        shared = read_shared_strings(z)
        mj = []
        index_of = {}
        for r in read_rows(z, shared):
            name = r['mj']
            ucs = r.get('ucs', '')
            index_of[name] = len(mj)
            mj.append([name, ucs[2:] if ucs else '',
                       ivs_selector(r.get('ivs'), ucs, name), r.get('x0213', '')])

    with open(shrink_path, encoding='utf-8') as f:
        shrink = json.load(f)

    cand = []
    for item in shrink['content']:
        name = item['MJ文字図形名']
        i = index_of.get(name)
        if i is None:
            print(f'warn: {name} は xlsx に無い', file=sys.stderr)
            continue
        for si, key in enumerate(SRC_KEYS):
            for c in item.get(key, []):
                # 種別(戸籍法) / 表+順位(告示582号) を付記として残す
                note = c.get('種別') or (c.get('表', '') + c.get('順位', '')) or ''
                if c.get('付記'):
                    note = f"{note}({c['付記']})" if note else c['付記']
                cand.append([i, c['UCS'][2:], c['JIS X 0213'], si, c.get('ホップ数') or 0, note])

    return {
        'meta': {
            'mji': xlsx_path.split('/')[-1],
            'shrink': shrink['meta'].get('owl:versionInfo', ''),
            'built': date.today().isoformat(),
        },
        'src': SRC_KEYS,
        'mj': mj,
        'cand': cand,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('xlsx', help='MJ文字情報一覧表 (mji.*.xlsx)')
    p.add_argument('shrink', help='MJ縮退マップ (MJShrinkMap.*.json)')
    p.add_argument('-o', '--out', default='mjmap.json')
    a = p.parse_args()

    data = build(a.xlsx, a.shrink)
    with open(a.out, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))

    targets = {c[2] for c in data['cand']}
    with_cand = len({c[0] for c in data['cand']})
    print(f"{a.out}: MJ {len(data['mj']):,} / 候補 {len(data['cand']):,} / "
          f"縮退先の面区点 {len(targets):,} / 候補ありMJ {with_cand:,} / "
          f"縮退先なしMJ {len(data['mj']) - with_cand:,} / "
          f"IVSあり {sum(1 for m in data['mj'] if m[2]):,}")


if __name__ == '__main__':
    main()
