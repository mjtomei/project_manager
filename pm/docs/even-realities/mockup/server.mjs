// Static server for the mockup plus a "director" queue of SIMULATED events.
//   node server.mjs [port]
// GET  /director?since=N  -> {events, seq}   (polled by the page)
// POST /director          <- JSON event      (capture script / curl)
// Binds to 127.0.0.1 only. No PM, tmux or agent access.
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.dirname(fileURLToPath(import.meta.url));
const port = Number(process.argv[2] || process.env.PORT || 5180);
const types = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.mjs': 'text/javascript', '.json': 'application/json', '.css': 'text/css', '.png': 'image/png' };
const events = [];

http.createServer((req, res) => {
  const url = new URL(req.url, 'http://x');
  if (url.pathname === '/director') {
    if (req.method === 'POST') {
      let body = '';
      req.on('data', c => { body += c; });
      req.on('end', () => {
        try { events.push(JSON.parse(body)); res.writeHead(200, { 'Content-Type': 'application/json' }); res.end(JSON.stringify({ seq: events.length })); }
        catch (e) { res.writeHead(400); res.end(String(e)); }
      });
      return;
    }
    const since = Number(url.searchParams.get('since') || 0);
    res.writeHead(200, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' });
    res.end(JSON.stringify({ events: events.slice(since), seq: events.length }));
    return;
  }
  let p;
  try { p = decodeURIComponent(url.pathname); } catch { res.writeHead(400); res.end('bad path'); return; }
  if (p.endsWith('/')) p += 'index.html';
  const file = path.join(root, p);
  if (!file.startsWith(root + path.sep) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.writeHead(404); res.end('not found'); return; }
  res.writeHead(200, { 'Content-Type': types[path.extname(file)] || 'application/octet-stream', 'Cache-Control': 'no-store' });
  fs.createReadStream(file).pipe(res);
}).listen(port, '127.0.0.1', () => console.log(`mockup on http://127.0.0.1:${port}/`));
