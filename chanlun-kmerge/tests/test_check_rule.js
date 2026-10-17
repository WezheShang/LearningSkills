// 校验「合并前校验 + 完成检查」逻辑 —— 直接从目标文件抽取真实函数执行
// 用法: node test_check_rule.js [目标html]   默认测模板，可传构建产物
const fs = require('fs');
const path = require('path');
const ROOT = path.resolve(__dirname, '..');
const target = process.argv[2] || path.join(ROOT, 'templates', 'kmerge_template.html');
const tpl = fs.readFileSync(target, 'utf8');
const js = tpl.slice(tpl.lastIndexOf('<script>') + 8, tpl.lastIndexOf('</script>'));
console.log('目标文件:', target);

function grab(name) {
  const start = js.indexOf('function ' + name + '(');
  if (start < 0) throw new Error('模板里找不到函数 ' + name);
  let d = 0;
  for (let k = js.indexOf('{', start); k < js.length; k++) {
    if (js[k] === '{') d++;
    else if (js[k] === '}') { d--; if (!d) return js.slice(start, k + 1); }
  }
  throw new Error('函数 ' + name + ' 括号不配对');
}
const names = ['isContain', 'inheritedDir', 'autoDirFor', 'checkMergeable', 'findPending', 'mergeRange', 'mergedBar'];
const src = names.map(grab).join('\n');
console.log('已抽取:', names.join(', '));

global.S = null;
global.dec = p => p.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
global.fmtDate = d => d;
eval(src);

const setSeq = (bars, dirMode) => { global.S = { bars, dirMode: dirMode || 'auto', undo: [], doneScope: 'view', start: 0, count: bars.length }; return S; };
const B = (h, l, d) => ({ d: d || '', h, l, o: l, c: h, v: 0, parts: 1 });

let fail = 0;
const chk = (n, c, d) => { if (!c) fail++; console.log((c ? 'PASS  ' : 'FAIL  ') + n + '  |  ' + (d || '')); };

console.log('\n=== A. 包含关系校验 ===');
{
  // 不构成包含：两端同向错开
  setSeq([B(10, 2), B(12, 5)]);          // b[2,10] c[5,12] 同向上移，无一根罩住另一根
  let r = checkMergeable(0);
  chk('无包含 → 拒绝', r.ok === false && r.kind === 'contain', `kind=${r.kind} title=${r.title}`);
  chk('拒绝原因写明包含定义', /完全罩住/.test(r.detail || ''), (r.detail || '').split('\n')[0]);

  // 左包右
  setSeq([B(10, 2), B(8, 4)]);
  r = checkMergeable(0);
  chk('左包右 → 自动模式放行（方向不校验）', r.ok === true, `kind=${r.kind}`);

  // 右包左
  setSeq([B(8, 4), B(10, 2)]);
  r = checkMergeable(0);
  chk('右包左 → 自动模式放行', r.ok === true, `kind=${r.kind}`);
}

console.log('\n=== B. 方向校验（仅手动模式） ===');
{
  // 构造：b 相对 a 创新低 → 规则判「向下低低」
  const seq = [B(20, 18, 'a'), B(15, 10, 'b'), B(14, 11, 'c')];
  // a[18,20] b[10,15] 无包含且 b 创新低 → down；b[10,15] c[11,14] 有包含

  setSeq(seq, 'auto');
  let r = checkMergeable(1);
  chk('自动模式 + 方向判错 → 仍放行（不校验方向）', r.ok === true, `kind=${r.kind} 自动应为 down`);

  setSeq(seq, 'down');
  r = checkMergeable(1);
  chk('手动选对（向下 ⇇）→ 放行', r.ok === true, `kind=${r.kind}`);

  setSeq(seq, 'up');
  r = checkMergeable(1);
  chk('手动选错（应为向下却选了向上）→ 拒绝', r.ok === false && r.kind === 'dir', `kind=${r.kind}`);
  chk('拒绝文案给出正确方向', /应为向下/.test(r.title), r.title);
  chk('拒绝文案给出参照物与依据', /参照物 a/.test(r.detail) && /d_b/.test(r.detail),
    (r.detail || '').split('\n').slice(0, 2).join(' ⏎ '));
}

console.log('\n=== C. 手动模式下，方向判错 + 方向正确 都要先过包含校验 ===');
{
  setSeq([B(10, 2), B(12, 5)], 'up');     // 故意选不包含的一对
  const r = checkMergeable(0);
  chk('先卡包含（而非方向）', r.kind === 'contain', `kind=${r.kind}`);
}

console.log('\n=== D. 无合格参照物时方向判不了 → 不拦 ===');
{
  const seq = [B(25, 5, 'x'), B(20, 8, 'y'), B(15, 11, 'b'), B(14, 12, 'c')];
  // #0 #1 都罩住 b → autoDirFor 返回 aIdx=-1
  setSeq(seq, 'down');
  const r = checkMergeable(2);
  chk('无参照物 → 方向校验跳过，放行', r.ok === true, `kind=${r.kind}`);
}

console.log('\n=== E. 完成检查：全序列扫描 ===');
{
  setSeq([B(10, 2), B(8, 4), B(6, 3), B(4, 5)]);
  // [2,10] vs [4,8] → 右包左，pending
  // [4,8]  vs [3,6] → 两端反向错开，无包含
  // [3,6]  vs [5,4] → 相互包含，pending
  let p = findPending();
  chk('只扫出真正含包含的对', p.length === 2 && p[0] === 0 && p[1] === 2, `pending=[${p}] 共 ${p.length} 处`);

  // 全清序列：每对都无包含
  setSeq([B(10, 8), B(20, 15), B(30, 25)]);
  p = findPending();
  chk('无包含 → 0 处', p.length === 0, `pending=${p.length}`);

  // 单根 / 两根
  setSeq([B(10, 2)]);
  chk('单根序列无相邻对', findPending().length === 0, '');
  setSeq([B(10, 2), B(8, 4)]);
  chk('两根含包含 → 1 处', findPending().length === 1, '');
}

console.log('\n=== F. 真实数据：待处理处数必须与 isContain 扫描一致 ===');
{
  const D = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'index_data.json'), 'utf8'));
  for (const sym of ['sh000001', 'sh000688']) {
    const rows = D.indices[sym].rows;
    const bars = rows.map(r => ({ d: r[0], dEnd: r[0], o: r[1], h: r[2], l: r[3], c: r[4], v: r[5], parts: 1 }));
    setSeq(bars);
    const n = findPending().length;
    // 独立复算
    let m = 0;
    for (let i = 0; i < bars.length - 1; i++) if (isContain(bars[i], bars[i + 1])) m++;
    chk(D.indices[sym].name + ' 扫描一致', n === m, `findPending=${n} 独立复算=${m}`);

    // 在真实包含对上抽样跑校验器
    let blocked = 0, okCnt = 0;
    setSeq(bars, 'auto');
    for (let i = 1; i < bars.length - 1; i += 37) {
      if (!isContain(bars[i], bars[i + 1])) continue;
      const r = checkMergeable(i);
      if (r.ok) okCnt++; else blocked++;
    }
    chk(D.indices[sym].name + ' 自动模式对真实包含对全部放行', blocked === 0, `放行 ${okCnt} / 拦下 ${blocked}`);
  }
}

console.log('\n=== G. 手动模式在真实数据上必须能区分对错 ===');
{
  const D = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'index_data.json'), 'utf8'));
  const rows = D.indices.sh000001.rows;
  const bars = rows.map(r => ({ d: r[0], dEnd: r[0], o: r[1], h: r[2], l: r[3], c: r[4], v: r[5], parts: 1 }));
  let right = 0, wrong = 0;
  for (let i = 1; i < bars.length - 1; i++) {
    if (!isContain(bars[i], bars[i + 1])) continue;
    const truth = autoDirFor(i);
    setSeq(bars, truth.dir); if (checkMergeable(i).ok) right++;
    setSeq(bars, truth.dir === 'up' ? 'down' : 'up');
    if (!checkMergeable(i).ok) wrong++;
  }
  chk('选对方向 → 全部放行', right === 1170, `放行 ${right}`);
  chk('故意选反 → 全部拦下', wrong === 1170, `拦下 ${wrong}`);
}

console.log('\n=== H. 完成检查范围：视窗内 vs 全序列 ===');
{
  // 造一条长序列：把几处改造成包含关系
  const bars = [];
  for (let i = 0; i < 20; i++) bars.push(B(100 + i * 10, 95 + i * 10, 'a' + i));   // 逐根抬升，无包含
  for (let i = 20; i < 40; i++) bars.push(B(300 + i * 10, 295 + i * 10, 'b' + i));
  bars[3] = B(130, 95); bars[4] = B(128, 100);   // 造包含
  bars[7] = B(160, 125); bars[8] = B(158, 130);  // 造包含
  bars[23] = B(330, 295); bars[24] = B(328, 300); // 后半段造包含
  setSeq(bars);

  const all = findPending();
  const front = findPending(0, 20);
  const back = findPending(20, 40);
  console.log(`        (实际扫出 全序列=[${all}] 前20=[${front}] 后20=[${back}])`);
  chk('全序列 = 前后两段之和（无遗漏无重复）', front.length + back.length === all.length,
    `${front.length}+${back.length}=${all.length}`);
  chk('前半段与后半段互不重叠', !front.some(i => back.includes(i)), `[${front}] ∩ [${back}] = ∅`);
  chk('子区间是全序列的子集', front.concat(back).every(i => all.includes(i)), '');
  chk('两段各扫到包含对', front.length > 0 && back.length > 0, `前=${front.length} 后=${back.length}`);
  chk('区间越界自动钳制', findPending(-5, 999).length === all.length, 'findPending(-5,999)');
  chk('空区间 → 0 处', findPending(10, 10).length === 0, '');

  // 真实数据：视窗内 vs 全序列必须不同
  const D = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'index_data.json'), 'utf8'));
  const rows = D.indices.sh000001.rows;
  const real = rows.map(r => ({ d: r[0], dEnd: r[0], o: r[1], h: r[2], l: r[3], c: r[4], v: r[5], parts: 1 }));
  setSeq(real);
  const N = real.length;
  const a = findPending(), v = findPending(N - 120, N);
  chk('真实数据：全序列扫出 1170 处', a.length === 1170, `${a.length} 处`);
  chk('真实数据：最后 120 根远少于全序列', v.length < a.length, `全序列 ${a.length} 处 vs 最后120根 ${v.length} 处`);
  chk('真实数据：视窗内是全序列子集', v.every(i => a.includes(i)), '');
  chk('真实数据：会提示「视窗外还有 N 处」', a.length - v.length > 0, `视窗外 ${a.length - v.length} 处`);
}

console.log(fail ? `\n>>> ${fail} 项 FAIL` : '\n>>> ALL PASS');
process.exit(fail ? 1 : 0);
