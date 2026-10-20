#!/usr/bin/env node
// 部品の照合の規則を代表字で確かめる。node tools/test_parts.js（成功したら何も出さない）
// mjmap.json があれば外字ぶんも足して、全字の索引を組む時間も測る（UNICOPY_TIME=1 のとき出す）
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { PART_IDS, DICT_RADICALS, makeParts, topParts, buildPartIndex, boxZone,
        nestTree, nestHoles, nestText, makeNest, CAPTURE } = require('../parts.js');

const partsOf = makeParts(c => PART_IDS[c]);
const has = (ch, pos, ...ps) => ps.forEach(p => assert(partsOf(ch)?.[pos]?.has(p), `${ch} の ${pos} に ${p} が無い`));
const lacks = (ch, pos, ...ps) => ps.forEach(p => assert(!partsOf(ch)?.[pos]?.has(p), `${ch} の ${pos} に ${p} がある`));

has('倣', 'へん', '亻');
has('倣', 'つくり', '放', '攵', '方');          // 範囲に含まれる部品は何段下でも
lacks('倣', 'へん', '放');
has('俚', 'へん', '亻'); has('俚', 'つくり', '里');
has('椅', 'へん', '木'); has('椅', 'つくり', '奇', '大', '可');
has('椅', 'かんむり', '大'); has('椅', 'あし', '可'); lacks('椅', 'かんむり', '木');  // 右上の 大 は冠でもある
has('街', 'へん', '彳', '圭'); has('街', 'つくり', '亍', '圭');  // ⿲ の真ん中は両側
has('岩', 'かんむり', '山'); lacks('岩', 'へん', '山');          // 字書の部は混ぜない
has('国', 'かまえ', '囗'); has('国', 'なかみ', '玉');
has('広', 'たれ', '广'); has('道', 'にょう', '辶'); has('道', 'なかみ', '首');
has('内', 'かまえ', '冂'); has('内', 'なかみ', '人');            // ⿻ でも冂が囲む字は構
has('中', 'なし', '口'); assert(!partsOf('中').かまえ);
assert(![...(partsOf('与')?.なし || [])].some(c => c >= '①' && c <= '⓿'), '丸数字が部品に出ている');
assert.strictEqual(partsOf('木'), null);                         // 分解の無い字は位置を持たない

// 国語辞典式の部首（康熙の番号）。果は木部(75)、中は丨部(2)
const radOf = ch => Object.keys(DICT_RADICALS).find(r => DICT_RADICALS[r].includes(ch));
assert.strictEqual(radOf('果'), '75');
assert.strictEqual(radOf('中'), '2');

// 字から条件を作るボタンは直下の部品だけ
assert.deepStrictEqual(topParts('理', c => PART_IDS[c]), [['へん', '王'], ['つくり', '里']]);

// 枠の当たり判定（176px 角）
[[60, 88, 'へん'], [120, 88, 'つくり'], [100, 20, 'かんむり'], [100, 160, 'あし'],
 [10, 10, 'たれ'], [10, 80, 'たれ'], [10, 100, 'にょう'], [30, 170, 'にょう'],
 [170, 10, 'かまえ'], [170, 170, 'かまえ'], [-8, 88, 'かまえ'], [88, 180, 'かまえ'], [88, -20, null]]
  .forEach(([x, y, z]) => assert.strictEqual(boxZone(x, y), z, `(${x},${y})`));
assert.strictEqual(boxZone(88, 88, 'かまえ'), 'なかみ');       // 囲いを入れると中身の区画が出る
assert.strictEqual(boxZone(130, 130, 'たれ'), 'なかみ');
assert.strictEqual(boxZone(130, 40, 'にょう'), 'なかみ');
assert.strictEqual(boxZone(87, 88), 'へん');                    // 中央線ちょうどは右半分（旁）

// 入れ子で組む。位置を選ぶと外を包み、あな は形の中の空いた所を経路で指して埋める。偏と冠のどちらを先に選んだかで形が変わる
const nt = (...steps) => nestText(nestTree(steps));
assert.strictEqual(nt(['かんむり', '大'], ['あな', '可', [1]], ['へん', '木']), '⿰木⿱大可');
assert.strictEqual(nt(['へん', '木'], ['かんむり', '艹']), '⿱艹⿰木□');
assert.strictEqual(nt(['かんむり', '艹'], ['へん', '木']), '⿰木⿱艹□');
assert.strictEqual(nt(['へん', '亻'], ['へん', '木']), '⿰木⿰亻□');
assert.strictEqual(nt(['かまえ', '門'], ['あな', '日', [1]]), '⿴門日');
assert.strictEqual(nt(['へん', '木'], ['かんむり', '艹'], ['あな', '口', [1, 1]]), '⿱艹⿰木口');   // 経路は埋めた時点の形の根から
assert.deepStrictEqual(nestHoles(nestTree([['へん', '木'], ['かんむり', '艹']])), [{ path: [1, 1], role: 'つくり' }]);
assert.deepStrictEqual(nestHoles(nestTree([['にょう', '辶']])), [{ path: [1], role: 'なかみ' }]);
// 途中の段の部品を穴に戻しても、後の段の位置は変わらない（⿰氵⿱𭕄田 から 𭕄 を外すと ⿰氵⿱□田）
assert.strictEqual(nt(['かんむり', null], ['あな', '田', [1]], ['へん', '氵']), '⿰氵⿱□田');
assert.strictEqual(nt(['かんむり', '大'], ['へん', '木'], ['あな', '可', [1]]), '⿰木⿱大□');   // 古い経路は何もしない

const nest = makeNest(c => PART_IDS[c], p => p === '人' ? ['人', '亻'] : [p]);
const hits = (ch, ...steps) => assert(nest.test(ch, nestTree(steps)), `${ch} が ${nt(...steps)} に当たらない`);
const miss = (ch, ...steps) => assert(!nest.test(ch, nestTree(steps)), `${ch} が ${nt(...steps)} に当たる`);
hits('椅', ['かんむり', '大'], ['へん', '木']);                    // 奇 を ⿱大可 に開いて当てる
hits('椅', ['かんむり', '大'], ['あな', '可', [1]], ['へん', '木']);
miss('椅', ['へん', '木'], ['かんむり', '大']);                     // 順が逆なら ⿱大⿰木□ で当たらない
hits('淄', ['かんむり', '巛'], ['あな', '田', [1]]);                  // 外がまだ決まっていない形は、部品のどこかにあれば当てる
hits('淄', ['かんむり', '巛'], ['あな', '田', [1]], ['へん', '氵']);
miss('淄', ['かんむり', '巛'], ['あな', '田', [1]], ['つくり', '氵']);
hits('森', ['へん', '木']); miss('林', ['かんむり', '木']);
hits('熒', ['へん', '火'], ['あな', '火', [1]], ['あし', '火']);  // 前の段の形は、外の段のその側に含まれていればよい
miss('熒', ['へん', '火'], ['あな', '火', [1]], ['かんむり', '火']);              // 森 = ⿱木林 は 林 の中に ⿰木□
hits('倣', ['へん', '人']); hits('倣', ['へん', '亻'], ['あな', '攵', [1]]);   // 部品 1 字もその側のどこかにあればよい                                          // 字体の同一視
hits('街', ['へん', '彳']); hits('街', ['つくり', '亍']);            // ⿲ はどちらの割り方でも
hits('国', ['かまえ', '囗'], ['あな', '玉', [1]]);
hits('道', ['にょう', '辶']); miss('道', ['たれ', '辶']);
assert(['奇', '大', '可', '口'].every(p => nest.capture('椅', { op: '⿰', args: ['木', CAPTURE] }).includes(p)));   // 側の中の部品すべて

const mm = path.join(__dirname, '..', 'mjmap.json');
if (fs.existsSync(mm)) {
  const t0 = Date.now();
  const { ids } = JSON.parse(fs.readFileSync(mm, 'utf8'));
  const all = makeParts(c => PART_IDS[c] || ids[c]);
  const idx = buildPartIndex([...Object.keys(PART_IDS), ...Object.keys(ids)], all);
  assert(idx.つくり.get('攵').size > 100);
  if (process.env.UNICOPY_TIME) console.log(`全字の索引 ${Date.now() - t0}ms`);
}
