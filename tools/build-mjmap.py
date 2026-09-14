#!/usr/bin/env python3
"""MJ文字情報一覧表(xlsx) と MJ縮退マップ(json) を index.html 用の 1 ファイルに統合する。

  python3 tools/build-mjmap.py mji.00602.xlsx MJShrinkMap.1.2.0.json -o mjmap.json

xlsx は字形(IVS)を、縮退マップは縮退グラフを持つ。両者は MJ文字図形名で 1:1 に対応する。
標準ライブラリのみで読む。この xlsx は strict OOXML なので名前空間が通常と違う点に注意。

縮退の根拠は SRC_KEYS の並びのビットで1エッジ1つに畳む。ホップ数は落とす。
根拠が違うだけの同じ縮退先が最大8本並ぶのを潰しつつ、
「規格の包摂か、法令の読み替えか、辞書の参考か」は残す必要があるため。
MJ自身の面区点は別枠では持たない ―― 必ず包摂規準のエッジとして候補に含まれる（検証済み）。
"""
import argparse, json, re, sys, zipfile
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import date

# strict OOXML。通常の schemas.openxmlformats.org ではない
NS = '{http://purl.oclc.org/ooxml/spreadsheetml/main}'

# 縮退マップが持つ根拠を強い順にビットへ割り当てる。1エッジに複数立つ
# （同じ縮退先が根拠違いで最大8本並ぶのを潰すため）。
# (縮退マップのキー, 種別で絞るならその値, 表示名)
#
# 「法務省戸籍法関連通達・通知」は3つの出典の寄せ集めなので種別で割る。
# 親字・正字 16,305本 に対し、誤字俗字・正字一覧表が 1,001本、正字・俗字等対照表が 138本。
# ひとまとめだと「正字の関係だけ採る」ができず、誤字までいっしょに付いてくる。
SRC_BITS = [
    ('JIS包摂規準・UCS統合規則', None, 'JIS包摂規準・UCS統合規則'),
    (None, None, '常用漢字表の新旧字体'),          # 縮退マップ外。下の BIT_KYUUJITAI が立てる
    ('法務省告示582号別表第四', None, '法務省告示582号別表第四'),
    ('法務省戸籍法関連通達・通知', '戸籍統一文字情報 親字・正字', '戸籍統一文字情報 親字・正字'),
    ('法務省戸籍法関連通達・通知', '民二5202号通知別表 正字・俗字等対照表', '民二5202号通知別表 正字・俗字等対照表'),
    ('法務省戸籍法関連通達・通知', '民一2842号通達別表 誤字俗字・正字一覧表', '民一2842号通達別表 誤字俗字・正字一覧表'),
    ('辞書類等による関連字', None, '辞書類等による関連字'),
    ('読み・字形による類推', None, '読み・字形による類推'),
]
# 面区点を集めるときに見るキー（種別の違いは同じキーの中なので重複を除く）
SRC_KEYS = list(dict.fromkeys(k for k, _, _ in SRC_BITS if k))
# bit1 は縮退マップ外の情報。常用漢字表(平成22年内閣告示第2号)の「いわゆる康熙字典体」で、
# 旧字体を実装するMJから新字体の面区点へ向かうエッジに立てる。出典と一覧は下記に置いてある。
# 戸籍法通達の部分集合ではない（包摂や582号だけで繋がる組が7本ある）ので独立したビットが要る。
# 強い根拠から順に並べたいので、包摂の次に差し込んである。
KYUUJITAI_MD = 'docs/jyouyou-kyuujitai.md'
BIT_KYUUJITAI = 1 << 1

# 使う列だけ拾う
# (C:MJ文字図形名 D:対応するUCS F:実装したMoji_JohoコレクションIVS N:X0213 P:X0213 包摂区分)
COLS = {'C': 'mj', 'D': 'ucs', 'F': 'ivs', 'N': 'x0213', 'P': 'houhsetsu'}

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
            name = COLS.get(c.get('r').rstrip('0123456789'))
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


def read_kyuujitai(path):
    """対照表ブロック（```tsv ... ```）から (旧面区点, 新面区点) を読む。"""
    try:
        with open(path, encoding='utf-8') as f:
            body = f.read()
    except FileNotFoundError:
        print(f'warn: {path} が無いので新旧字体ビットは立てない', file=sys.stderr)
        return []
    m = re.search(r'```tsv\n(.*?)```', body, re.S)
    if not m:
        print(f'warn: {path} に tsv ブロックが無い', file=sys.stderr)
        return []
    out = []
    for line in m.group(1).splitlines():
        f4 = line.split('\t')
        if len(f4) == 4 and f4[2] != '—' and f4[3] != '—':
            out.append((f4[2], f4[3]))
    return out


def build(xlsx_path, shrink_path, kyuujitai):
    with zipfile.ZipFile(xlsx_path) as z:
        shared = read_shared_strings(z)
        mj, index_of, own, rep_of = [], {}, {}, {}
        for r in read_rows(z, shared):
            name = r['mj']
            ucs = r.get('ucs', '')
            index_of[name] = len(mj)
            if r.get('x0213'):
                own[name] = r['x0213']
                # 包摂区分0 = その面区点のJIS例示字形。同じ面区点に縮退するMJを並べるとき、
                # 字形がその面区点そのものであるMJを先頭に出すために持っておく。
                if r.get('houhsetsu') == '0':
                    rep_of[name] = r['x0213']
            mj.append([int(name[2:]), ucs[2:] if ucs else '',
                       ivs_selector(r.get('ivs'), ucs, name)])

    with open(shrink_path, encoding='utf-8') as f:
        shrink = json.load(f)

    # 面区点 -> UCS の表。候補は面区点の添字で指すのでここが辞書がわりになる
    jis_ucs = {}
    for item in shrink['content']:
        for key in SRC_KEYS:
            for c in item.get(key, []):
                jis_ucs.setdefault(c['JIS X 0213'], c['UCS'][2:])
    jis = sorted(jis_ucs)
    jis_idx = {code: i for i, code in enumerate(jis)}

    # (MJ, 縮退先) の重複を潰し、根拠はビットにまとめる
    pairs = {}
    for item in shrink['content']:
        i = index_of.get(item['MJ文字図形名'])
        if i is None:
            print(f"warn: {item['MJ文字図形名']} は xlsx に無い", file=sys.stderr)
            continue
        for si, (key, kind, _) in enumerate(SRC_BITS):
            if key is None:
                continue
            for c in item.get(key, []):
                if kind is not None and c.get('種別') != kind:
                    continue
                k = (i, jis_idx[c['JIS X 0213']])
                pairs[k] = pairs.get(k, 0) | (1 << si)

    # MJ自身の面区点が候補に無いものが居ないか確かめる（居なければ別枠で持たなくてよい）
    missing = [n for n, code in own.items()
               if (index_of[n], jis_idx.get(code, -1)) not in pairs]
    if missing:
        print(f'warn: 自身の面区点が候補に無いMJが {len(missing)}件: {missing[:5]}', file=sys.stderr)

    # 旧字体の面区点に包摂されるMJが、新字体の面区点にも縮退している組にビットを立てる
    by_mj = {}
    for (i, j), b in pairs.items():
        by_mj.setdefault(i, []).append((j, b))
    n_marked = 0
    for old, new in kyuujitai:
        oi, ni = jis_idx.get(old), jis_idx.get(new)
        if oi is None or ni is None:
            continue
        for i, es in by_mj.items():
            if any(j == oi and b & 1 for j, b in es) and any(j == ni for j, b in es):
                pairs[(i, ni)] |= BIT_KYUUJITAI
                n_marked += 1
    print(f'新旧字体ビット: {n_marked:,} エッジ ({len(kyuujitai):,} 組から)', file=sys.stderr)

    return {
        'meta': {
            'mji': xlsx_path.split('/')[-1],
            'shrink': shrink['meta'].get('owl:versionInfo', ''),
            'built': date.today().isoformat(),
            # cand のビットの意味。読む側がこれだけ見れば根拠を組み立てられる
            'bits': [name for _, _, name in SRC_BITS],
        },
        'jis': [[code, jis_ucs[code]] for code in jis],
        'mj': mj,
        # [MJのindex, 面区点のindex]。そのMJがその面区点のJIS例示字形であることを示す
        'rep': sorted([index_of[n], jis_idx[c]] for n, c in rep_of.items() if c in jis_idx),
        'cand': [[i, j, b] for (i, j), b in sorted(pairs.items())],
    }


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('xlsx', help='MJ文字情報一覧表 (mji.*.xlsx)')
    p.add_argument('shrink', help='MJ縮退マップ (MJShrinkMap.*.json)')
    p.add_argument('-o', '--out', default='mjmap.json')
    a = p.parse_args()

    data = build(a.xlsx, a.shrink, read_kyuujitai(KYUUJITAI_MD))
    with open(a.out, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))

    with_cand = len({c[0] for c in data['cand']})
    LAW = 0b111100  # 告示582号 と 戸籍法通達の3種別
    t = Counter(0 if c[2] & 1 else (1 if c[2] & LAW else 2) for c in data['cand'])
    print(f"{a.out}: MJ {len(data['mj']):,} / 縮退エッジ {len(data['cand']):,} / "
          f"面区点 {len(data['jis']):,} / 縮退先なしMJ {len(data['mj']) - with_cand:,} / "
          f"IVSあり {sum(1 for m in data['mj'] if m[2]):,}\n"
          f"  線種: 実線(包摂・統合) {t[0]:,} / 破線(法令・告示) {t[1]:,} / 点線(辞書・類推のみ) {t[2]:,}\n"
          f"  JIS例示字形(X0213 包摂区分0) {len(data['rep']):,}")
    for i, (_, _, name) in enumerate(SRC_BITS):
        print(f"  bit{i} {name}: {sum(1 for c in data['cand'] if c[2] >> i & 1):,}")


if __name__ == '__main__':
    main()
