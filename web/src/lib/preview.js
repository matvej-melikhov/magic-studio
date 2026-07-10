/* Рендерер предпросмотра Telegram-поста.
   ДОСЛОВНЫЙ порт из editor.html (строки 1466–1769) — код выверен под
   пиксели tdesktop, НЕ переписывать на JSX и не «улучшать»: снапшот-тесты
   в preview.test.ts фиксируют вывод. Плейсхолдеры формул — символ U+E000. */
'use strict';
const esc = s => s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');

const mathStore = [];
function mathInline(tex) { mathStore.push([tex, false]); return `${mathStore.length - 1}`; }
function mathBlock(tex) { mathStore.push([tex, true]); return `${mathStore.length - 1}`; }

function inline(text) {
  let h = text.replace(/\$([^$\n]+)\$/g, (_, tex) => mathInline(tex));
  h = esc(h);
  // поддерживаемые инлайн-теги rich-формата
  h = h.replace(/&lt;(\/?)(u|s|b|i|sub|sup|cite|mark)&gt;/gi, '<$1$2>');
  h = h.replace(/&lt;(\/?)ins&gt;/gi, '<$1u>');
  h = h.replace(/&lt;(\/?)em&gt;/gi, '<$1i>');
  h = h.replace(/&lt;(\/?)strong&gt;/gi, '<$1b>');
  h = h.replace(/&lt;tg-spoiler&gt;/gi,
    '<span class="spoiler" onclick="this.classList.toggle(\'open\')">');
  h = h.replace(/&lt;\/tg-spoiler&gt;/gi, '</span>');
  h = h.replace(/&lt;a name=&quot;[^&]*&quot;&gt;&lt;\/a&gt;/gi, '');
  // спец-сущности: кастомные эмодзи и дата-время
  // кастомные эмодзи: настоящая картинка через прокси сервера,
  // при недоступности — запасной обычный эмодзи (alt)
  h = h.replace(/!\[([^\]]*)\]\(tg:\/\/emoji\?id=(\d+)[^)]*\)/g,
    '<img class="cemoji" src="api/emoji/img?id=$2" alt="$1" ' +
    'onerror="this.outerHTML=this.alt">');
  h = h.replace(/!\[([^\]]*)\]\(tg:\/\/emoji[^)]*\)/g, '$1');
  h = h.replace(/!\[[^\]]*\]\(tg:\/\/time\?unix=(\d+)[^)]*\)/g, (_, ts) => {
    const d = new Date(+ts * 1000);
    return '<span class="tgtime">' +
      d.toLocaleDateString('ru-RU', {weekday: 'long', day: 'numeric', month: 'long', year: 'numeric'}) +
      ' в ' + d.toLocaleTimeString('ru-RU') + '</span>';
  });
  h = h.replace(/!\[[^\]]*\]\([^)]*\)/g, '');
  h = h.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" onclick="return false">$1</a>');
  h = h.replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>');
  h = h.replace(/__([^_]+)__/g, '<b>$1</b>');
  h = h.replace(/(^|[^\w*])\*([^*\n]+)\*/g, '$1<i>$2</i>');
  h = h.replace(/(^|[^\w_])_([^_\n]+)_/g, '$1<i>$2</i>');
  h = h.replace(/~~([^~]+)~~/g, '<s>$1</s>');
  h = h.replace(/==([^=]+)==/g, '<mark>$1</mark>');
  h = h.replace(/\|\|([^|]+)\|\|/g,
    '<span class="spoiler" onclick="this.classList.toggle(\'open\')">$1</span>');
  h = h.replace(/`([^`]+)`/g, '<code>$1</code>');
  h = h.replace(/\[\^([\w-]+)\]/g, '<sup><a onclick="return false">$1</a></sup>');
  return h;
}
const PLAY_ICON = '<svg viewBox="0 0 24 24" width="26" height="26" fill="currentColor" style="display:block"><path d="M8 5.3v13.4c0 .8.9 1.3 1.6.9l10.5-6.7c.6-.4.6-1.4 0-1.8L9.6 4.4c-.7-.4-1.6.1-1.6.9z"/></svg>';
const PAUSE_ICON = '<svg viewBox="0 0 24 24" width="26" height="26" fill="currentColor" style="display:block"><rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/></svg>';

function mediaBlock(url, caption) {
  const cap = caption ? `<figcaption>${esc(caption)}</figcaption>` : '';
  const clean = url.split('?')[0].toLowerCase();
  const fname = decodeURIComponent(clean.split('/').pop() || 'аудио');
  let inner;
  if (/\.(mp4|mov|webm)$/.test(clean))
    inner = `<span class="vwrap"><video src="${esc(url)}" muted playsinline preload="metadata"></video>` +
            `<span class="vplay">${PLAY_ICON}</span></span>`;
  else if (/\.(mp3|m4a|wav|flac|ogg|oga|opus)$/.test(clean))
    inner = `<span class="audiow"><button class="aplay">${PLAY_ICON}</button>` +
            `<span class="ameta"><span class="aname">${esc(fname)}</span>` +
            `<span class="asub">…</span></span>` +
            `<audio src="${esc(url)}" preload="metadata"></audio></span>`;
  else
    inner = `<img src="${esc(url)}" loading="lazy">`;
  return `<figure>${inner}${cap}</figure>`;
}

function fmtDuration(sec) {
  if (!isFinite(sec)) return '';
  const m = Math.floor(sec / 60), s = Math.round(sec % 60);
  return m + ':' + String(s).padStart(2, '0');
}

/* Оживление медиа-виджетов предпросмотра (play/pause, длительность) */
function attachMedia(root) {
  root.querySelectorAll('.audiow').forEach(w => {
    const a = w.querySelector('audio'), btn = w.querySelector('.aplay'),
          sub = w.querySelector('.asub');
    a.addEventListener('loadedmetadata', () => { sub.textContent = fmtDuration(a.duration); });
    a.addEventListener('ended', () => { btn.innerHTML = PLAY_ICON; });
    btn.addEventListener('click', () => {
      if (a.paused) { a.play(); btn.innerHTML = PAUSE_ICON; }
      else { a.pause(); btn.innerHTML = PLAY_ICON; }
    });
  });
  root.querySelectorAll('img:not(.cemoji)').forEach(img => {
    if (img.complete) return;
    img.classList.add('ph');
    img.addEventListener('load', () => {
      img.classList.remove('ph');
      img.classList.add('ld');
    }, {once: true});
    img.addEventListener('error', () => img.classList.remove('ph'), {once: true});
  });
  root.querySelectorAll('.slidewrap').forEach(w => {
    const ss = w.querySelector('.slideshow');
    const dots = [...w.querySelectorAll('.sdots span')];
    ss.addEventListener('scroll', () => {
      const idx = Math.round(ss.scrollLeft / ss.clientWidth);
      dots.forEach((d, n) => d.classList.toggle('on', n === idx));
    }, {passive: true});
    dots.forEach((d, n) => d.addEventListener('click', () =>
      ss.scrollTo({left: n * ss.clientWidth, behavior: 'smooth'})));
  });
  root.querySelectorAll('.vwrap').forEach(w => {
    const v = w.querySelector('video'), p = w.querySelector('.vplay');
    p.addEventListener('click', () => {
      if (v.paused) { v.play(); p.classList.add('playing'); }
      else { v.pause(); p.classList.remove('playing'); }
    });
    v.addEventListener('ended', () => p.classList.remove('playing'));
  });
}

function buildContentHtml(src) {
  // mathStore НЕ сбрасывается здесь: функция рекурсивна (details),
  // сброс делает вызывающий код перед корневым вызовом
  const out = [], footnotes = [];
  const lines = src.split('\n');
  let i = 0, listBuf = [], listTag = '';
  const flushList = () => {
    if (listBuf.length) { out.push(`<${listTag}>` + listBuf.join('') + `</${listTag}>`); listBuf = []; }
  };
  while (i < lines.length) {
    const line = lines[i];
    let m;
    if (/^\s*$/.test(line)) { flushList(); i++; continue; }
    if ((m = line.match(/^(#{1,6})\s+(.*)/))) {
      flushList();
      const lvl = m[1].length;
      out.push(`<h${lvl}>${inline(m[2])}</h${lvl}>`); i++; continue;
    }
    if (/^---+\s*$/.test(line)) { flushList(); out.push('<hr>'); i++; continue; }
    if (line.startsWith('```')) {
      flushList();
      const lang = line.slice(3).trim();
      const buf = []; i++;
      while (i < lines.length && !lines[i].startsWith('```')) buf.push(lines[i++]);
      i++;
      if (lang === 'math') out.push('<span class="math-block">' + mathBlock(buf.join(' ')) + '</span>');
      else out.push('<pre><code>' + esc(buf.join('\n')) + '</code></pre>');
      continue;
    }
    if (line.startsWith('$$')) {
      flushList();
      let rest = line.slice(2);
      if (rest.includes('$$')) {
        out.push('<span class="math-block">' + mathBlock(rest.slice(0, rest.indexOf('$$'))) + '</span>');
        i++; continue;
      }
      const buf = [rest]; i++;
      while (i < lines.length && !lines[i].includes('$$')) buf.push(lines[i++]);
      if (i < lines.length) { buf.push(lines[i].slice(0, lines[i].indexOf('$$'))); i++; }
      out.push('<span class="math-block">' + mathBlock(buf.join(' ').trim()) + '</span>');
      continue;
    }
    if (line.startsWith('>')) {
      flushList();
      // подряд идущие >-строки склеиваются пробелом, пустая > — перенос
      const raw = [];
      while (i < lines.length && lines[i].startsWith('>'))
        raw.push(lines[i++].replace(/^>\s?/, ''));
      const parts = [];
      let cur = [];
      for (const l of raw) {
        if (!l.trim()) { if (cur.length) { parts.push(cur.join(' ')); cur = []; } }
        else cur.push(l);
      }
      if (cur.length) parts.push(cur.join(' '));
      out.push('<blockquote>' + parts.map(inline).join('<br>') + '</blockquote>');
      continue;
    }
    if ((m = line.match(/^[-*+]\s+\[([ x])\]\s+(.*)/))) {
      if (listTag !== 'ul') flushList();
      listTag = 'ul';
      listBuf.push(`<li class="task"><input type="checkbox" ${m[1]==='x'?'checked':''} disabled> ${inline(m[2])}</li>`);
      i++; continue;
    }
    if ((m = line.match(/^[-*+]\s+(.*)/))) {
      if (listTag !== 'ul') flushList();
      listTag = 'ul'; listBuf.push('<li>' + inline(m[1]) + '</li>'); i++; continue;
    }
    if ((m = line.match(/^\d+[.)]\s+(.*)/))) {
      if (listTag !== 'ol') flushList();
      listTag = 'ol'; listBuf.push('<li>' + inline(m[1]) + '</li>'); i++; continue;
    }
    if ((m = line.match(/^!\[[^\]]*\]\(([^)\s]+)(?:\s+"([^"]*)")?\)/)) &&
        !m[1].startsWith('tg://')) {
      flushList();
      out.push(mediaBlock(m[1], m[2]));
      i++; continue;
    }
    if ((m = line.match(/^\[\^([\w-]+)\]:\s+(.*)/))) {
      flushList();
      footnotes.push(`<div>${esc(m[1])}. ${inline(m[2])} <span class="back">↩</span></div>`);
      i++; continue;
    }
    if ((m = line.match(/^<tg-map\s+lat="([^"]+)"\s+long="([^"]+)"[^>]*\/?>/i))) {
      flushList();
      out.push(`<div class="mapbox"><span>📍</span>` +
               `<span class="coords">${esc(m[1])}, ${esc(m[2])}</span></div>`);
      i++; continue;
    }
    if ((m = line.match(/^<tg-(collage|slideshow)>/i))) {
      flushList();
      const kind = m[1].toLowerCase();
      const urls = [];
      i++;
      while (i < lines.length && !new RegExp('</tg-' + kind + '>', 'i').test(lines[i])) {
        const im = lines[i].match(/!\[[^\]]*\]\(([^)\s]+)/) || lines[i].match(/src="([^"]+)"/i);
        if (im) urls.push(im[1]);
        i++;
      }
      i++;
      if (kind === 'slideshow') {
        out.push('<div class="slidewrap"><div class="slideshow">' +
                 urls.map(u => `<img src="${esc(u)}" loading="lazy">`).join('') +
                 '</div><div class="sdots">' +
                 urls.map((_, n) => `<span${n ? '' : ' class="on"'}></span>`).join('') +
                 '</div></div>');
      } else {
        out.push(`<div class="collage n${Math.min(urls.length, 4)}">` +
                 urls.map(u => `<img src="${esc(u)}" loading="lazy">`).join('') + '</div>');
      }
      continue;
    }
    if (line.includes('|') && i + 1 < lines.length && /^\s*\|?[\s:|-]+\|?\s*$/.test(lines[i+1])) {
      flushList();
      const cells = r => r.split('|').map(c => c.trim()).filter((c, idx, arr) =>
        !(idx === 0 && c === '') && !(idx === arr.length - 1 && c === ''));
      const aligns = cells(lines[i + 1]).map(c =>
        /^:.*:$/.test(c) ? 'center' : /:$/.test(c) ? 'right' : 'left');
      const st = idx => aligns[idx] && aligns[idx] !== 'left'
        ? ` style="text-align:${aligns[idx]}"` : '';
      let html = '<table><tr>' + cells(line).map((c, idx) =>
        `<th${st(idx)}>${inline(c)}</th>`).join('') + '</tr>';
      i += 2;
      while (i < lines.length && lines[i].includes('|')) {
        html += '<tr>' + cells(lines[i]).map((c, idx) =>
          `<td${st(idx)}>${inline(c)}</td>`).join('') + '</tr>';
        i++;
      }
      out.push(html + '</table>');
      continue;
    }
    if ((m = line.match(/^<details([^>]*)><summary>(.*?)<\/summary>(.*)/i))) {
      flushList();
      const buf = [m[3]]; i++;
      while (i < lines.length && !/<\/details>/i.test(lines[i])) buf.push(lines[i++]);
      if (i < lines.length) { buf.push(lines[i].replace(/<\/details>.*/i, '')); i++; }
      // тело details — полноценный rich-контент, парсим рекурсивно;
      // свёрнут по умолчанию, раскрыт только с атрибутом open — как в Telegram
      const openAttr = /\bopen\b/i.test(m[1]) ? ' open' : '';
      out.push(`<details${openAttr}><summary>${inline(m[2])}</summary>` +
               `<div class="dbody">${buildContentHtml(buf.join('\n'))}</div></details>`);
      continue;
    }
    if ((m = line.match(/^<footer>(.*?)<\/footer>/i))) {
      flushList(); out.push(`<footer>${inline(m[1])}</footer>`); i++; continue;
    }
    if ((m = line.match(/^<aside>(.*?)(?:<cite>(.*?)<\/cite>)?<\/aside>/i))) {
      flushList();
      out.push(`<aside>${inline(m[1])}${m[2] ? `<cite>${inline(m[2])}</cite>` : ''}</aside>`);
      i++; continue;
    }
    flushList();
    const buf = [line];
    while (i + 1 < lines.length && lines[i+1].trim() &&
           !/^(#|>|[-*+]\s|\d+[.)]\s|```|\$\$|---|!\[|<|\||\[\^)/.test(lines[i+1]))
      buf.push(lines[++i]);
    out.push('<p>' + inline(buf.join(' ')) + '</p>');
    i++;
  }
  flushList();
  if (footnotes.length) out.push('<div class="footnotes">' + footnotes.join('') + '</div>');
  return out.join('');
}

function applyMath(root) {
  // KaTeX по плейсхолдерам
  if (mathStore.length) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const targets = [];
    while (walker.nextNode()) {
      if (walker.currentNode.nodeValue.includes('')) targets.push(walker.currentNode);
    }
    targets.forEach(node => {
      const parts = node.nodeValue.split(/(\d+)/);
      const frag = document.createDocumentFragment();
      parts.forEach((part, idx) => {
        if (idx % 2 === 0) { if (part) frag.appendChild(document.createTextNode(part)); return; }
        const [tex, display] = mathStore[+part];
        const span = document.createElement('span');
        if (window.katex) {
          try { katex.render(tex, span, {throwOnError: false, displayMode: display}); }
          catch (e) { span.textContent = tex; }
        } else {
          span.textContent = tex;
          span.style.cssText = 'font-family:Georgia,serif;font-style:italic';
        }
        frag.appendChild(span);
      });
      node.parentNode.replaceChild(frag, node);
    });
  }
  attachMedia(root);
}

export { mathStore, inline, mediaBlock, fmtDuration, attachMedia, buildContentHtml, applyMath, esc };
