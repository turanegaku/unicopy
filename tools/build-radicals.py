#!/usr/bin/env python3
"""IDS(漢字構成記述列) から部首フィルタの索引を作り、index.html と mjmap.json へ書き戻す。

  python3 tools/build-radicals.py ids.txt --html index.html --mjmap mjmap.json

ids.txt は CHISE IDS Database / CJKVI IDS。`U+XXXX <tab> 字 <tab> IDS [<tab> 地域別異体[GTJKV]]`。
標準ライブラリのみで読む。ソースデータはリポジトリに入れず引数で渡す（build-mjmap.py と同じ）。

もとの部首データは康熙字典の部首番号(Unihan kRSAdobe_Japan1_6)から起こしていた。
康熙部首は「その字を字書のどの部に収めるか」であって「その部品が字のどこにあるか」ではない。
一覧のUIは へん/つくり/かんむり/あし/かまえ/たれ/にょう という位置で引くので、
岩(⿱山石) が「やまへん」に入るような取り違えが のべ9,128件中 2,335件あった。
部首の同定は康熙214に任せ、位置はIDSの記述演算子から決める。
"""
import argparse, collections, json, re, sys, unicodedata as ud

# 記述演算子。⿻(重ね)は位置を決められないので使わない
OPS = '⿰⿱⿲⿳⿴⿵⿶⿷⿸⿹⿺⿻'
ARITY = {'⿲': 3, '⿳': 3}

# 位置 -> (その位置になる演算子, 何番目の引数か)
# ⿰A B なら A が へん・B が つくり、というだけの対応。囲い系は第1引数がそのまま構え。
POS = {
    'へん':     ('⿰⿲', 0),
    'つくり':   ('⿰⿲', -1),
    'かんむり': ('⿱⿳', 0),
    'あし':     ('⿱⿳', -1),
    'かまえ':   ('⿴⿵⿶⿷⿹', 0),
    'たれ':     ('⿸', 0),
    'にょう':   ('⿺', 0),
}

# チップに出す部品の下限。康熙部首は名前があるので緩め、それ以外は多いものだけ出す。
# 康熙を1字まで拾うと「かまえ/又 1字」のような組まで並んで648個になる。
MIN_ANY = 20
MIN_KANGXI = 5

# 康熙214部首の読み（並びは部首番号順）
KANGXI_READINGS = """いち ぼう てん の おつ はねぼう ふた なべぶた ひと にんにょう
いる はち けいがまえ わかんむり にすい つくえ かんにょう かたな ちから つつみがまえ
さじ はこがまえ かくしがまえ じゅう ぼく ふしづくり がんだれ む また くち
くにがまえ つち し ふゆがしら すいにょう ゆうべ おおきい おんな こ うかんむり
すん ちいさい まげあし しかばね ぐうのあし やま まがりかわ たくみ おのれ はば
ほし いとがしら まだれ えんにょう にじゅうあし しきがまえ ゆみ けいがしら さんづくり ぎょうにんべん
こころ ほこ とだれ て えだ ぼくづくり ぶん とます おの ほう
むひ にち ひらび つき き あくび とめ いちた ほこづくり なかれ
くらべる け うじ き みず ひ つめ ちち こう しょうへん
かた きば うし いぬ くろ たま うり かわら あまい いきる
もちいる た ひき やまいだれ はつがしら しろ かわ さら め ほこ
や いし しめす じゅう のぎ あな たつ たけ こめ いと
ほとぎ あみがしら ひつじ はね おい しこう すき みみ ふで にく
しん みずから いたる うす した まい ふね うしとら いろ くさ
とら むし ち ゆく ころも にし みる つの ことば たに
まめ いのしし むじな かい あか はしる あし み くるま からい
たつ しんにょう おおざと とり のごめ さと かね ながい もん こざと
しもべ ふるとり あめ あお あらず めん かわ なめしがわ にら おと
おおがい かぜ とぶ しょく くび かおり うま ほね たかい かみがしら
とう ちょう れき おに さかな とり しお しか むぎ あさ
きいろ きび くろ ふつ べん かなえ つづみ ねずみ はな ひとし
は りゅう かめ ふえ""".split()

# 部首の位置別字体 -> 親となる康熙部首。名前を引くときと「康熙部首か」を見るときに使う
VARIANTS = {
    '亻': '人', '⺅': '人', '冫': '冰', '刂': '刀', '⺌': '小', '忄': '心', '⺗': '心',
    '扌': '手', '氵': '水', '氺': '水', '灬': '火', '爫': '爪', '犭': '犬', '王': '玉',
    '罒': '网', '耂': '老', '⺮': '竹', '糹': '糸', '艹': '艸', '衤': '衣', '訁': '言',
    '釒': '金', '阝': '阜', '飠': '食', '𩙿': '食', '辶': '辵', '⻌': '辵', '攵': '攴',
    '月': '肉', '𧾷': '足', '戸': '戶', '歯': '齒', '竜': '龍', '亀': '龜',
    '麦': '麥', '黄': '黃', '斉': '齊', '青': '靑', '黒': '黑',
}
# 位置別の字体には固有の呼び名がある（康熙部首の読みをそのまま当てても通じない）。
# ここに無い部品は康熙の読みをそのまま出し、位置は title 側で「き（へん）」のように添える。
VARIANT_READINGS = {
    '亻': 'にんべん', '⺅': 'にんべん', '冫': 'にすい', '刂': 'りっとう', '忄': 'りっしんべん',
    '扌': 'てへん', '氵': 'さんずい', '灬': 'れっか', '爫': 'つめかんむり', '犭': 'けものへん',
    '罒': 'あみがしら', '耂': 'おいかんむり', '⺮': 'たけかんむり', '糹': 'いとへん',
    '艹': 'くさかんむり', '衤': 'ころもへん', '訁': 'ごんべん', '釒': 'かねへん',
    '飠': 'しょくへん', '𩙿': 'しょくへん', '辶': 'しんにょう', '⻌': 'しんにょう',
    '攵': 'ぼくづくり', '𧾷': 'あしへん', '礻': 'しめすへん', '𠆢': 'ひとやね',
}
# 阝だけは左と右で名前が変わる
BY_POSITION = {('へん', '阝'): 'こざとへん', ('つくり', '阝'): 'おおざと'}

# 部首辞典の127部首（位置つきの呼び名と、その部首に属する字）。
# IDSは「部品がどこにあるか」しか持たないので、字書の部の立て方はこちらから貰う。
# チップの前半はここに載っている＝伝統的な呼び名のある組で、残りはIDSから出ただけの構成部品。
# 岩は ⿱山石 なので位置はかんむりだが、字書の部首は山（やまへん）なので両方から引けるようにする。
BUSHU_JSON = 'tools/kangxi-bushu.json'

MARK_BEGIN, MARK_END = '/* radicals:begin */', '/* radicals:end */'
# 部首を持たない添え字。一覧では記号セクションに出していて部首では引かない
SYMBOLS = set('々〆〻仝〇ヶ')

TAG_RE = re.compile(r'\[([A-Z]+)\]$')


def read_ids(path):
    """字 -> IDS。地域別の異体があるときは日本の字形([J])を採る。"""
    out = {}
    with open(path, encoding='utf-8') as f:
        for line in f:
            if line.startswith('#'):
                continue
            col = line.rstrip('\n').split('\t')
            if len(col) < 3:
                continue
            plain = None
            for s in col[2:]:
                m = TAG_RE.search(s)
                if m is None:
                    if plain is None:
                        plain = s
                elif 'J' in m.group(1):
                    plain = s[:m.start()]
                    break
            out[col[1]] = plain if plain is not None else TAG_RE.sub('', col[2])
    return out


def split_args(s):
    """先頭の演算子の引数を、部分木ごと切り出す。壊れていたら (None, None)。"""
    if not s or s[0] not in OPS:
        return None, None
    op = s[0]
    out, i = [], 1
    for _ in range(ARITY.get(op, 2)):
        need, j = 1, i
        while need and j < len(s):
            need -= 1
            if s[j] in OPS:
                need += ARITY.get(s[j], 2)
            j += 1
        if need:
            return None, None
        out.append(s[i:j])
        i = j
    return op, out


def components(ids, ch, deep=True):
    """その字の {位置: {部品,...}}。引数が部分木なら中の葉を全部その位置の部品とする。
    愛(⿱⿱爫冖𢖻) のかんむり側は ⿱爫冖 なので 爫 と 冖 の両方に入れる（どちらも実際に上にある）。

    部品そのものが同じ向きの枠になっているときは、その内側の部品でも引けるようにする。
    同(⿵𠔼口) の枠は 𠔼(⿵冂一) で、𠔼 を部品とする字は同を入れて2字しかない。
    人が探すのは どうがまえ(冂) なので、一段だけ下を見て 冂 からも当たるようにする。"""
    op, args = split_args(ids.get(ch, ''))
    if op is None:
        return {}
    out = {}
    for pos, (ops, k) in POS.items():
        if op not in ops:
            continue
        part = args[k]
        cs = {part} if len(part) == 1 else {c for c in part if c not in OPS}
        if deep:
            for c in list(cs):
                cs |= components(ids, c, deep=False).get(pos, set())
        out[pos] = cs
    return out


def build_readings():
    """部品 -> 読み。康熙214の読みを土台に、位置別字体の固有名で上書きする。
    生成物だけで完結させておかないと、2回目の実行で読みが痩せていく。"""
    kangxi = {}
    for i, reading in enumerate(KANGXI_READINGS):
        n = ud.normalize('NFKC', chr(0x2F00 + i))
        if len(n) == 1:
            kangxi[n] = reading
    reading_of = dict(kangxi)
    for var, base in VARIANTS.items():
        if base in kangxi:
            reading_of.setdefault(var, kangxi[base])
    reading_of.update(VARIANT_READINGS)
    return reading_of, dict(BY_POSITION)


def load_bushu(path, idx):
    """{位置: {呼び名: 字}} を読み、(位置, IDSの部品) -> (呼び名, 字) に落とす。
    呼び名のかっこ内は康熙の親字（さんずい(水)）なので、その位置で実際に使われている
    字体（氵）へ寄せる。候補のうちその位置で一番字数の多いものを採る。"""
    with open(path, encoding='utf-8') as f:
        bushu = json.load(f)
    out = {}
    for pos, rads in bushu.items():
        for name, chars in rads.items():
            base = re.search(r'\(([^)]+)\)$', name).group(1)
            cand = [base] + [v for v, parent in VARIANTS.items() if parent == base]
            n = ud.normalize('NFKC', base)
            if len(n) == 1 and n != base:
                cand += [n] + [v for v, parent in VARIANTS.items() if parent == n]
            c = max(dict.fromkeys(cand), key=lambda x: len(idx[pos].get(x, ())))
            out[(pos, c)] = (name.split('(')[0], set(chars))
    return out


def build(ids, jis_chars, gaiji_chars):
    idx = collections.defaultdict(lambda: collections.defaultdict(set))
    compound = 0
    for ch in jis_chars:
        op, args = split_args(ids.get(ch, ''))
        if op is None:
            continue
        for pos, cs in components(ids, ch).items():
            k = POS[pos][1]
            if len(args[k]) > 1:
                compound += 1
            for c in cs:
                idx[pos][c].add(ch)

    kangxi = set()
    for i in range(214):
        n = ud.normalize('NFKC', chr(0x2F00 + i))
        if len(n) == 1:
            kangxi.add(n)
    kangxi |= {v for v in VARIANTS if VARIANTS[v] in kangxi}

    # 位置の並びは POS のまま（一覧の見出しの並びになる）。部品は多い順
    # 字書の部の立て方を重ねる。位置はIDSのままなので、岩は かんむり/山 と へん/山 の両方に出る
    real = load_bushu(BUSHU_JSON, idx)
    for (pos, c), (_, chars) in real.items():
        idx[pos][c] |= chars & set(jis_chars)

    # 伝統的な呼び名のある組は字数に関わらず前へ。残りはIDSから出ただけの構成部品として後ろへ
    def rank(pos, c):
        return (0 if (pos, c) in real else 1, -len(idx[pos][c]))
    chips = {pos: sorted((c for c, v in idx[pos].items()
                          if (pos, c) in real or len(v) >= MIN_ANY
                          or (c in kangxi and len(v) >= MIN_KANGXI)),
                         key=lambda c: rank(pos, c))
             for pos in POS}
    n_real = {pos: sum(1 for c in cs if (pos, c) in real) for pos, cs in chips.items()}

    # IDSが原子（部品を持たない 一 木 山 口 …）の字は、自分自身が部品になっている所へ入れる
    selfref = 0
    for ch in jis_chars:
        if split_args(ids.get(ch, ''))[0] is not None:
            continue
        for pos, cs in chips.items():
            if ch in cs:
                idx[pos][ch].add(ch)
                selfref += 1

    table = {pos: {c: ''.join(sorted(idx[pos][c])) for c in cs if idx[pos][c]}
             for pos, cs in chips.items() if cs}

    # 外字は mjmap.json 側に置く。inline に足すと index.html が155KB膨らむ
    gai = collections.defaultdict(lambda: collections.defaultdict(list))
    for ch in gaiji_chars:
        for pos, cs in components(ids, ch).items():
            for c in cs:
                if c in table.get(pos, ()):
                    gai[pos][c].append(ch)
    gaiji = {pos: {c: ''.join(gai[pos][c]) for c in chips[pos] if gai[pos].get(c)}
             for pos in POS if gai.get(pos)}

    reading_of, by_pos = build_readings()
    readings = {pos: {c: (real[(pos, c)][0] if (pos, c) in real
                          else by_pos.get((pos, c)) or reading_of[c])
                      for c in cs if (pos, c) in real or by_pos.get((pos, c)) or c in reading_of}
                for pos, cs in table.items()}
    return table, gaiji, readings, n_real, compound, selfref


def js_block(table, readings, n_real):
    def obj(d, indent):
        pad = ' ' * indent
        rows = [f'{pad}  {json.dumps(k, ensure_ascii=False)}: {json.dumps(v, ensure_ascii=False)},'
                for k, v in d.items()]
        return '{\n' + '\n'.join(rows) + '\n' + pad + '}'
    out = [MARK_BEGIN,
           '    /* 部首データ。tools/build-radicals.py が IDS(CHISE IDS Database / CJKVI IDS) から作る。',
           '       位置 -> 部品 -> その位置にその部品を持つ第1〜4水準の字。部品は IDS が返す位置別の字体',
           '       （亻 氵 扌 忄 灬 衤 …）なので、チップはこのキーをそのまま1文字出すだけでよい。',
           '       MJ外字ぶんは量が多いので mjmap.json の radicals に置いてある。 */',
           '    const KANJI_RADICALS = {']
    for pos, d in table.items():
        out.append(f'      {json.dumps(pos, ensure_ascii=False)}: {obj(d, 6)},')
    out.append('    };')
    out.append('    // 部品 -> 読み。チップは部品そのものを出し、読みは title に回す（阝のように位置で変わる）')
    out.append('    const RADICAL_READING = {')
    for pos, d in readings.items():
        out.append(f'      {json.dumps(pos, ensure_ascii=False)}: {json.dumps(d, ensure_ascii=False)},')
    out.append('    };')
    out.append('    // 位置ごとの、先頭から何個が伝統的な呼び名を持つ部首か。残りはIDSの構成部品')
    out.append('    const RADICAL_REAL = ' + json.dumps(n_real, ensure_ascii=False) + ';')
    out.append('    ' + MARK_END)
    return '\n'.join(out)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('ids', help='IDSファイル (ids.txt)')
    p.add_argument('--html', default='index.html')
    p.add_argument('--mjmap', default='mjmap.json')
    a = p.parse_args()

    ids = read_ids(a.ids)
    with open(a.mjmap, encoding='utf-8') as f:
        mm = json.load(f)
    # 対象字は mjmap.json から取る。jis は面区点を持つ10,054字で、記号を除くと第1〜4水準になる
    jis_chars = sorted({c for _, c in mm['jis'] if c not in SYMBOLS})
    gaiji_chars = sorted({m[1][0] for m in mm['mj'] if m[1]} - set(jis_chars) - SYMBOLS)
    table, gaiji, readings, n_real, compound, selfref = build(ids, jis_chars, gaiji_chars)

    html = open(a.html, encoding='utf-8').read()
    block = js_block(table, readings, n_real)
    i, j = html.index(MARK_BEGIN), html.index(MARK_END) + len(MARK_END)
    open(a.html, 'w', encoding='utf-8').write(html[:i] + block.lstrip() + html[j:])
    mm['radicals'] = gaiji
    with open(a.mjmap, 'w', encoding='utf-8') as f:
        json.dump(mm, f, ensure_ascii=False, separators=(',', ':'))

    chips = sum(len(d) for d in table.values())
    named = sum(len(d) for d in readings.values())
    nreal = sum(n_real.values())
    cov = len({c for d in table.values() for v in d.values() for c in v})
    gcov = len({c for d in gaiji.values() for v in d.values() for c in v})
    print(f'{a.html}: チップ {chips}（伝統部首 {nreal} / IDSのみ {chips - nreal}・読みあり {named}）'
          f' / 水準 {cov:,}/{len(jis_chars):,}字'
          f' / 複合引数 {compound}箇所を展開 / 原子字の自己登録 {selfref}\n'
          f'{a.mjmap}: 外字 {gcov:,}/{len(gaiji_chars):,}字', file=sys.stderr)
    for pos in POS:
        d = table.get(pos, {})
        print(f'  {pos}: {len(d)}種（伝統 {n_real.get(pos, 0)}） / のべ {sum(len(v) for v in d.values()):,}字'
              f' … {" ".join(f"{c}{len(v)}" for c, v in list(d.items())[:8])}', file=sys.stderr)


if __name__ == '__main__':
    main()
