#!/usr/bin/env python3
"""IDS と Unihan から部品の枠で引くためのデータを作り、parts.js と mjmap.json へ書き戻す。

  python3 tools/build_parts.py ids.txt Unihan.zip --js parts.js --mjmap mjmap.json

水準字ぶんは parts.js の parts ブロックに、外字ぶんは mjmap.json の ids / dictRadicals に置く
（build_radicals.py と同じ分け方。外字ぶんの IDS は 850KB あり、parts.js に足すと常に読まれる）。
MJ に無い統合漢字・拡張A のうち IDS を持つ字も、外字ぶんと同じ所に置き、字の並びを mjmap.json の extra に持つ。
どの部品がどの位置に入るかは parts.js の照合関数が実行時に決める。ここは IDS をそのまま運ぶだけにして、
位置の規則を Python と JS の二か所に持たない。
ソースデータはリポジトリに入れず引数で渡す（build-mjmap.py と同じ）。標準ライブラリのみで読む。
"""
import argparse, json, re, sys, zipfile

from build_radicals import KANGXI_READINGS, OPS, SYMBOLS, read_ids

MARK_BEGIN, MARK_END = '/* parts:begin */', '/* parts:end */'


def with_components(ids, chars, skip=()):
    """chars の IDS に、その部品を組み立てる IDS を足していく。照合は部品をたどって下りるので、
    部品が水準字でなくても（𠂉 など）その IDS が要る。skip にあるものは別の場所に置いてあるので入れない。"""
    out, todo = {}, list(chars)
    while todo:
        c = todo.pop()
        if c in out or c in skip:
            continue
        s = ids.get(c)
        if not s or s == c:
            continue
        out[c] = s
        todo.extend(d for d in s if d not in OPS and d != c)
    return out


def read_dict_radicals(path):
    """字 -> 康熙部首の番号。日本の字形に基づく kRSAdobe_Japan1_6 を優先し、無い字は kRSUnicode。
    kRSAdobe_Japan1_6 は `C+CID+部首.部首画数.残り画数` を並べたもので、C が字形の代表なので先に採る。
    kRSUnicode は `部首.残り画数` で、簡体字の部首は番号の後ろに ' が付く。"""
    aj, uni = {}, {}
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if not name.endswith('.txt'):
                continue
            for line in z.read(name).decode('utf-8').splitlines():
                if not line or line.startswith('#'):
                    continue
                cp, key, val = line.split('\t', 2)
                if key == 'kRSAdobe_Japan1_6':
                    toks = val.split()
                    tok = next((t for t in toks if t.startswith('C+')), toks[0])
                    aj[chr(int(cp[2:], 16))] = int(tok.split('+')[2].split('.')[0])
                elif key == 'kRSUnicode':
                    uni[chr(int(cp[2:], 16))] = int(re.match(r'\d+', val).group())
    if not aj or not uni:
        sys.exit(f'{path}: kRSAdobe_Japan1_6 か kRSUnicode が見つからない。Unihan の版が変わったなら読み方を直す')
    return {**uni, **aj}


def by_radical(rad, chars):
    """{部首番号: 字の並び}。番号の順に並べる（部首の束の並べ替えは画面側で字数順にする）。"""
    out = {}
    for c in sorted(chars):
        if c in rad:
            out.setdefault(rad[c], []).append(c)
    return {r: ''.join(out[r]) for r in sorted(out)}


def js_block(part_ids, dict_radicals):
    rows = '\n'.join(f'      {json.dumps(k, ensure_ascii=False)}: {json.dumps(v, ensure_ascii=False)},'
                     for k, v in sorted(part_ids.items()))
    rads = '\n'.join(f'      {r}: {json.dumps(s, ensure_ascii=False)},' for r, s in dict_radicals.items())
    return '\n'.join([
        MARK_BEGIN,
        '    /* tools/build_parts.py が作る。水準字と、その部品をたどるのに要る字の IDS（字 -> 記述）。',
        '       MJ外字ぶんは量が多いので mjmap.json の ids に置いてある。 */',
        '    const PART_IDS = {', rows, '    };',
        '    // 康熙部首の番号 -> その部首に属する水準字（国語辞典式の部首。位置の検索とは別の条件）',
        '    const DICT_RADICALS = {', rads, '    };',
        '    // 康熙部首の読み（番号順。1 が いち）',
        '    const DICT_RADICAL_NAMES = ' + json.dumps(KANGXI_READINGS, ensure_ascii=False) + ';',
        '    ' + MARK_END])


def apply(ids_path, unihan_path, js_path, mm):
    ids = read_ids(ids_path)
    rad = read_dict_radicals(unihan_path)
    jis_chars = sorted({c for _, c in mm['jis'] if c not in SYMBOLS})
    gaiji_chars = sorted({m[1][0] for m in mm['mj'] if m[1]} - set(jis_chars) - SYMBOLS)
    # MJ は行政の字なので、簡体字や他の地域の字が統合漢字にも 2,700 字ほど抜けている。拡張B 以降はふつうの PC で
    # 描けないので足さない。IDS の無い字は部品で引けないので足しても見つからない
    known = set(jis_chars) | set(gaiji_chars) | SYMBOLS
    extra_chars = sorted(c for c, s in ids.items()
                         if len(c) == 1 and (0x3400 <= ord(c) <= 0x4DBF or 0x4E00 <= ord(c) <= 0x9FFF)
                         and c not in known and s != c)

    part_ids = with_components(ids, jis_chars)
    gaiji_ids = with_components(ids, gaiji_chars + extra_chars, skip=part_ids)
    dict_jis, dict_gaiji = by_radical(rad, jis_chars), by_radical(rad, gaiji_chars + extra_chars)

    js = open(js_path, encoding='utf-8').read()
    i, j = js.index(MARK_BEGIN), js.index(MARK_END) + len(MARK_END)
    open(js_path, 'w', encoding='utf-8').write(js[:i] + js_block(part_ids, dict_jis).lstrip() + js[j:])
    mm['ids'] = gaiji_ids
    mm['dictRadicals'] = dict_gaiji
    mm['extra'] = ''.join(extra_chars)

    n_rad = lambda d: sum(len(s) for s in d.values())
    print(f'{js_path}: IDS {len(part_ids):,}（うち部品のみ {len(set(part_ids) - set(jis_chars)):,}）'
          f' / 辞書の部首 {n_rad(dict_jis):,}/{len(jis_chars):,}字\n'
          f'外字: IDS {len(gaiji_ids):,} / 辞書の部首 {n_rad(dict_gaiji):,}/{len(gaiji_chars) + len(extra_chars):,}字'
          f'（うち MJ に無い統合漢字・拡張A {len(extra_chars):,}字）', file=sys.stderr)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('ids', help='IDSファイル (ids.txt)')
    p.add_argument('unihan', help='Unihan.zip')
    p.add_argument('--js', default='parts.js')
    p.add_argument('--mjmap', default='mjmap.json')
    a = p.parse_args()

    with open(a.mjmap, encoding='utf-8') as f:
        mm = json.load(f)
    apply(a.ids, a.unihan, a.js, mm)
    with open(a.mjmap, 'w', encoding='utf-8') as f:
        json.dump(mm, f, ensure_ascii=False, separators=(',', ':'))


if __name__ == '__main__':
    main()
