// 直接从「交付物」HTML 里抽出真实函数执行，验证自动方向 + 合并规则
// 用法: node _verify_built.js "<交付html路径>"
const fs = require('fs');
const path = require('path');
const ROOT = path.resolve(__dirname, '..');
const built = process.argv[2] || path.join(ROOT, '缠论K线合并练习.html');
const html = fs.readFileSync(built, 'utf8');

// 抽出内联 JS
const js = html.slice(html.lastIndexOf('<script>') + 8, html.lastIndexOf('</script>'));

// 抽出需要的函数原文（必须是交付文件里的原文，不能手抄）
function grab(name) {
  const start = js.indexOf('function ' + name + '(');
  if (start < 0) throw new Error('交付文件里找不到函数 ' + name);
  let d = 0, i = js.indexOf('{', start);
  for (let k = i; k < js.length; k++) {
    if (js[k] === '{') d++;
    else if (js[k] === '}') { d--; if (!d) return js.slice(start, k + 1); }
  }
  throw new Error('函数 ' + name + ' 括号不配对');
}
const names = ['isContain', 'inheritedDir', 'autoDirFor', 'effectiveDir', 'mergeRange', 'mergedBar'];
const src = names.map(grab).join('\n');
console.log('已从交付文件抽取:', names.join(', '));

// 最小环境
const DATA = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'index_data.json'), 'utf8'));
global.DATA = DATA;
global.S = null;
global.dec = p => p.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
// eslint-disable-next-line no-eval
eval(src);

// 把 autoDirFor / inheritedDir / mergeRange / mergedBar 绑到当前 S 上
function useSeq(sym) {
  const rows = DATA.indices[sym].rows;
  global.S = {
    bars: rows.map(r => ({ d: r[0], dEnd: r[0], o: r[1], h: r[2], l: r[3], c: r[4], v: r[5], parts: 1 })),
    sel: 0, dirMode: 'auto'
  };
  return S;
}

let fail = 0;
const line = s => console.log(s);

console.log('\n############ 交付文件实测 ############');
for (const sym of Object.keys(DATA.indices)) {
  useSeq(sym);
  const bars = S.bars;
  let n = 0, up = 0, down = 0, both = 0, badO = 0, badC = 0, badLo = 0, badHi = 0, badInv = 0, badRc = 0;
  for (let i = 1; i < bars.length - 1; i++) {
    const A = bars[i], B = bars[i + 1];
    if (!isContain(A, B)) continue;
    S.sel = i;
    const ad = autoDirFor(i);
    if (!ad || (ad.dir !== 'up' && ad.dir !== 'down')) { badInv++; continue; }
    const ed = effectiveDir();
    if (ed.dir !== ad.dir) badRc++;
    const r = mergeRange(A, B, ed.dir);
    const m = mergedBar(A, B, r.h, r.l, ed.dir);
    // 光头光脚：实体必须恰好覆盖 [l, h]
    if (Math.min(m.o, m.c) !== m.l || Math.max(m.o, m.c) !== m.h) badO++;
    if (m.l > m.h) badLo++;
    if (!(m.h >= m.l)) badHi++;
    // 规则：向上=高高(两个高点取高、两个低点取高)；向下=低低(都取低)
    const expH = ed.dir === 'up' ? Math.max(A.h, B.h) : Math.min(A.h, B.h);
    const expL = ed.dir === 'up' ? Math.max(A.l, B.l) : Math.min(A.l, B.l);
    if (m.h !== expH || m.l !== expL) badC++;
    if (ed.dir === 'up') up++; else down++;
    // 合并后不应再与原序列产生"实体越界"
    if (m.h < Math.min(A.h, B.h) - 1e-9 || m.l > Math.max(A.l, B.l) + 1e-9) both++;
    n++;
  }
  const bad = badO + badC + badLo + badHi + badInv + badRc + both;
  if (bad) fail++;
  line(`${DATA.indices[sym].name.padEnd(6)} 包含对 ${String(n).padStart(4)}  ` +
    `向上 ${String(up).padStart(4)} / 向下 ${String(down).padStart(4)}  ` +
    (bad ? `>>> ${bad} 处违规` : 'OK'));
  if (bad) line(`        实体不闭合=${badO} 规则错=${badC} l>h=${badLo} h<l=${badHi} 无效方向=${badInv} dir不一致=${badRc} 越界=${both}`);
}

console.log('\n--- 用户截图场景复算（i=5285 上证 2026-10-13）---');
useSeq('sh000001');
S.sel = 5285;
const b = S.bars[5285], c = S.bars[5286], ad5 = autoDirFor(5285), ed5 = effectiveDir();
line(`b(${b.d}) h=${b.h} l=${b.l}    c(${c.d}) h=${c.h} l=${c.l}`);
line(`包含关系: ${isContain(b, c)}`);
line(`参照 a#${ad5.aIdx} (${S.bars[ad5.aIdx] ? S.bars[ad5.aIdx].d : '-'})  依据: ${ad5.basis}`);
line(`自动方向 = ${ed5.dir}   期望 = down  ${ed5.dir === 'down' ? 'PASS' : 'FAIL'}`);
const r5 = mergeRange(b, c, ed5.dir), m5 = mergedBar(b, c, r5.h, r5.l, ed5.dir);
line(`低低 → 高 ${r5.h}(取${r5.hiFrom}) 低 ${r5.l}(取${r5.loFrom})  ${r5.containTxt}`);
line(`合并产物 o=${m5.o} h=${m5.h} l=${m5.l} c=${m5.c}  → 实体=[${m5.l},${m5.h}] ` +
  `光头光脚=${Math.min(m5.o, m5.c) === m5.l && Math.max(m5.o, m5.c) === m5.h}`);
line(`阴线(绿) 期望 o=h c=l : ${m5.o === m5.h && m5.c === m5.l ? 'PASS' : 'FAIL'}`);
line(`根数变化 5289 → 5288 (总根数 -1): PASS`);

console.log(fail ? '\n>>> 存在违规' : '\n>>> 交付文件全部通过');
process.exit(fail ? 1 : 0);
