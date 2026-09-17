#!/usr/bin/env python3
"""MJ文字情報一覧表(xlsx) と MJ縮退マップ(json) を index.html 用の 1 ファイルに統合する。

  python3 tools/build-mjmap.py mji.00602.xlsx MJShrinkMap.1.2.0.json -o mjmap.json

xlsx は字形(IVS)を、縮退マップは縮退グラフを持つ。両者は MJ文字図形名で 1:1 に対応する。
標準ライブラリのみで読む。この xlsx は strict OOXML なので名前空間が通常と違う点に注意。

縮退の根拠は SRC_BITS の並びのビットで1エッジ1つに畳む。ホップ数は落とす。
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
# 誤字俗字・正字一覧表は `付記` でさらに割る。俗字は漢和辞典に載る同字の異体（戸籍に残せる）、
# 無印は誤字（辞書に無い誤った字体。職権で正字に訂正）、別字は正字とは別の字だが混用されているもの
# （申出で訂正）。「同じ字か」の確からしさが違うので、俗字 → 誤字 → 別字 の順に並べる。
GOJI = '民一2842号通達別表 誤字俗字・正字一覧表'
SRC_BITS = [
    (None, None, None, 'JIS例示字形'),                   # 縮退マップ外。xlsx の X0213包摂区分0 が立てる
    ('JIS包摂規準・UCS統合規則', None, None, 'JIS包摂規準・UCS統合規則'),
    (None, None, None, '常用漢字表の新旧字体'),          # 縮退マップ外。下の BIT_KYUUJITAI が立てる
    ('法務省戸籍法関連通達・通知', '戸籍統一文字情報 親字・正字', None, '戸籍統一文字情報 親字・正字'),
    ('法務省戸籍法関連通達・通知', GOJI, '俗字', GOJI + ' 俗字'),
    ('法務省戸籍法関連通達・通知', '民二5202号通知別表 正字・俗字等対照表', None, '民二5202号通知別表 正字・俗字等対照表'),
    ('法務省戸籍法関連通達・通知', GOJI, '無印', GOJI + ' 誤字'),
    ('法務省戸籍法関連通達・通知', GOJI, '別字', GOJI + ' 別字'),
    ('法務省告示582号別表第四', None, None, '法務省告示582号別表第四'),
    ('辞書類等による関連字', None, None, '辞書類等による関連字'),
    ('読み・字形による類推', None, None, '読み・字形による類推'),
]
# 面区点を集めるときに見るキー（種別の違いは同じキーの中なので重複を除く）
SRC_KEYS = list(dict.fromkeys(k for k, _, _, _ in SRC_BITS if k))
# bit1 は縮退マップ外の情報。常用漢字表(平成22年内閣告示第2号)の「いわゆる康熙字典体」で、
# 旧字体を実装するMJから新字体の面区点へ向かうエッジに立てる。出典と一覧は下記に置いてある。
# 戸籍法通達の部分集合ではない（包摂や582号だけで繋がる組が7本ある）ので独立したビットが要る。
# 強い根拠から順に並べたいので、包摂の次に差し込んである。
KYUUJITAI_MD = 'docs/jyouyou-kyuujitai.md'
BIT_REP = 1 << 0
BIT_HOUSETSU = 1 << 1
BIT_KYUUJITAI = 1 << 2

# 使う列だけ拾う
# (C:MJ文字図形名 D:対応するUCS E:実装したUCS F:実装したMoji_JohoコレクションIVS
#  N:X0213 P:X0213 包摂区分)
COLS = {'C': 'mj', 'D': 'ucs', 'E': 'impl', 'F': 'ivs', 'N': 'x0213', 'P': 'houhsetsu'}

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
        mj, index_of, own, zero = [], {}, {}, {}
        for r in read_rows(z, shared):
            name = r['mj']
            ucs = r.get('ucs', '')
            index_of[name] = len(mj)
            if r.get('x0213'):
                own[name] = r['x0213']
                # 包摂区分0 = 包摂規準を当てずにその面区点に対応している字形。
                # 1つの面区点に複数あることがあるので（10,909件／10,054面区点）、
                # 「実装したUCS」が入っているものだけに絞って正字を1つに決める（下の rep_of）。
                if r.get('houhsetsu') == '0':
                    zero.setdefault(r['x0213'], []).append((name, bool(r.get('impl'))))
            sel = ivs_selector(r.get('ivs'), ucs, name)
            ch = chr(int(ucs[2:], 16)) if ucs else ''
            mj.append([int(name[2:]), ch + (chr(int(sel, 16)) if sel else '')])

    # 面区点ごとの正字。「実装したUCS」が入っている区分0を採る。愛(1-16-06) なら
    # 実装したUCSを持つ MJ011752 だけが残り、MJ011751(E0102) は落ちる。
    # 実装したUCSを持つ区分0が1つも無い面区点が41あるので、そこは区分0が1つしか
    # 無ければそれを使う（3面区点だけ絞りきれずに複数残る）。
    rep_of = {}
    for code, rows in zero.items():
        impl = [n for n, has in rows if has] or ([rows[0][0]] if len(rows) == 1 else [])
        for n in impl:
            rep_of[n] = code

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
    jis_ch = {code: chr(int(h, 16)) for code, h in jis_ucs.items()}

    # (MJ, 縮退先) の重複を潰し、根拠はビットにまとめる
    pairs = {}
    for item in shrink['content']:
        i = index_of.get(item['MJ文字図形名'])
        if i is None:
            print(f"warn: {item['MJ文字図形名']} は xlsx に無い", file=sys.stderr)
            continue
        for si, (key, kind, fuki, _) in enumerate(SRC_BITS):
            if key is None:
                continue
            for c in item.get(key, []):
                if kind is not None and c.get('種別') != kind:
                    continue
                if fuki is not None and c.get('付記') != fuki:
                    continue
                k = (i, jis_idx[c['JIS X 0213']])
                pairs[k] = pairs.get(k, 0) | (1 << si)

    # MJ自身の面区点が候補に無いものが居ないか確かめる（居なければ別枠で持たなくてよい）
    missing = [n for n, code in own.items()
               if (index_of[n], jis_idx.get(code, -1)) not in pairs]
    if missing:
        print(f'warn: 自身の面区点が候補に無いMJが {len(missing)}件: {missing[:5]}', file=sys.stderr)

    # 正字のエッジにビットを立てる。縮退マップはこれを包摂規準のエッジとして持っている
    # （MJ自身の面区点は別枠では持っていない）が、中身は縮退ではなく
    # 「この字形がこの面区点の字である」という1:1の対応なので、区別できるようにしておく。
    for n, code in rep_of.items():
        k = (index_of[n], jis_idx.get(code, -1))
        if k in pairs:
            pairs[k] |= BIT_REP

    # 新旧字体は 邊→辺 という面区点どうしの対応なので、旧字体の正字（rep_of）から新字体への
    # エッジ1本だけに立てる（無ければ作る）。邊 に包摂される他のMJへは立てない。
    # どのMJが 辺 まで届くかは、読む側が「選んだ根拠で 邊 に届いたら 邊 の新旧字体を1段たどる」
    # として決める（app.js buildEdges）。ここで他のMJにも立てると、戸籍に載っている字形だけが
    # 親字・正字のエッジに相乗りして 辺 へ行き、載っていない字形は行かないという歪みが出る。
    rep_mj = {code: index_of[n] for n, code in rep_of.items()}
    n_marked = 0
    for old, new in kyuujitai:
        oi, ni = jis_idx.get(old), jis_idx.get(new)
        if oi is None or ni is None or old not in rep_mj:
            print(f'warn: 新旧字体 {old}→{new} の正字が引けない', file=sys.stderr)
            continue
        pairs[(rep_mj[old], ni)] = pairs.get((rep_mj[old], ni), 0) | BIT_KYUUJITAI
        n_marked += 1
    print(f'新旧字体ビット: {n_marked:,} エッジ ({len(kyuujitai):,} 組から)', file=sys.stderr)

    # 縮退先は MJ にぶら下げる（別配列にすると添字を2つ持つぶん嵩む）
    for m in mj:
        m.append([])
    for (i, j), b in sorted(pairs.items()):
        mj[i][2].append([j, b])
    # xlsx は末尾に訂正分の19行（font=実装なし）を追補してあり、そこだけ番号が戻る。
    # 縮退先が持つ添字は jis 側だけなので、ここで並べ替えても参照は壊れない。
    mj.sort(key=lambda m: m[0])

    return {
        'meta': {
            'mji': xlsx_path.split('/')[-1],
            'shrink': shrink['meta'].get('owl:versionInfo', ''),
            'built': date.today().isoformat(),
            # 縮退先のビットの意味。読む側がこれだけ見れば根拠を組み立てられる
            'bits': [name for _, _, _, name in SRC_BITS],
        },
        'jis': [[code, jis_ch[code]] for code in jis],
        'mj': mj,
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

    cand = [e for m in data['mj'] for e in m[2]]
    with_cand = sum(1 for m in data['mj'] if m[2])
    LAW = 0b111111000  # 戸籍法通達の5区分 と 告示582号
    t = Counter(0 if e[1] & (BIT_REP | BIT_HOUSETSU) else (1 if e[1] & LAW else 2) for e in cand)
    print(f"{a.out}: MJ {len(data['mj']):,} / 縮退エッジ {len(cand):,} / "
          f"面区点 {len(data['jis']):,} / 縮退先なしMJ {len(data['mj']) - with_cand:,} / "
          f"IVSあり {sum(1 for m in data['mj'] if len(m[1]) > 1):,}\n"
          f"  線種: 実線(包摂・統合) {t[0]:,} / 破線(法令・告示) {t[1]:,} / 点線(辞書・類推のみ) {t[2]:,}")
    for i, (_, _, _, name) in enumerate(SRC_BITS):
        print(f"  bit{i} {name}: {sum(1 for e in cand if e[1] >> i & 1):,}")


if __name__ == '__main__':
    main()
