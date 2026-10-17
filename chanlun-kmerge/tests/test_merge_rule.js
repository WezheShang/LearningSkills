// 缠论包含处理 —— 参照物 a 走左逻辑自检（价格口径：h>l）
function isContain(x, y) {
  return (x.h >= y.h && x.l <= y.l) || (y.h >= x.h && y.l <= x.l);
}
function inheritedDir(bars, i, depth) {
  depth = depth || 0;
  if (depth > 300 || i <= 0) return 'up';
  const b = bars[i];
  if (b.rule) return b.rule;
  for (let j = i - 1; j >= 0; j--) {
    if (!isContain(bars[j], b)) {
      if (b.h > bars[j].h) return 'up';
      if (b.l < bars[j].l) return 'down';
      return inheritedDir(bars, j, depth + 1);
    }
  }
  return 'up';
}
function autoDirFor(bars, i) {
  const b = bars[i];
  for (let j = i - 1; j >= 0; j--) {
    if (!isContain(bars[j], b)) {
      const a = bars[j];
      if (b.h > a.h) return { dir: 'up', aIdx: j };
      if (b.l < a.l) return { dir: 'down', aIdx: j };
      return { dir: inheritedDir(bars, j, 1), aIdx: j };
    }
  }
  return { dir: inheritedDir(bars, i, 1), aIdx: -1 };
}
function merged(A, B, dir) {
  const up = dir === 'up';
  const h = up ? Math.max(A.h, B.h) : Math.min(A.h, B.h);
  const l = up ? Math.max(A.l, B.l) : Math.min(A.l, B.l);
  return { h, l, o: up ? l : h, c: up ? h : l };
}

let ok = true;
const chk = (name, cond, detail) => {
  if (!cond) ok = false;
  console.log((cond ? 'PASS  ' : 'FAIL  ') + name + '  |  ' + detail);
};

console.log('=== 场景1【用户截图回归】：b 相对前一根 a 向下走，b 与 c 成包含关系 ===');
// 按截图 y 换算成价格（price = 1000 - y）：g[825,935] a[840,935] b[810,915] c[805,975]
const bars = [
  { d: 'g', h: 935, l: 825 },
  { d: 'a', h: 935, l: 840 },
  { d: 'b', h: 915, l: 810 },
  { d: 'c', h: 975, l: 805 },
];
const i = 2;
chk('b 与 c 是包含关系', isContain(bars[i], bars[i + 1]),
  `b[${bars[i].l},${bars[i].h}] c[${bars[i+1].l},${bars[i+1].h}]`);
chk('a 与 b 无包含 → a 是合格参照', !isContain(bars[1], bars[2]),
  `a[${bars[1].l},${bars[1].h}] b[${bars[2].l},${bars[2].h}]`);
const ad = autoDirFor(bars, i);
// 回归对照：旧逻辑（拿 c 与 b 比）会误判
const oldWrong = bars[i + 1].h > bars[i].h ? 'up' : 'down';
chk('旧逻辑(c vs b)会误判为向上', oldWrong === 'up', `旧逻辑=${oldWrong}  ← 这就是原来的 bug`);
chk('新逻辑(b vs a)判为向下', ad.dir === 'down', `自动=${ad.dir} 参照 aIdx=${ad.aIdx}`);
const m = merged(bars[i], bars[i + 1], ad.dir);
chk('低低 = 较低的高 + 较低的低', m.h === 915 && m.l === 805, `h=${m.h} l=${m.l}`);
chk('阴线：开=高 收=低', m.o === m.h && m.c === m.l, `o=${m.o} c=${m.c}`);

console.log('\n=== 场景2：参照物不合格时必须继续往左找 ===');
{
  // #1 与 b(#2) 构成包含 → #1 没资格当参照，必须继续往左找到 #0
  const B = [
    { d: 'x', h: 10, l: 8 },    // #0 合格参照（低）
    { d: 'y', h: 20, l: 5 },    // #1 与 b 包含 → 不合格
    { d: 'b', h: 15, l: 9 },
    { d: 'c', h: 14, l: 11 },
  ];
  chk('#1 与 #2 构成包含（#1 不合格）', isContain(B[1], B[2]),
    `#1[${B[1].l},${B[1].h}] b[${B[2].l},${B[2].h}]`);
  const r = autoDirFor(B, 2);
  chk('参照被推到 #0', r.aIdx === 0, `aIdx=${r.aIdx} dir=${r.dir}`);
  chk('#0 高 10 < #2 高 15 → b 创新高 → 向上', r.dir === 'up', `dir=${r.dir}`);
}

console.log('\n=== 场景2b：参照物一路被推到 #0 仍成立（b 创新低 → 向下）===');
{
  const B = [
    { d: 'x', h: 30, l: 20 },   // #0
    { d: 'y', h: 20, l: 5 },    // #1 罩住 b → 不合格
    { d: 'b', h: 15, l: 8 },
    { d: 'c', h: 14, l: 9 },
  ];
  chk('#1 与 #2 构成包含（#1 不合格）', isContain(B[1], B[2]), '');
  const r = autoDirFor(B, 2);
  chk('参照被推到 #0', r.aIdx === 0, `aIdx=${r.aIdx} dir=${r.dir}`);
  chk('b 低 8 < #0 低 20 → 创新低 → 向下', r.dir === 'down', `dir=${r.dir}`);
}

console.log('\n=== 场景3：b 创新高 → 向上（高高）===');
{
  const B = [{ h: 10, l: 2 }, { h: 12, l: 5 }, { h: 11, l: 6 }];
  const r = autoDirFor(B, 1);
  const m = merged(B[1], B[2], r.dir);
  chk('b 高于 a → 向上', r.dir === 'up', `dir=${r.dir}`);
  chk('高高 = 较高的高 + 较高的低', m.h === 12 && m.l === 6, `h=${m.h} l=${m.l}`);
}

console.log('\n=== 场景4：严格不等号 —— 等高必然构成包含，会被跳过 ===');
{
  const B = [{ h: 10, l: 2 }, { h: 10, l: 5 }, { h: 9, l: 4 }];
  chk('等高 → 构成包含，参照不合格', isContain(B[0], B[1]), 'a[2,10] b[5,10]');
  const r = autoDirFor(B, 1);
  chk('跳过并落到延续/继续走左', r.aIdx === -1 || r.aIdx === 0, `dir=${r.dir} aIdx=${r.aIdx}`);
}

console.log('\n=== 场景5：等高/等低时延续更早方向（合并产物自带 rule）===');
{
  const B = [
    { h: 20, l: 10, rule: 'down', parts: 2 },
    { h: 20, l: 14, rule: 'down', parts: 2 },
    { h: 18, l: 15 },
  ];
  chk('#0 与 #1 等高 → 构成包含', isContain(B[0], B[1]), 'h 都是 20');
  const r = autoDirFor(B, 1);
  chk('延续 #0 的 down', r.dir === 'down', `dir=${r.dir}`);
}

console.log('\n=== 场景6：实体永远覆盖整个区间（光头光脚）===');
for (const dir of ['up', 'down']) {
  const A = { h: 10, l: 2 }, B = { h: 8, l: 4 };
  const r = merged(A, B, dir);
  chk(dir + ' 光头光脚', Math.min(r.o, r.c) <= r.l && Math.max(r.o, r.c) >= r.h,
    `o=${r.o} c=${r.c} 区间[${r.l},${r.h}]`);
}

console.log('\n=== 场景7：序列开头的两根（#0 本身就是合格参照）===');
{
  const B = [{ h: 5, l: 1 }, { h: 8, l: 3 }];   // 缠论原文例子：第1根高5，第2根高8
  chk('#0 与 #1 无包含 → #0 即参照', !isContain(B[0], B[1]), '#0[1,5] #1[3,8]');
  const r = autoDirFor(B, 1);
  chk('参照 = #0，高 8 > 5 → 向上', r.dir === 'up' && r.aIdx === 0, `dir=${r.dir} aIdx=${r.aIdx}`);
}

console.log('\n=== 场景8：左边全部与 b 包含 → 真·无参照，走延续 ===');
{
  const B = [{ h: 25, l: 5 }, { h: 20, l: 8 }, { h: 15, l: 11 }];
  chk('两根参照物都罩住 b', isContain(B[0], B[2]) && isContain(B[1], B[2]),
    `b[${B[2].l},${B[2].h}] #0[${B[0].l},${B[0].h}] #1[${B[1].l},${B[1].h}]`);
  const r = autoDirFor(B, 2);
  chk('无参照 → aIdx=-1 且走延续（默认向上）', r.aIdx === -1 && r.dir === 'up',
    `dir=${r.dir} aIdx=${r.aIdx}`);
}

console.log(ok ? '\n>>> ALL PASS' : '\n>>> MISMATCH');
process.exit(ok ? 0 : 1);
