// In-page search: type a line or stop name, jump to it on this page.
(function () {
  var input = document.getElementById('find');
  var box = document.getElementById('find-results');
  if (!input || !box) return;

  function norm(s) {
    return (s || '')
      .toLowerCase()
      .replace(/[״"׳'`]/g, '')
      .replace(/ך/g, 'כ').replace(/ם/g, 'מ').replace(/ן/g, 'נ').replace(/ף/g, 'פ').replace(/ץ/g, 'צ')
      .replace(/\s+/g, ' ')
      .trim();
  }

  var targets = [];
  document.querySelectorAll('main .route li, main .lines li, main section[id] > h2, main .qa h3').forEach(function (el) {
    var link = el.querySelector('a');
    var note = el.querySelector('.muted');
    var label = (link ? link.textContent + (note ? ' · ' + note.textContent : '') : el.textContent)
      .replace(/\s+/g, ' ').trim();
    if (label) targets.push({ el: el, label: label, key: norm(label) });
  });

  var matches = [];
  var counted = false;

  function hide() { box.hidden = true; box.innerHTML = ''; input.setAttribute('aria-expanded', 'false'); }

  function go(t) {
    hide();
    t.el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    t.el.classList.add('hit');
    setTimeout(function () { t.el.classList.remove('hit'); }, 2000);
    if (!counted && window.goatcounter && window.goatcounter.count) {
      counted = true;
      window.goatcounter.count({ path: 'in-page-search', event: true });
    }
  }

  input.addEventListener('input', function () {
    var q = norm(input.value);
    box.innerHTML = '';
    if (!q) return hide();
    matches = targets.filter(function (t) { return t.key.indexOf(q) !== -1; }).slice(0, 8);
    if (!matches.length) {
      var li = document.createElement('li');
      li.className = 'none';
      li.textContent = 'לא נמצא בעמוד הזה';
      box.appendChild(li);
    }
    matches.forEach(function (t) {
      var li = document.createElement('li');
      var b = document.createElement('button');
      b.type = 'button';
      b.textContent = t.label.length > 80 ? t.label.slice(0, 80) + '…' : t.label;
      b.addEventListener('click', function () { go(t); });
      li.appendChild(b);
      box.appendChild(li);
    });
    box.hidden = false;
    input.setAttribute('aria-expanded', 'true');
  });

  input.addEventListener('keydown', function (ev) {
    if (ev.key === 'Enter') { ev.preventDefault(); if (matches.length) go(matches[0]); }
    if (ev.key === 'Escape') hide();
  });

  document.addEventListener('click', function (ev) {
    if (!ev.target.closest('.find')) hide();
  });
})();

// Stop review: add the visitor's local time to the pre-filled form link at tap time.
(function () {
  function pad(n) { return (n < 10 ? '0' : '') + n; }
  // The line the rider came from: ?line=<id>&dir=<n>, matched against this stop's lines.
  function currentLineLabel() {
    var params = new URLSearchParams(window.location.search);
    var line = params.get('line');
    if (!line) return '';
    var dir = params.get('dir') || '';
    var items = document.querySelectorAll('li[data-line]');
    for (var i = 0; i < items.length; i++) {
      var li = items[i];
      if (li.getAttribute('data-line') === line && (!dir || li.getAttribute('data-dir') === dir)) {
        return li.getAttribute('data-label');
      }
    }
    return '';
  }
  document.querySelectorAll('a[data-visit-time]').forEach(function (a) {
    var field = a.getAttribute('data-visit-time');
    if (!field) return;
    a.addEventListener('click', function () {
      var t = new Date(Date.now());
      var stamp = t.getFullYear() + '-' + pad(t.getMonth() + 1) + '-' + pad(t.getDate()) +
        ' ' + pad(t.getHours()) + ':' + pad(t.getMinutes());
      var url = new URL(a.href);
      url.searchParams.set(field, stamp);
      var lineField = a.getAttribute('data-line-field');
      var label = currentLineLabel();
      if (lineField && label) url.searchParams.set(lineField, label);
      a.href = url.toString();
    });
  });
})();
