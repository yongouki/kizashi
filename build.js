// build.js — inline external scripts into a single self-contained dist/index.html
// usage: node build.js
const fs = require('fs');
const path = require('path');

const ROOT = __dirname;
let html = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8');

function inline(srcAttr, file) {
  const code = fs.readFileSync(path.join(ROOT, file), 'utf8').replace(/<\/script>/gi, '<\\/script>');
  const tag = `<script src="${srcAttr}"></script>`;
  if (html.indexOf(tag) === -1) throw new Error('tag not found: ' + tag);
  const repl = '<script>\n' + code + '\n</script>';
  // function replacement avoids $&/$1 special-pattern interpretation in `repl`
  html = html.replace(tag, () => repl);
}

inline('./vendor/react.production.min.js', 'vendor/react.production.min.js');
inline('./vendor/react-dom.production.min.js', 'vendor/react-dom.production.min.js');
inline('./vendor/html-to-image.min.js', 'vendor/html-to-image.min.js');
inline('./hexdata.js', 'hexdata.js');

fs.mkdirSync(path.join(ROOT, 'dist'), { recursive: true });
fs.writeFileSync(path.join(ROOT, 'dist', 'index.html'), html);

const size = (fs.statSync(path.join(ROOT, 'dist', 'index.html')).size / 1024).toFixed(0);
const leftover = (html.match(/<script src=/g) || []).length;
console.log('wrote dist/index.html (' + size + ' KB), remaining external <script src=: ' + leftover);
