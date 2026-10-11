#!/usr/bin/env node
// 部品の照合の規則を代表字で確かめる。node tools/test_parts.js（成功したら何も出さない）
// mjmap.json があれば外字ぶんも足して、全字の索引を組む時間も測る（UNICOPY_TIME=1 のとき出す）
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { PART_IDS, DICT_RADICALS, makeParts, topParts, buildPartIndex, boxZone } = require('../parts.js');

const partsOf = makeParts(c => PART_IDS[c]);
const has = (ch, pos, ...ps) => ps.forEach(p => assert(partsOf(ch)?.[pos]?.has(p), `${ch} の ${pos} に ${p} が無い`));
const lacks = (ch, pos, ...ps) => ps.forEach(p => assert(!partsOf(ch)?.[pos]?.has(p), `${ch} の ${pos} に ${p} がある`));

has('倣', 'へん', '亻');
has('倣', 'つくり', '放', '攵', '方');          // 範囲に含まれる部品は何段下でも
lacks('倣', 'へん', '放');
has('俚', 'へん', '亻'); has('俚', 'つくり', '里');
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

const mm = path.join(__dirname, '..', 'mjmap.json');
if (fs.existsSync(mm)) {
  const t0 = Date.now();
  const { ids } = JSON.parse(fs.readFileSync(mm, 'utf8'));
  const all = makeParts(c => PART_IDS[c] || ids[c]);
  const idx = buildPartIndex([...Object.keys(PART_IDS), ...Object.keys(ids)], all);
  assert(idx.つくり.get('攵').size > 100);
  if (process.env.UNICOPY_TIME) console.log(`全字の索引 ${Date.now() - t0}ms`);
}
