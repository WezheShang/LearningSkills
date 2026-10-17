// 校验：JS 里 $('xxx') 引用的每个控件 id 都真实存在于 HTML，避免 null.children 静默炸掉整页
const fs = require('fs');
const t = fs.readFileSync(process.argv[2], 'utf8');
const cut = t.indexOf('<script id="DATA"');
const html = t.slice(0, cut);
const js = t.slice(t.lastIndexOf('<script>'));
const ids = new Set([...html.matchAll(/id="([^"]+)"/g)].map(m => m[1]));
const refs = [...new Set([...js.matchAll(/\$\('([^']+)'\)/g)].map(m => m[1]))];
// 运行时用 document.createElement 动态挂载、不在静态 HTML 里的控件
const DYNAMIC = new Set(['toast', 'note']);
const missing = refs.filter(r => !ids.has(r) && !DYNAMIC.has(r));
console.log('HTML ids      :', [...ids].join(', '));
console.log('JS 引用控件   :', refs.join(', '));
console.log('动态创建豁免  :', [...DYNAMIC].join(', ') || '(无)');
console.log(missing.length
  ? '>>> MISSING (会抛 null.children): ' + missing.join(', ')
  : '>>> ALL CONTROL REFS RESOLVE (' + refs.length + ', 豁免 ' + DYNAMIC.size + ')');
process.exit(missing.length ? 1 : 0);
