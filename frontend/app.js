const API = '';  // same origin

// ── Theme ───────────────────────────────────────────────────────
// Apply saved preference immediately to avoid flash-of-wrong-theme
(function initTheme() {
  const saved = localStorage.getItem('theme') || 'dark';
  document.documentElement.dataset.theme = saved;
})();

function toggleTheme(btn) {
  const html = document.documentElement;
  const goLight = html.dataset.theme !== 'light';
  html.dataset.theme = goLight ? 'light' : 'dark';
  localStorage.setItem('theme', html.dataset.theme);
  _applyThemeButton();
}

function _applyThemeButton() {
  const isLight = document.documentElement.dataset.theme === 'light';
  const icon  = document.getElementById('themeIcon');
  const label = document.getElementById('themeLabel');
  if (icon)  icon.textContent  = isLight ? '🌙' : '☀️';
  if (label) label.textContent = isLight ? 'Dark' : 'Light';
}

// ── State ───────────────────────────────────────────────────────
let evtSource = null;
let latestCommentary = '';
let eventCount = 0;

// ── Player performance tracking ─────────────────────────────────
const _playerStats = new Map(); // name → { team, actions:{type:count}, total }

function _trackPlayer(data) {
  const player = data.player;
  if (!player) return;
  const cur = _playerStats.get(player) || { team: data.team || '', actions: {}, total: 0 };
  const t = data.type || 'other';
  cur.actions[t] = (cur.actions[t] || 0) + 1;
  cur.total++;
  _playerStats.set(player, cur);
}

// ── Voice commentary (Web Speech API) ──────────────────────────
let _voiceOn = false;
const _synth = window.speechSynthesis || null;
const _speechQueue = [];
let _speechBusy = false;

function toggleVoice(btn) {
  _voiceOn = !_voiceOn;
  btn.classList.toggle('active', _voiceOn);
  btn.textContent = _voiceOn ? '🔊' : '🔇';
  btn.title = _voiceOn ? 'Voice ON — click to mute' : 'Enable voice commentary';
  if (!_voiceOn && _synth) {
    _synth.cancel();
    _speechQueue.length = 0;
    _speechBusy = false;
  }
}

function _drainSpeechQueue() {
  if (_speechBusy || _speechQueue.length === 0 || !_synth) return;
  const text = _speechQueue.shift();
  _speechBusy = true;
  const utt = new SpeechSynthesisUtterance(text);
  utt.rate = 1.05; utt.pitch = 1.0; utt.volume = 0.9;
  const voices = _synth.getVoices();
  const pick = voices.find(v => v.lang === 'en-GB') || voices.find(v => v.lang.startsWith('en')) || null;
  if (pick) utt.voice = pick;
  utt.onend = () => { _speechBusy = false; _drainSpeechQueue(); };
  utt.onerror = () => { _speechBusy = false; _drainSpeechQueue(); };
  _synth.speak(utt);
}

// priority=true: clear queue and interrupt (used for goals/cards/chat answers)
function _speak(text, priority = false) {
  if (!_voiceOn || !_synth) return;
  if (priority) {
    _speechQueue.length = 0;
    _synth.cancel();
    _speechBusy = false;
  }
  // Drop ambient filler if already 2 items queued — keeps commentary current
  if (_speechQueue.length >= 2) return;
  _speechQueue.push(text);
  _drainSpeechQueue();
}

// ── Fan Prediction ──────────────────────────────────────────────
let _prediction = null; // { home, away } once locked

function submitPrediction() {
  const h = parseInt(document.getElementById('predHome').value, 10);
  const a = parseInt(document.getElementById('predAway').value, 10);
  if (isNaN(h) || isNaN(a)) return;
  _prediction = { home: h, away: a };
  _lockPredictionUI();
  showToast(`Prediction locked: ${h}–${a}`);
}

function _lockPredictionUI() {
  const { home, away } = _prediction;
  document.getElementById('predHome').disabled = true;
  document.getElementById('predAway').disabled = true;
  document.getElementById('predSubmitBtn').disabled = true;
  const chip = document.getElementById('predChip');
  chip.textContent = `${home}–${away} Locked`;
  chip.className = 'status-chip locked';
}

function _showPredictionResult(finalScore) {
  if (!_prediction) return;
  const { home: fh, away: fa } = finalScore;
  const { home: ph, away: pa } = _prediction;
  const chip = document.getElementById('predChip');
  const body = document.getElementById('predBody');
  const correct = fh === ph && fa === pa;
  chip.textContent = correct ? '✓ Correct!' : `Final: ${fh}–${fa}`;
  chip.className = 'status-chip ' + (correct ? 'correct' : 'wrong');
  body.innerHTML += `<div style="margin-top:8px;font-size:11px;color:${correct ? 'var(--pl-green)' : 'var(--danger)'};">
    ${correct ? '🎯 Perfect prediction!' : `Your pick: ${ph}–${pa} · Final: ${fh}–${fa}`}</div>`;
}

// ── AI Pundit Chat ──────────────────────────────────────────────
const _chatHistory = [];
let _chatTypingId = null;

function useSuggestion(btn) {
  document.getElementById('chatInput').value = btn.textContent;
  sendChatMessage();
}

async function sendChatMessage() {
  const input = document.getElementById('chatInput');
  const msg = input.value.trim();
  if (!msg) return;
  input.value = '';

  // Clear intro on first message
  const intro = document.querySelector('.chat-intro');
  if (intro) intro.remove();

  _appendChatMsg('user', msg);
  _chatHistory.push({ role: 'user', content: msg });

  const typingEl = _showTyping();

  const res = await fetch(`${API}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question: msg, history: _chatHistory.slice(-6) }),
  }).catch(() => null);

  typingEl.remove();

  if (!res || !res.ok) {
    _appendChatMsg('ai', 'The pundit is currently unavailable. Start the match first and try again.');
    return;
  }
  const data = await res.json();
  _appendChatMsg('ai', data.answer);
  _chatHistory.push({ role: 'assistant', content: data.answer });
  _speak(data.answer, true); // chat answers always interrupt — user is waiting
}

function _appendChatMsg(role, text) {
  const feed = document.getElementById('chatMessages');
  const div = document.createElement('div');
  div.className = `chat-msg ${role}`;
  div.innerHTML = `
    <div class="chat-avatar">${role === 'user' ? '👤' : '🎙️'}</div>
    <div class="chat-bubble">${escHtml(text)}</div>`;
  feed.appendChild(div);
  feed.scrollTop = feed.scrollHeight;
}

function _showTyping() {
  const feed = document.getElementById('chatMessages');
  const el = document.createElement('div');
  el.className = 'chat-msg ai';
  el.innerHTML = `<div class="chat-avatar">🎙️</div>
    <div class="chat-typing"><span></span><span></span><span></span></div>`;
  feed.appendChild(el);
  feed.scrollTop = feed.scrollHeight;
  return el;
}

// ── Player Performance Tab ──────────────────────────────────────
function renderPlayerStats() {
  const list = document.getElementById('playersList');
  const empty = document.getElementById('playersEmpty');

  if (_playerStats.size === 0) {
    empty.style.display = '';
    list.innerHTML = '';
    return;
  }
  empty.style.display = 'none';

  const sorted = [..._playerStats.entries()]
    .sort((a, b) => b[1].total - a[1].total)
    .slice(0, 10);

  const maxTotal = sorted[0]?.[1].total || 1;

  list.innerHTML = sorted.map(([name, stat], i) => {
    const rank = i === 0 ? 'top1' : i === 1 ? 'top2' : i === 2 ? 'top3' : '';
    const pct = Math.round((stat.total / maxTotal) * 100);
    const chips = Object.entries(stat.actions)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 5)
      .map(([t, c]) => `<span class="action-chip">${t.replace(/_/g,' ')} ×${c}</span>`)
      .join('');
    return `
      <div class="player-row">
        <div class="player-row-header">
          <span class="player-rank ${rank}">#${i + 1}</span>
          <span class="player-name-label">${escHtml(name)}</span>
          <span class="player-team-label">${escHtml(stat.team)}</span>
          <span class="player-count-label">${stat.total} actions</span>
        </div>
        <div class="player-action-bar"><div class="player-action-fill" style="width:${pct}%"></div></div>
        <div class="player-actions-chips">${chips}</div>
      </div>`;
  }).join('');
}

// ── Team logos (API-Football media CDN, publicly accessible) ────
const TEAM_LOGOS = {
  'Manchester City':   'https://media.api-sports.io/football/teams/50.png',
  'Arsenal':           'https://media.api-sports.io/football/teams/42.png',
  'Liverpool':         'https://media.api-sports.io/football/teams/40.png',
  'Chelsea':           'https://media.api-sports.io/football/teams/49.png',
  'Manchester United': 'https://media.api-sports.io/football/teams/33.png',
  'Tottenham':         'https://media.api-sports.io/football/teams/47.png',
  'Tottenham Hotspur': 'https://media.api-sports.io/football/teams/47.png',
  'Newcastle United':  'https://media.api-sports.io/football/teams/34.png',
  'Aston Villa':       'https://media.api-sports.io/football/teams/66.png',
  'West Ham United':   'https://media.api-sports.io/football/teams/48.png',
  'Brighton':          'https://media.api-sports.io/football/teams/51.png',
  'Brighton & Hove Albion': 'https://media.api-sports.io/football/teams/51.png',
  'Crystal Palace':    'https://media.api-sports.io/football/teams/52.png',
  'Everton':           'https://media.api-sports.io/football/teams/45.png',
  'Brentford':         'https://media.api-sports.io/football/teams/55.png',
  'Fulham':            'https://media.api-sports.io/football/teams/36.png',
  'Nottingham Forest': 'https://media.api-sports.io/football/teams/65.png',
  'Wolves':            'https://media.api-sports.io/football/teams/39.png',
  'Wolverhampton Wanderers': 'https://media.api-sports.io/football/teams/39.png',
  'Bournemouth':       'https://media.api-sports.io/football/teams/35.png',
  'Leicester City':    'https://media.api-sports.io/football/teams/46.png',
  'Southampton':       'https://media.api-sports.io/football/teams/41.png',
  'Ipswich':           'https://media.api-sports.io/football/teams/57.png',
  'Ipswich Town':      'https://media.api-sports.io/football/teams/57.png',
  'Luton Town':        'https://media.api-sports.io/football/teams/1359.png',
  'Sheffield United':  'https://media.api-sports.io/football/teams/62.png',
  'Burnley':           'https://media.api-sports.io/football/teams/44.png',
};

function setTeamLogos(homeName, awayName, homeLogo, awayLogo) {
  const hImg = document.getElementById('homeLogo');
  const aImg = document.getElementById('awayLogo');
  const hSrc = homeLogo || TEAM_LOGOS[homeName] || '';
  const aSrc = awayLogo || TEAM_LOGOS[awayName] || '';
  if (hImg) { hImg.src = hSrc; hImg.alt = homeName; hImg.style.display = hSrc ? '' : 'none'; }
  if (aImg) { aImg.src = aSrc; aImg.alt = awayName; aImg.style.display = aSrc ? '' : 'none'; }
}

const LANGUAGES = {
  en: '🇬🇧 English', es: '🇪🇸 Spanish', fr: '🇫🇷 French',
  de: '🇩🇪 German',  ar: '🇸🇦 Arabic',  zh: '🇨🇳 Mandarin',
  pt: '🇧🇷 Portuguese', hi: '🇮🇳 Hindi', ja: '🇯🇵 Japanese',
};

const EVENT_ICONS = {
  goal: '⚽', own_goal: '🤦', yellow_card: '🟨', red_card: '🟥', save: '🧤',
  foul: '⚠️', corner: '🚩', free_kick: '📍', offside: '🚫', shot: '👟',
  var_check: '🖥️', penalty: '🎯', penalty_missed: '❌',
  half_time: '⏸️', full_time: '🏁', shot_off_target: '💨',
  tackle: '🦶', header: '📤', dribble: '🏃', clearance: '🛡️',
  ai_commentary: '🤖', social_snippet: '📱', match_start: '🏟️',
  pass: '⚽', substitution: '🔄', connected: '🔌',
};

// ── Init ────────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', async () => {
  _applyThemeButton();
  buildLangGrid();
  // Stop any match still running from a previous session before connecting
  await fetch(`${API}/api/match/stop`, { method: 'POST' }).catch(() => {});
  await loadSquads();
  _updatePredLabels();
  connectSSE();
});

// Stop the match when the user refreshes or navigates away
window.addEventListener('pagehide', () => {
  navigator.sendBeacon(`${API}/api/match/stop`);
});

// ── SSE Connection ──────────────────────────────────────────────
function connectSSE() {
  if (evtSource) evtSource.close();
  evtSource = new EventSource(`${API}/api/match/stream`);

  evtSource.onmessage = (e) => {
    const data = JSON.parse(e.data);
    handleEvent(data);
  };

  evtSource.onerror = () => {
    setTimeout(connectSSE, 3000);
  };
}

function handleEvent(data) {
  const type = data.type;
  // Debug: log every SSE event so DevTools Console shows what arrives
  console.log('[SSE]', type, data.score ? JSON.stringify(data.score) : '', data.stats ? '✓stats' : '', data.km ? '✓km' : '');

  if (type === 'connected') {
    applyState(data.state);
    return;
  }

  // Update scoreboard / stats / clock from any event that carries these fields
  if (data.score) updateScore(data.score);
  if (data.stats) { updateStats(data.stats); }
  if (data.minute) updateClock(data.minute);

  // Update match status + team names
  if (type === 'match_start') {
    setStatus('LIVE');
    if (data.home_team) document.getElementById('homeTeam').textContent = data.home_team;
    if (data.away_team) document.getElementById('awayTeam').textContent = data.away_team;
    setTeamLogos(data.home_team, data.away_team, data.home_logo, data.away_logo);
    _updatePredLabels();
    updateScore({ home: 0, away: 0 });
    updateClock(0);
    updateStats({
      possession: { home: 50, away: 50 },
      shots: { home: 0, away: 0 }, shots_on_target: { home: 0, away: 0 },
      fouls: { home: 0, away: 0 }, yellow_cards: { home: 0, away: 0 },
      corners: { home: 0, away: 0 },
    });
    eventCount = 0;
    document.getElementById('eventsFeed').innerHTML =
      '<div style="color:var(--text-dim);font-style:italic;font-size:13px;padding:8px;">Waiting for kick-off...</div>';
    document.getElementById('eventCount').textContent = '0 events';
    _goalCount = 0;
    document.getElementById('goalTabBadge').style.display = 'none';
    document.getElementById('goalsList').innerHTML = '';
    document.getElementById('goalsEmpty').style.display = '';
    _momentCount = 0;
    document.getElementById('momentsBadge').style.display = 'none';
    document.getElementById('momentsList').innerHTML = '';
    document.getElementById('momentsEmpty').style.display = '';
    _playerStats.clear();
    document.getElementById('playersList').innerHTML = '';
    document.getElementById('playersEmpty').style.display = '';
    _prediction = null;
    document.getElementById('predHome').disabled = false;
    document.getElementById('predAway').disabled = false;
    document.getElementById('predSubmitBtn').disabled = false;
    document.getElementById('predChip').textContent = '';
    document.getElementById('predChip').className = 'status-chip';
    document.getElementById('commentaryFeed').innerHTML =
      '<div style="color:var(--text-dim);font-style:italic;font-size:13px;padding:8px;">AI commentary will appear here as the match progresses...</div>';
    document.getElementById('socialFeed').innerHTML =
      '<div style="color:var(--text-dim);font-style:italic;font-size:12px;">Goal moments generate social snippets...</div>';
    document.getElementById('recapOutput').textContent = 'Match recap will appear here after enough events have occurred.';
    _chatHistory.length = 0;
  }

  if (type === 'half_time') {
    setStatus('HT');
    // HT key moment is embedded in the half_time event itself
    if (data.km) { console.log('[KM] HT embedded km'); addKeyMoment(data.km); }
  }

  if (type === 'full_time') {
    setStatus('FT');
    document.getElementById('btnStart').disabled = false;
    document.getElementById('btnStop').disabled = true;
    if (data.km) { console.log('[KM] FT embedded km'); addKeyMoment(data.km); }
    if (data.score) _showPredictionResult(data.score);
  }

  // Explicit stats update event (replay/live mode)
  if (type === 'stats_update') {
    console.log('[StatsUpdate]', JSON.stringify(data.stats));
    updateStats(data.stats);
    return;
  }

  // AI Commentary
  if (type === 'ai_commentary') {
    addCommentary(data);
    latestCommentary = data.text;
    // Goals and red cards interrupt; ambient filler and others queue behind current speech
    const isUrgent = ['goal', 'own_goal', 'red_card', 'penalty'].includes(data.trigger_event_type);
    _speak(data.text, isUrgent);
    return;
  }

  // Social snippets
  if (type === 'social_snippet') {
    addSocialSnippet(data);
    return;
  }

  // Key moment from background AI task (goals/cards during replay/simulation)
  if (type === 'key_moment') {
    console.log('[KM] key_moment event received:', data.event_type, data.minute + "'");
    addKeyMoment(data);
    return;
  }

  // Goal build-up analysis
  if (type === 'goal_buildup') {
    renderGoalBuildup(data.data);
    return;
  }

  // Track player activity for the Players tab
  _trackPlayer(data);

  // Render match event in the live feed
  addEventToFeed(data);
  eventCount++;
  document.getElementById('eventCount').textContent = `${eventCount} events`;

  if (type === 'goal' || type === 'own_goal') {
    addGoalPlaceholder(data);
  }

  if (['goal', 'penalty', 'red_card', 'var_check'].includes(type)) {
    fetchSimilarToEvent(data);
  }
}

// ── Score / Stats / Clock ───────────────────────────────────────
function updateScore(score) {
  document.getElementById('homeScore').textContent = score.home ?? 0;
  document.getElementById('awayScore').textContent = score.away ?? 0;
}

function updateStats(stats) {
  if (stats.possession) {
    const hp = stats.possession.home ?? 50;
    const ap = stats.possession.away ?? 50;
    document.getElementById('possHome').style.width = `${hp}%`;
    document.getElementById('possAway').style.width = `${ap}%`;
    document.getElementById('homePossVal').textContent = `${hp}%`;
    document.getElementById('awayPossVal').textContent = `${ap}%`;
  }

  const rows = [
    { label: 'Shots',    hk: 'shots',           ak: 'shots',           hSide: 'home', aSide: 'away' },
    { label: 'On Target',hk: 'shots_on_target',  ak: 'shots_on_target', hSide: 'home', aSide: 'away' },
    { label: 'Fouls',    hk: 'fouls',            ak: 'fouls',           hSide: 'home', aSide: 'away' },
    { label: 'Yellows',  hk: 'yellow_cards',     ak: 'yellow_cards',    hSide: 'home', aSide: 'away' },
    { label: 'Corners',  hk: 'corners',          ak: 'corners',         hSide: 'home', aSide: 'away' },
  ];

  const container = document.getElementById('statRows');
  container.innerHTML = rows.map(r => {
    const hv = stats[r.hk]?.home ?? 0;
    const av = stats[r.ak]?.away ?? 0;
    const total = hv + av || 1;
    return `
      <div class="stat-row" style="margin-bottom:8px;">
        <span class="stat-val home">${hv}</span>
        <div class="stat-bar-wrap">
          <div class="stat-bar-home" style="width:${Math.round((hv/total)*100)}%"></div>
          <div class="stat-bar-away" style="width:${Math.round((av/total)*100)}%"></div>
        </div>
        <span class="stat-val away">${av}</span>
      </div>
      <div style="text-align:center;font-size:10px;color:var(--text-dim);margin-bottom:6px;">${r.label}</div>`;
  }).join('');
}

function updateClock(minute) {
  document.getElementById('matchClock').textContent = `${minute}'`;
}

function setStatus(status) {
  const el = document.getElementById('statusBadge');
  el.textContent = status;
  el.className = 'match-status-badge ' + status.toLowerCase();
}

function applyState(state) {
  if (!state) return;
  // Only restore the live scoreboard visuals when a match is actively running.
  // A finished or not-yet-started match shows clean defaults on page reload.
  if (state.running) {
    if (state.home_team) document.getElementById('homeTeam').textContent = state.home_team;
    if (state.away_team) document.getElementById('awayTeam').textContent = state.away_team;
    setTeamLogos(state.home_team, state.away_team);
    if (state.score) updateScore(state.score);
    updateStats({
      possession:      state.possession      || { home: 50, away: 50 },
      shots:           state.shots           || { home: 0, away: 0 },
      shots_on_target: state.shots_on_target || { home: 0, away: 0 },
      fouls:           state.fouls           || { home: 0, away: 0 },
      yellow_cards:    state.yellow_cards    || { home: 0, away: 0 },
      corners:         state.corners         || { home: 0, away: 0 },
    });
    if (state.minute) updateClock(state.minute);
    setStatus('LIVE');
  } else if (state.finished) {
    setStatus('FT');
  }
  // else: idle — leave HTML defaults intact (no score/team override)
}

// ── Event Feed ──────────────────────────────────────────────────
function addEventToFeed(data) {
  const feed = document.getElementById('eventsFeed');

  // Clear placeholder
  const placeholder = feed.querySelector('div[style]');
  if (placeholder && eventCount === 0) feed.innerHTML = '';

  const icon  = EVENT_ICONS[data.type] || '•';
  const label = (data.type || '').replace(/_/g, ' ').toUpperCase();
  const desc  = data.text || data.description || '';
  const min   = data.minute ? `${data.minute}'` : '';
  const team  = data.team || '';

  const item = document.createElement('div');
  item.className = `event-item ${data.type || ''}`;
  item.innerHTML = `
    <div class="event-minute">${min}</div>
    <div class="event-icon">${icon}</div>
    <div class="event-body">
      <div class="event-type">${label}</div>
      <div class="event-desc">${desc}</div>
      ${team ? `<div class="event-team">${team}</div>` : ''}
    </div>`;

  feed.appendChild(item);
  feed.scrollTop = feed.scrollHeight;
}

// ── AI Commentary ───────────────────────────────────────────────
function addCommentary(data) {
  const feed = document.getElementById('commentaryFeed');
  const placeholder = feed.querySelector('div[style]');
  if (placeholder) feed.innerHTML = '';

  const item = document.createElement('div');
  item.className = 'commentary-item';
  item.innerHTML = `<div class="c-minute">${data.minute || 0}' · AI Commentary</div>${escHtml(data.text)}`;
  feed.appendChild(item);
  feed.scrollTop = feed.scrollHeight;
}

// ── Social Snippets ─────────────────────────────────────────────
function addSocialSnippet(data) {
  const feed = document.getElementById('socialFeed');
  const placeholder = feed.querySelector('div[style]');
  if (placeholder) feed.innerHTML = '';

  const item = document.createElement('div');
  item.style.cssText = 'background:rgba(255,40,130,0.08);border:1px solid rgba(255,40,130,0.3);border-radius:8px;padding:8px 10px;font-size:12px;line-height:1.5;';
  item.textContent = data.text;
  feed.prepend(item);
}

// ── Match Control ───────────────────────────────────────────────
async function startMatch() {
  const speed = document.getElementById('speedSelect').value;

  // Reset UI
  document.getElementById('eventsFeed').innerHTML = '<div style="color:var(--text-dim);font-style:italic;font-size:13px;padding:8px;">Starting match...</div>';
  document.getElementById('commentaryFeed').innerHTML = '<div style="color:var(--text-dim);font-style:italic;font-size:13px;padding:8px;">Waiting for events...</div>';
  document.getElementById('socialFeed').innerHTML = '<div style="color:var(--text-dim);font-style:italic;font-size:12px;">Goal moments generate social snippets...</div>';
  eventCount = 0;
  document.getElementById('eventCount').textContent = '0 events';

  const res = await fetch(`${API}/api/match/start?speed=${speed}`, { method: 'POST' });
  if (!res.ok) {
    const err = await res.json();
    showToast('Error: ' + (err.detail || 'Could not start match'));
    return;
  }
  document.getElementById('btnStart').disabled = true;
  document.getElementById('btnStop').disabled = false;
  setStatus('LIVE');
  showToast('Match started!');
}

async function stopMatch() {
  await fetch(`${API}/api/match/stop`, { method: 'POST' });
  document.getElementById('btnStart').disabled = false;
  document.getElementById('btnStop').disabled = true;
  setStatus('FT');
  showToast('Match stopped.');
}

// ── Tactical Analysis ───────────────────────────────────────────
async function runTacticalAnalysis() {
  const out = document.getElementById('tacticalOutput');
  out.innerHTML = '<div class="spinner"></div> Analysing...';

  const res = await fetch(`${API}/api/tactical/analyse`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ focus_event: null }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const msg = res.status === 400 ? 'Start a match first — not enough events yet.' : (err.error || 'Analysis unavailable right now.');
    out.innerHTML = `<div class="prose-placeholder">${msg}</div>`; return;
  }

  const data = await res.json();
  out.innerHTML = `
    <div class="tactical-card">
      <div class="tactical-headline">${escHtml(data.headline || '')}</div>
      ${data.formation_home || data.formation_away ? `
        <div class="formation-badges">
          <div class="formation-badge">${escHtml(data.formation_home || '?')}</div>
          <span style="color:var(--text-dim);font-size:12px;line-height:2;">vs</span>
          <div class="formation-badge">${escHtml(data.formation_away || '?')}</div>
        </div>` : ''}
      <div class="tactical-row">
        <div class="t-label">🔵 ${escHtml(document.getElementById('homeTeam').textContent)}</div>
        <div class="t-body">${escHtml(data.home_pattern || '')}</div>
      </div>
      <div class="tactical-row">
        <div class="t-label">🔴 ${escHtml(document.getElementById('awayTeam').textContent)}</div>
        <div class="t-body">${escHtml(data.away_pattern || '')}</div>
      </div>
      <div class="tactical-row">
        <div class="t-label">⚔️ Key Battle</div>
        <div class="t-body">${escHtml(data.key_battle || '')}</div>
      </div>
      <div class="tactical-row">
        <div class="t-label">🔮 Prediction</div>
        <div class="t-body">${escHtml(data.prediction || '')}</div>
      </div>
    </div>`;
}

// ── Recap ───────────────────────────────────────────────────────
async function getHalfTimeAnalysis() {
  const out = document.getElementById('recapOutput');
  out.textContent = 'Generating half-time analysis...';
  out.className = 'prose';

  const res = await fetch(`${API}/api/narrative/half-time`, { method: 'POST' });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    out.textContent = res.status === 400 ? 'Play through at least one half first.' : (err.error || 'Analysis unavailable right now.');
    return;
  }
  const data = await res.json();
  out.textContent = data.text;
}

async function getMatchRecap() {
  const out = document.getElementById('recapOutput');
  out.textContent = 'Generating match report...';
  out.className = 'prose';

  const res = await fetch(`${API}/api/narrative/recap`, { method: 'POST' });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    out.textContent = res.status === 400 ? 'Play through more of the match first (need at least 5 events).' : (err.error || 'Report unavailable right now.');
    return;
  }
  const data = await res.json();
  out.textContent = data.text;
}

// ── Embedding Search ────────────────────────────────────────────
async function runSearch() {
  const query = document.getElementById('searchQuery').value.trim();
  if (!query) return;

  const out = document.getElementById('searchResults');
  out.innerHTML = '<div class="spinner"></div> Searching...';

  const res = await fetch(`${API}/api/search/similar`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, top_k: 3 }),
  });

  const data = await res.json();
  renderMoments(out, data.results);
}

async function fetchSimilarToEvent(event) {
  const out = document.getElementById('similarPanel');
  out.innerHTML = '<div class="spinner"></div>';

  const res = await fetch(`${API}/api/search/similar-event`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ event, top_k: 2 }),
  });

  if (!res.ok) { out.innerHTML = ''; return; }
  const data = await res.json();
  renderMoments(out, data.results, true);
}

function renderMoments(container, moments, compact = false) {
  if (!moments || moments.length === 0) {
    container.innerHTML = '<div class="prose-placeholder">No similar moments found.</div>';
    return;
  }
  container.innerHTML = moments.map(m => `
    <div class="moment-card">
      <div class="match-label">📅 ${escHtml(m.match)} · ${m.minute}'</div>
      <div class="moment-desc">${escHtml(m.description)}</div>
      <div class="moment-score">Similarity: ${Math.round((m.similarity_score || 0) * 100)}%</div>
      ${!compact && m.tags ? `<div class="moment-tags">${m.tags.map(t => `<span class="tag">${t}</span>`).join('')}</div>` : ''}
    </div>`).join('');
}

// ── Translation ─────────────────────────────────────────────────
function buildLangGrid() {
  const grid = document.getElementById('langGrid');
  grid.innerHTML = Object.entries(LANGUAGES).map(([code, label]) =>
    `<button class="lang-btn ${code === 'en' ? 'active' : ''}" data-lang="${code}" onclick="selectLang('${code}', this)">${label}</button>`
  ).join('');
}

async function selectLang(code, btn) {
  document.querySelectorAll('.lang-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');

  const out = document.getElementById('translationOutput');
  if (!latestCommentary) {
    out.textContent = 'No commentary yet — start the match first.';
    out.className = 'prose prose-placeholder';
    return;
  }

  out.textContent = 'Translating...';
  out.className = 'prose';

  const res = await fetch(`${API}/api/translate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text: latestCommentary, language: code }),
  });

  const data = await res.json();
  out.textContent = data.text;
}

// ── Squads ──────────────────────────────────────────────────────
async function loadSquads(fixtureId = null) {
  const panel = document.getElementById('squadsPanel');
  panel.innerHTML = '<div style="color:var(--text-dim);font-style:italic;font-size:12px;">Loading...</div>';

  if (fixtureId) {
    // Real fixture — fetch lineups from API-Football
    try {
      const res = await fetch(`${API}/api/live/lineups?fixture_id=${fixtureId}`);
      const data = await res.json();
      const lineups = data.lineups || {};
      if (Object.keys(lineups).length === 0) {
        panel.innerHTML = '<div style="color:var(--text-dim);font-style:italic;font-size:12px;">Lineups not available for this fixture.</div>';
        return;
      }
      panel.innerHTML = Object.entries(lineups).map(([team, players]) => `
        <div style="margin-bottom:10px;">
          <div style="font-size:11px;font-weight:700;color:var(--pl-green);margin-bottom:4px;">${team}</div>
          ${players.map(p => `
            <div style="display:flex;justify-content:space-between;font-size:11px;padding:2px 0;border-bottom:1px solid var(--border);">
              <span style="color:var(--text-dim);">#${p.number || '–'}</span>
              <span style="flex:1;margin-left:6px;">${escHtml(p.name)}</span>
              <span style="color:${p.position === 'SUB' ? 'var(--text-dim)' : 'var(--text)'};">${p.position || ''}</span>
            </div>`).join('')}
        </div>`).join('');
    } catch (e) {
      panel.innerHTML = '<div style="color:var(--text-dim);font-style:italic;font-size:12px;">Could not load lineups.</div>';
    }
  } else {
    // Simulation — load hard-coded squads
    const res = await fetch(`${API}/api/players`);
    if (!res.ok) { panel.innerHTML = '<div style="color:var(--text-dim)">Failed to load</div>'; return; }
    const data = await res.json();
    panel.innerHTML = Object.entries(data).map(([team, players]) => `
      <div style="margin-bottom:10px;">
        <div style="font-size:11px;font-weight:700;color:var(--pl-green);margin-bottom:4px;">${team}</div>
        ${players.map(p => `
          <div style="display:flex;justify-content:space-between;font-size:11px;padding:2px 0;border-bottom:1px solid var(--border);">
            <span style="color:var(--text-dim);">#${p.number}</span>
            <span style="flex:1;margin-left:6px;">${p.name}</span>
            <span style="color:var(--text-dim);">${p.position}</span>
          </div>`).join('')}
      </div>`).join('');
  }
}

// ── Tabs ────────────────────────────────────────────────────────
function switchTab(name, btn) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById(`tab-${name}`).classList.add('active');
  if (name === 'players') renderPlayerStats();
  if (name === 'foryou') initForYou();
}

// A shot-analysis diagram (distinct from the Goals pass-map): the ball's curved
// trajectory, the shooting-angle wedge, the outcome, and — for misses — a dashed
// 'better angle' arc to the open corner.
function shotTrajectorySvg(e) {
  const GLx = 100, GRx = 200, barY = 22, lineY = 40;     // goal frame
  const seed = ((e.minute || 0) * 37 + (e.player || '').length * 13 + (e.type || '').length * 7);
  const left = (seed % 2 === 0);
  const ox = e.is_penalty ? 150 : (74 + (seed % 152));    // shot origin
  const oy = e.is_penalty ? 150 : (120 + (seed % 48));

  // shooting angle (origin to each post)
  const ang = Math.round(Math.abs(
    Math.atan2(lineY - oy, GLx - ox) - Math.atan2(lineY - oy, GRx - ox)) * 180 / Math.PI);

  let tx, ty, badge, bcolor, showBetter = false;
  const goalCol = '#00e676', missCol = '#ff5f56';
  if (e.scored) {
    tx = left ? GLx + 16 : GRx - 16; ty = lineY - 8; badge = '⚽ GOAL'; bcolor = goalCol;
  } else if (e.type === 'save') {
    tx = 150; ty = lineY - 7; badge = '🧤 SAVED'; bcolor = missCol; showBetter = true;
  } else if (e.type === 'penalty_missed') {
    tx = left ? GLx - 13 : GRx + 13; ty = lineY - 6; badge = '❌ MISSED'; bcolor = missCol; showBetter = true;
  } else {
    if (seed % 3 === 0) { tx = 150; ty = barY - 6; badge = '⤴ OVER'; }
    else { tx = left ? GLx - 18 : GRx + 18; ty = lineY - 6; badge = '↗ WIDE'; }
    bcolor = missCol; showBetter = true;
  }
  // open corner for the better option (opposite side to the miss)
  const betterX = (tx < 150) ? GRx - 14 : GLx + 14, betterY = lineY - 9;

  // parabola control points (lift the arc = 'loop')
  const lift = 46;
  const actPath = `M ${ox} ${oy} C ${ox} ${oy - lift} ${tx} ${ty - lift} ${tx} ${ty}`;
  const betPath = `M ${ox} ${oy} C ${ox} ${oy - lift} ${betterX} ${betterY - lift} ${betterX} ${betterY}`;
  const net = [0,1,2,3,4].map(i => `<line x1="${GLx + i*25}" y1="${barY}" x2="${GLx + i*25}" y2="${lineY}" stroke="#3a5f49" stroke-width="0.5"/>`).join('')
            + [0,1,2].map(i => `<line x1="${GLx}" y1="${barY + i*6}" x2="${GRx}" y2="${barY + i*6}" stroke="#3a5f49" stroke-width="0.5"/>`).join('');
  const last = (e.player || '').split(' ').slice(-1)[0] || '';

  return `
  <svg viewBox="0 0 300 200" width="100%" style="max-height:200px;background:linear-gradient(#12482e,#0a2417);border-radius:6px;">
    <defs>
      <marker id="sm-a" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto"><path d="M0,0 L0,6 L6,3 z" fill="${bcolor}"/></marker>
      <marker id="sm-b" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto"><path d="M0,0 L0,6 L6,3 z" fill="${goalCol}"/></marker>
    </defs>
    <rect x="46" y="40" width="208" height="92" fill="none" stroke="#1f5a37" stroke-width="1.3"/>
    <rect x="110" y="40" width="80" height="34" fill="none" stroke="#1f5a37" stroke-width="1.1"/>
    <circle cx="150" cy="104" r="2" fill="#2f6a49"/>
    ${net}
    <line x1="${GLx}" y1="${lineY}" x2="${GLx}" y2="${barY}" stroke="#eef4fb" stroke-width="3"/>
    <line x1="${GRx}" y1="${lineY}" x2="${GRx}" y2="${barY}" stroke="#eef4fb" stroke-width="3"/>
    <line x1="${GLx}" y1="${barY}" x2="${GRx}" y2="${barY}" stroke="#eef4fb" stroke-width="3"/>
    <!-- shooting-angle wedge -->
    <polygon points="${ox},${oy} ${GLx},${lineY} ${GRx},${lineY}" fill="rgba(255,255,255,0.06)" stroke="rgba(255,255,255,0.12)" stroke-width="0.5"/>
    ${showBetter ? `<path d="${betPath}" fill="none" stroke="${goalCol}" stroke-width="1.8" stroke-dasharray="5 4" marker-end="url(#sm-b)" opacity="0.9"/>
      <circle cx="${betterX}" cy="${betterY}" r="3" fill="${goalCol}"/>
      <text x="${betterX}" y="${betterY - 5}" text-anchor="middle" font-size="8" fill="${goalCol}" font-weight="700">better</text>` : ''}
    <path d="${actPath}" fill="none" stroke="${bcolor}" stroke-width="2.4" marker-end="url(#sm-a)"/>
    <circle cx="${ox}" cy="${oy}" r="4" fill="#4db4ff"/>
    <text x="${ox}" y="${oy + 14}" text-anchor="middle" font-size="9" fill="#bfe3ff">${escHtml(last)}</text>
    <text x="150" y="150" text-anchor="middle" font-size="8" fill="rgba(255,255,255,0.55)">angle ≈ ${ang}°</text>
    <text x="150" y="192" text-anchor="middle" font-size="11" fill="${bcolor}" font-weight="bold">${badge}</text>
  </svg>`;
}

// ── Goal Projection: xG projection + near-miss coaching ──────────────────────
async function runGoalProjection() {
  const out = document.getElementById('projectionOutput');
  out.innerHTML = '<div class="spinner"></div> Projecting the match…';
  let d;
  try {
    const res = await fetch(`${API}/api/goal/projection`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ near_misses: 3 }),
    });
    d = await res.json();
    if (!res.ok || d.error) throw new Error(d.error || 'unavailable');
  } catch (e) {
    out.innerHTML = '<div class="prose-placeholder">Start a match first — need shots and chances to project.</div>';
    return;
  }

  const home = escHtml(d.home_team || 'Home'), away = escHtml(d.away_team || 'Away');
  const wp = d.win_prob || {}, xg = d.xg || {}, ps = d.projected_score || {}, sc = d.score || {};
  const shots = (d.shot_map || []).map(s => {
    const better = (!s.scored && s.better_angle)
      ? `<div style="font-size:12px;margin-top:6px;"><span style="color:var(--pl-green);">⚑ Better angle:</span> ${escHtml(s.better_angle)}</div>` : '';
    return `
    <div class="shot-card ${s.scored ? 'goal' : 'miss'}">
      <div class="shot-card-head">
        <b>${escHtml(s.player || '')}</b>
        <span>${s.minute}' · ${escHtml((s.type || '').replace(/_/g, ' '))} · xG ${s.xg}</span>
      </div>
      ${shotTrajectorySvg(s)}
      <div style="font-size:11px;color:var(--text-dim);margin-top:6px;">${escHtml(s.what_happened || '')}</div>
      ${better}
    </div>`;
  }).join('') || '<div class="prose-placeholder" style="font-size:12px;">No shots on record yet — start a match and let chances build.</div>';

  out.innerHTML = `
    <div class="tactical-card">
      <div style="display:flex;justify-content:space-around;align-items:center;text-align:center;margin-bottom:12px;">
        <div><div style="font-size:10px;color:var(--text-muted);">NOW</div>
          <div style="font-size:22px;font-weight:700;">${sc.home || 0} – ${sc.away || 0}</div></div>
        <div style="color:var(--text-dim);">→</div>
        <div><div style="font-size:10px;color:var(--pl-green);">PROJECTED</div>
          <div style="font-size:26px;font-weight:800;color:var(--pl-green);">${ps.home || 0} – ${ps.away || 0}</div></div>
      </div>
      <div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:4px;">
        <span>xG ${home}: <b>${xg.home ?? 0}</b></span>
        <span>Next goal &lt;15': <b>${d.next_goal_15min_pct ?? 0}%</b></span>
        <span>xG ${away}: <b>${xg.away ?? 0}</b></span>
      </div>
      <div style="font-size:10px;color:var(--text-muted);text-transform:uppercase;letter-spacing:.5px;margin:12px 0 4px;">Win Probability</div>
      <div style="display:flex;height:22px;border-radius:5px;overflow:hidden;font-size:10px;color:#06110a;font-weight:700;">
        <div style="width:${wp.home || 0}%;background:var(--pl-green);display:flex;align-items:center;justify-content:center;">${wp.home || 0}%</div>
        <div style="width:${wp.draw || 0}%;background:#4a5568;display:flex;align-items:center;justify-content:center;color:#fff;">${wp.draw || 0}%</div>
        <div style="width:${wp.away || 0}%;background:#ff5f56;display:flex;align-items:center;justify-content:center;color:#fff;">${wp.away || 0}%</div>
      </div>
      <div style="display:flex;justify-content:space-between;font-size:10px;color:var(--text-muted);margin-top:3px;">
        <span>${home}</span><span>Draw</span><span>${away}</span>
      </div>
      <div style="font-size:10px;color:var(--text-muted);text-transform:uppercase;letter-spacing:.5px;margin:14px 0 6px;">Shot Map · Trajectory & Better Angle</div>
      ${shots}
    </div>`;
}

// Deterministic shot-map SVG: parabola from where the player shot toward goal.
// Goals curve into the net (green); misses show the actual path (red) plus a
// dashed green 'better angle' to an open corner.
function shotMapSvg(e) {
  const seed = ((e.minute || 0) * 37 + (e.player || '').length * 13 + (e.type || '').length * 7);
  const left = (seed % 2 === 0);
  const GL = 92, GR = 168, GY = 34, TOP = 16;           // goal mouth geometry
  const ox = e.is_penalty ? 130 : (58 + (seed % 145));  // shot origin x
  const oy = e.is_penalty ? 118 : 152;                  // shot origin y
  const cornerX = left ? GL + 12 : GR - 12, cornerY = GY + 7;

  let tx, ty, badge, showBetter = false;
  const acc = e.scored ? '#00e676' : '#ff5f56';
  if (e.scored) {
    tx = left ? GL + 15 : GR - 15; ty = GY + 6; badge = '⚽ GOAL';
  } else if (e.type === 'save') {
    tx = 130; ty = GY + 6; badge = '🧤 SAVED'; showBetter = true;
  } else if (e.type === 'penalty_missed') {
    tx = left ? GL - 12 : GR + 12; ty = GY + 2; badge = '❌ MISSED'; showBetter = true;
  } else { // shot_off_target
    if (seed % 3 === 0) { tx = 130; ty = TOP - 3; } else { tx = left ? GL - 16 : GR + 16; ty = GY - 2; }
    badge = '↗ OFF TARGET'; showBetter = true;
  }
  const cx = (ox + tx) / 2, cy = Math.min(oy, ty) - 36;                 // parabola arc
  const bcx = (ox + cornerX) / 2, bcy = Math.min(oy, cornerY) - 42;
  const last = (e.player || '').split(' ').slice(-1)[0] || '';

  return `
  <svg viewBox="0 0 260 175" width="100%" style="max-height:178px;background:linear-gradient(#103022,#0a1f14);border-radius:6px;">
    <rect x="50" y="34" width="160" height="78" fill="none" stroke="#1f5a37" stroke-width="1.4"/>
    <rect x="95" y="34" width="70" height="30" fill="none" stroke="#1f5a37" stroke-width="1.2"/>
    <line x1="18" y1="34" x2="242" y2="34" stroke="#1f5a37" stroke-width="1"/>
    ${[0,1,2,3,4].map(i=>`<line x1="${GL+ i*19}" y1="${TOP}" x2="${GL+ i*19}" y2="${GY}" stroke="#2a4d3a" stroke-width="0.6"/>`).join('')}
    <line x1="${GL}" y1="${GY}" x2="${GL}" y2="${TOP}" stroke="#e8eef5" stroke-width="3"/>
    <line x1="${GR}" y1="${GY}" x2="${GR}" y2="${TOP}" stroke="#e8eef5" stroke-width="3"/>
    <line x1="${GL}" y1="${TOP}" x2="${GR}" y2="${TOP}" stroke="#e8eef5" stroke-width="3"/>
    ${showBetter ? `<path d="M ${ox} ${oy} Q ${bcx} ${bcy} ${cornerX} ${cornerY}" fill="none" stroke="#00e676" stroke-width="1.8" stroke-dasharray="4 3"/>
      <circle cx="${cornerX}" cy="${cornerY}" r="3" fill="#00e676"/>` : ''}
    <path d="M ${ox} ${oy} Q ${cx} ${cy} ${tx} ${ty}" fill="none" stroke="${acc}" stroke-width="2.4"/>
    <circle cx="${tx}" cy="${ty}" r="3.5" fill="${acc}"/>
    <circle cx="${ox}" cy="${oy}" r="4" fill="#4db4ff"/>
    <text x="${ox}" y="${oy + 14}" fill="#bfe3ff" font-size="9" text-anchor="middle">${escHtml(last)}</text>
    <text x="130" y="170" fill="${acc}" font-size="11" text-anchor="middle" font-weight="bold">${badge}</text>
    ${showBetter ? `<text x="${cornerX}" y="${cornerY - 6}" fill="#00e676" font-size="8" text-anchor="middle">better</text>` : ''}
  </svg>`;
}

// ── For You: multi-agent personalized intelligence ───────────────────────────
// Re-populate every time the tab opens so clubs/players track the CURRENT match
// (simulation OR a replayed fixture), not the static Man City vs Arsenal squad.
async function initForYou() {
  const clubSel = document.getElementById('fyClub');
  const playerSel = document.getElementById('fyPlayer');
  const prevClub = clubSel.value, prevPlayer = playerSel.value;
  try {
    const res = await fetch(`${API}/api/match/participants`);
    const data = await res.json();
    clubSel.innerHTML = '<option value="">Favourite club…</option>';
    [data.home_team, data.away_team].filter(Boolean).forEach(team => {
      clubSel.insertAdjacentHTML('beforeend', `<option value="${escHtml(team)}">${escHtml(team)}</option>`);
    });
    playerSel.innerHTML = '<option value="">Player-focus: none</option>';
    (data.players || []).forEach(p => {
      const tag = (p.team || '').split(' ')[0];
      playerSel.insertAdjacentHTML('beforeend',
        `<option value="${escHtml(p.name)}">${escHtml(p.name)}${tag ? ' (' + escHtml(tag) + ')' : ''}</option>`);
    });
    // restore selection: previous in-session choice, else saved profile (if still valid)
    const saved = JSON.parse(localStorage.getItem('fyProfile') || '{}');
    const wantClub = prevClub || saved.favorite_club || '';
    const wantPlayer = prevPlayer || saved.focus_player || '';
    if ([...clubSel.options].some(o => o.value === wantClub)) clubSel.value = wantClub;
    if ([...playerSel.options].some(o => o.value === wantPlayer)) playerSel.value = wantPlayer;
    if (saved.mode) document.getElementById('fyMode').value = saved.mode;
    if (saved.language) document.getElementById('fyLang').value = saved.language;
  } catch (e) { /* participants endpoint optional */ }
}

function _momentumBar(v) {
  const w = Math.min(50, Math.abs(v || 0) / 2);
  if ((v || 0) >= 0)
    return `<div style="position:absolute;left:50%;top:0;bottom:0;width:${w}%;background:var(--pl-green);"></div>`;
  return `<div style="position:absolute;right:50%;top:0;bottom:0;width:${w}%;background:#ff5f56;"></div>`;
}

async function runForYou() {
  const out = document.getElementById('foryouOutput');
  const profile = {
    favorite_club: document.getElementById('fyClub').value,
    focus_player:  document.getElementById('fyPlayer').value,
    mode:          document.getElementById('fyMode').value,
    language:      document.getElementById('fyLang').value,
  };
  localStorage.setItem('fyProfile', JSON.stringify(profile));
  out.innerHTML = '<div class="spinner"></div> Five agents collaborating…';

  let data;
  try {
    const res = await fetch(`${API}/api/agents/analyse`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ profile }),
    });
    data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || 'unavailable');
  } catch (e) {
    out.innerHTML = '<div class="prose-placeholder">Start a match first — the agents need live events to analyse.</div>';
    return;
  }

  const p = data.personalized || {}, tr = data.trace || [], ov = data.overlay || {};
  const chips = (ov.chips || []).map(c =>
    `<span class="formation-badge">${escHtml(c.k)}: ${escHtml(String(c.v))}</span>`).join('');
  const mb = ov.momentum_bar || {};
  const pipeline = tr.map(s => {
    const warn = s.status === 'recovered';
    return `
    <div class="agent-wrap">
      <div class="agent-row" onclick="toggleAgentRow(this)">
        <span class="agent-dot ${warn ? 'warn' : ''}"></span>
        <span class="agent-name">${escHtml(s.agent)}</span>
        <span class="agent-role">${escHtml(s.role)}</span>
        <span class="agent-meta">${s.ms}ms ${warn ? '⚠' : '✓'}</span>
        <span class="agent-chevron">▸</span>
      </div>
      <div class="agent-detail" style="display:none;">${fyAgentDetail(s.agent, data)}</div>
    </div>`;
  }).join('');

  out.innerHTML = `
    <div class="tactical-card">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
        <div class="tactical-headline">${escHtml(p.headline || 'Live match intelligence')}</div>
        <span style="font-size:10px;color:var(--text-muted);white-space:nowrap;">${(data.summary || {}).agents || 5} agents · ${(data.summary || {}).total_ms || 0}ms</span>
      </div>
      <div style="font-size:10px;color:var(--text-muted);margin-bottom:8px;">
        ${escHtml((p.mode || '').toUpperCase())}${p.favorite_club ? ' · ' + escHtml(p.favorite_club) : ''}${p.focus_player ? ' · ◎ ' + escHtml(p.focus_player) : ''}${p.language && p.language !== 'English' ? ' · ' + escHtml(p.language) : ''}
      </div>
      <div class="prose" style="font-size:14px;line-height:1.6;">${escHtml(p.text || '')}</div>
      <div style="display:flex;gap:6px;flex-wrap:wrap;margin:12px 0 6px;">${chips}</div>
      <div style="margin:6px 0 12px;">
        <div style="font-size:10px;color:var(--text-muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:3px;">Momentum → ${escHtml(mb.label || 'balanced')}</div>
        <div style="height:8px;background:#1a2235;border-radius:4px;position:relative;overflow:hidden;">
          <div style="position:absolute;left:50%;top:0;bottom:0;width:1px;background:#3a4a6a;"></div>
          ${_momentumBar(mb.value)}
        </div>
      </div>
      <div style="font-size:10px;color:var(--text-muted);text-transform:uppercase;letter-spacing:.5px;margin:4px 0 6px;">Multi-Agent Pipeline · MCP tools <span style="text-transform:none;color:var(--text-subtle);">— tap an agent</span></div>
      ${pipeline}
    </div>`;
}

// Expand/collapse an agent row to reveal what that agent produced
function toggleAgentRow(row) {
  const detail = row.nextElementSibling;
  const open = row.classList.toggle('open');
  if (detail) detail.style.display = open ? 'block' : 'none';
}

// Build the per-agent detail from the pipeline packet
function fyAgentDetail(agent, d) {
  const m = d.metrics || {}, t = d.tactical || {}, ex = d.explain || {},
        ov = d.overlay || {}, p = d.personalized || {};
  const ld = ((d.leaders || {}).leaders) || [];
  if (agent === 'DataAgent')
    return `Momentum <b>${m.momentum ?? 0}</b> → ${escHtml(m.momentum_side || 'balanced')} · Rhythm <b>${escHtml(m.rhythm || '')}</b> · Pressure <b>${m.pressure_index ?? 0}/100</b> · Tempo <b>${m.tempo_events_per_min ?? 0}/min</b>` +
      (ld.length ? `<br><span style="color:var(--text-muted);">Top movers: ${ld.slice(0, 3).map(x => escHtml(x.player)).join(', ')}</span>` : '');
  if (agent === 'TacticsAgent')
    return `<b>${escHtml(t.headline || '—')}</b><br>Key battle: ${escHtml(t.key_battle || '—')}<br>Prediction: ${escHtml(t.prediction || '—')}`;
  if (agent === 'ExplainAgent')
    return escHtml(ex.why_it_matters || '—');
  if (agent === 'NarrativeAgent')
    return `${escHtml(d.narrative || '—')}` +
      ((ov.chips || []).length ? `<br><span style="color:var(--text-muted);">Overlay: ${ov.chips.map(c => escHtml(c.k + ' ' + c.v)).join(' · ')}</span>` : '');
  if (agent === 'PersonaAgent')
    return escHtml(p.text || '—');
  return '—';
}

// Update home/away prediction labels on team name change
function _updatePredLabels() {
  const h = document.getElementById('homeTeam')?.textContent || 'Home';
  const a = document.getElementById('awayTeam')?.textContent || 'Away';
  const hl = document.getElementById('predHomeLabel');
  const al = document.getElementById('predAwayLabel');
  if (hl) hl.textContent = h.split(' ')[0];
  if (al) al.textContent = a.split(' ')[0];
}

// ── Key Moments Timeline ────────────────────────────────────────
let _momentCount = 0;

const MOMENT_COLOURS = {
  goal:'#00ff85', own_goal:'#f87171', yellow_card:'#facc15',
  red_card:'#f87171', penalty:'#a78bfa', penalty_missed:'#94a3b8',
  var_check:'#60a5fa', save:'#34d399', half_time:'#f59e0b',
  full_time:'#f59e0b', substitution:'#94a3b8',
};

function addKeyMoment(data) {
  _momentCount++;
  const badge = document.getElementById('momentsBadge');
  badge.textContent = _momentCount;
  badge.style.display = 'inline';
  document.getElementById('momentsEmpty').style.display = 'none';

  const col  = MOMENT_COLOURS[data.event_type] || '#94a3b8';
  const item = document.createElement('div');
  item.className = 'moment-item';
  item.innerHTML = `
    <div class="moment-spine">
      <div class="moment-dot" style="background:${col};box-shadow:0 0 6px ${col}66;"></div>
      <div class="moment-line"></div>
    </div>
    <div class="moment-content">
      <div class="moment-meta">
        <span class="moment-icon">${escHtml(data.icon || '•')}</span>
        <span class="moment-label" style="color:${col};">${escHtml(data.label || data.event_type)}</span>
        <span class="moment-minute">${data.minute}'</span>
        ${data.player ? `<span class="moment-player">${escHtml(data.player)}</span>` : ''}
        ${data.score ? `<span class="moment-score">${data.score.home}–${data.score.away}</span>` : ''}
      </div>
      <div class="moment-desc">${escHtml(data.description || '')}</div>
      ${data.insight ? `<div class="moment-insight">${escHtml(data.insight)}</div>` : ''}
    </div>`;
  document.getElementById('momentsList').appendChild(item);
  // Scroll to latest
  item.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

// ── Goal Build-up Analysis ──────────────────────────────────────
let _goalCount = 0;
const _goalSequences   = new Map(); // goalId → full sequence array
const _goalCurrentStep = new Map(); // goalId → current step (1-based, 0 = "all / replay")

function addGoalPlaceholder(event) {
  _goalCount++;
  const badge = document.getElementById('goalTabBadge');
  badge.textContent = _goalCount;
  badge.style.display = 'inline';

  document.getElementById('goalsEmpty').style.display = 'none';

  const goalId = `goal-${event.minute}-${(event.player || '').replace(/\s+/g, '_')}`;
  const isOG   = event.type === 'own_goal';
  const card   = document.createElement('div');
  card.id      = goalId;
  card.className = 'goal-buildup-card';
  card.innerHTML = `
    <div class="goal-buildup-header">
      <span class="goal-buildup-icon">⚽</span>
      <div style="flex:1;">
        <div style="font-weight:700;font-size:13px;">${escHtml(event.player || 'Unknown')}${isOG ? ' <span style="color:var(--text-dim)">(OG)</span>' : ''}</div>
        <div style="font-size:11px;color:var(--text-dim);">${escHtml(event.team || '')} · ${event.minute}'</div>
      </div>
      <div style="font-size:13px;font-weight:700;">${event.score ? `${event.score.home} – ${event.score.away}` : ''}</div>
    </div>
    <div class="goal-buildup-body" id="${goalId}-body">
      <div class="spinner" style="margin:8px 0;"></div> Generating build-up analysis…
    </div>`;
  document.getElementById('goalsList').prepend(card);
}

function renderGoalBuildup(data) {
  if (!data) return;
  const goalId   = `goal-${data.minute}-${(data.scorer || '').replace(/\s+/g, '_')}`;
  const bodyEl   = document.getElementById(`${goalId}-body`);
  if (!bodyEl) {
    // Card not yet in DOM — just prepend a full card
    addGoalPlaceholder({ minute: data.minute, player: data.scorer, team: data.team,
                         type: 'goal', score: data.goal_event?.score });
    renderGoalBuildup(data);
    return;
  }

  const seq = data.buildup_sequence || [];
  const pen = data.is_penalty ? ' <span style="font-size:10px;color:var(--text-dim);">(Penalty)</span>' : '';
  const pitchSVG = buildPitchSVG(seq);

  // Store sequence for step navigation
  _goalSequences.set(goalId, seq);
  _goalCurrentStep.set(goalId, seq.length); // start showing all steps

  const navHtml = seq.length > 1 ? `
    <div class="buildup-nav" id="${goalId}-nav">
      <button id="${goalId}-prev" onclick="stepGoalBuildup('${goalId}', -1)" disabled>◀ Prev</button>
      <span class="bnav-label" id="${goalId}-step-label">Step ${seq.length} of ${seq.length}</span>
      <button id="${goalId}-next" onclick="stepGoalBuildup('${goalId}', 1)" disabled>Next ▶</button>
      <button onclick="replayGoalBuildup('${goalId}')">⟳ Replay</button>
    </div>` : '';

  bodyEl.innerHTML = `
    <div style="font-weight:700;font-size:12px;color:var(--pl-green);margin-bottom:8px;">
      ${escHtml(data.summary || '')}${pen}
    </div>
    ${pitchSVG ? `<div class="buildup-pitch" id="${goalId}-pitch">${pitchSVG}</div>` : ''}
    ${navHtml}
    <p style="font-size:12px;line-height:1.55;margin:8px 0;">${escHtml(data.buildup_narrative || '')}</p>
    <div style="display:flex;flex-direction:column;gap:4px;">
      ${data.key_player ? `<div style="font-size:11px;"><span style="color:var(--text-dim);">Key player</span> — ${escHtml(data.key_player)}</div>` : ''}
      ${data.defensive_error ? `<div style="font-size:11px;"><span style="color:var(--text-dim);">Defence</span> — ${escHtml(data.defensive_error)}</div>` : ''}
      ${data.verdict ? `<div style="font-size:11px;font-style:italic;color:var(--text-dim);margin-top:4px;">${escHtml(data.verdict)}</div>` : ''}
    </div>`;
}

// ── Pitch SVG renderer ──────────────────────────────────────────
const ZONE_COORDS = {
  'GK':  [38,  160], 'D-L': [105, 68],  'D-C': [105, 160], 'D-R': [105, 252],
  'M-L': [250, 68],  'M-C': [250, 160], 'M-R': [250, 252],
  'A-L': [390, 68],  'A-C': [390, 160], 'A-R': [390, 252],
  'GOAL':[492, 160],
};
const ACTION_COLOURS = {
  pass:'#00ff85', dribble:'#f4a700', cross:'#60a5fa',
  header:'#a78bfa', shot:'#f87171', goal:'#f87171',
  tackle:'#fb923c', clearance:'#94a3b8', default:'#00ff85',
};

function buildPitchSVG(sequence, { maxStep = Infinity, animated = true, scored = true, better = null } = {}) {
  if (!sequence || sequence.length === 0) return '';
  sequence = maxStep < Infinity ? sequence.slice(0, maxStep) : sequence;

  // Arrow marker defs — one per colour
  const colours = [...new Set(sequence.map(s => ACTION_COLOURS[s.action] || ACTION_COLOURS.default))];
  let defs = colours.map(c => {
    const id = `arr-${c.replace('#','')}`;
    return `<marker id="${id}" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
      <path d="M0,0 L0,6 L6,3 z" fill="${c}"/>
    </marker>`;
  }).join('');
  if (better) defs += `<marker id="arr-better" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto"><path d="M0,0 L0,6 L6,3 z" fill="#00e676"/></marker>`;

  // Pitch background & markings
  const pitch = `
    <rect x="10" y="10" width="480" height="300" rx="4" fill="#2d6a4f" stroke="#fff" stroke-width="1.5"/>
    <!-- halfway line -->
    <line x1="250" y1="10" x2="250" y2="310" stroke="rgba(255,255,255,0.35)" stroke-width="1"/>
    <!-- centre circle -->
    <circle cx="250" cy="160" r="38" fill="none" stroke="rgba(255,255,255,0.35)" stroke-width="1"/>
    <circle cx="250" cy="160" r="2" fill="rgba(255,255,255,0.5)"/>
    <!-- left penalty area -->
    <rect x="10" y="95" width="72" height="130" fill="none" stroke="rgba(255,255,255,0.35)" stroke-width="1"/>
    <rect x="10" y="130" width="30" height="60" fill="none" stroke="rgba(255,255,255,0.35)" stroke-width="1"/>
    <!-- right penalty area -->
    <rect x="418" y="95" width="72" height="130" fill="none" stroke="rgba(255,255,255,0.35)" stroke-width="1"/>
    <rect x="460" y="130" width="30" height="60" fill="none" stroke="rgba(255,255,255,0.35)" stroke-width="1"/>
    <!-- goals -->
    <rect x="0" y="140" width="10" height="40" fill="none" stroke="rgba(255,255,255,0.5)" stroke-width="1.5"/>
    <rect x="490" y="140" width="10" height="40" fill="none" stroke="#f87171" stroke-width="2"/>
    <!-- zone labels -->
    <text x="38" y="305" text-anchor="middle" font-size="8" fill="rgba(255,255,255,0.28)" font-family="sans-serif" font-weight="600">GK</text>
    <text x="105" y="305" text-anchor="middle" font-size="8" fill="rgba(255,255,255,0.28)" font-family="sans-serif" font-weight="600">DEF</text>
    <text x="250" y="305" text-anchor="middle" font-size="8" fill="rgba(255,255,255,0.28)" font-family="sans-serif" font-weight="600">MID</text>
    <text x="390" y="305" text-anchor="middle" font-size="8" fill="rgba(255,255,255,0.28)" font-family="sans-serif" font-weight="600">ATT</text>
    <text x="462" y="305" text-anchor="middle" font-size="7" fill="rgba(248,113,113,0.55)" font-family="sans-serif" font-weight="600">→ NET</text>
  `;

  // Build arrows + player dots
  let arrows = '', dots = '', labels = '', playerLabels = '';
  sequence.forEach((step, i) => {
    const [x1, y1] = ZONE_COORDS[step.from_zone] || [250, 160];
    const [x2, y2] = ZONE_COORDS[step.to_zone]   || [250, 160];
    const col = ACTION_COLOURS[step.action] || ACTION_COLOURS.default;
    const markerId = `arr-${col.replace('#','')}`;
    const delay = i * 0.55;

    // Slightly offset parallel arrows so they don't overlap exactly
    const ox = (i % 2) * 6 - 3, oy = (i % 3) * 4 - 4;

    const dist = Math.ceil(Math.hypot(x2 - x1, y2 - y1)) + 8;
    const arrowStyle = animated
      ? `animation:drawArrow 0.45s ease forwards;animation-delay:${delay}s`
      : `stroke-dashoffset:0`;
    const dotStyle = animated
      ? `animation:popIn 0.2s ease forwards;animation-delay:${delay}s;opacity:0`
      : `opacity:1`;
    const lblStyle = animated
      ? `animation:popIn 0.2s ease forwards;animation-delay:${delay+0.2}s`
      : `opacity:1`;

    arrows += `<line x1="${x1+ox}" y1="${y1+oy}" x2="${x2+ox}" y2="${y2+oy}"
      stroke="${col}" stroke-width="2.2" stroke-dasharray="${dist}" stroke-dashoffset="${animated ? dist : 0}"
      marker-end="url(#${markerId})" opacity="0.9" style="${arrowStyle}"/>`;

    const isGoal = step.action === 'goal';
    dots += `<circle cx="${x1+ox}" cy="${y1+oy}" r="${isGoal ? 5 : 7}" fill="${col}"
      fill-opacity="${isGoal ? 0.35 : 0.2}" stroke="${col}" stroke-width="1.5" style="${dotStyle}"/>`;

    const lx = (x1 + x2) / 2 + ox, ly = (y1 + y2) / 2 + oy - 10;
    labels += `<text x="${lx}" y="${ly}" text-anchor="middle" font-size="9"
      fill="${col}" font-family="monospace" font-weight="700" style="${lblStyle}">${step.step}</text>`;

    if (step.player) {
      const nameY = (y1 + oy) <= 160 ? (y1 + oy) - 12 : (y1 + oy) + 13;
      playerLabels += `<text x="${x1+ox}" y="${nameY}" text-anchor="middle" font-size="8"
        fill="rgba(255,255,255,0.8)" font-family="sans-serif" style="${lblStyle}">${escHtml(step.player)}</text>`;
    }
  });

  // Final marker — goal pulse if scored, else a miss cross
  const [gx, gy] = ZONE_COORDS['GOAL'];
  const lastDelay = (sequence.length - 1) * 0.55;
  let goalPulse;
  if (scored) {
    goalPulse = animated ? `
      <circle cx="${gx}" cy="${gy}" r="12" fill="#f87171" fill-opacity="0" stroke="#f87171" stroke-width="2"
        style="animation:goalPulse 0.6s ease forwards;animation-delay:${lastDelay+0.3}s;opacity:0"/>
      <text x="${gx}" y="${gy+5}" text-anchor="middle" font-size="14" fill="#f87171" opacity="0"
        style="animation:popIn 0.3s ease forwards;animation-delay:${lastDelay+0.4}s">⚽</text>` : `
      <circle cx="${gx}" cy="${gy}" r="12" fill="#f87171" fill-opacity="0.15" stroke="#f87171" stroke-width="2"/>
      <text x="${gx}" y="${gy+5}" text-anchor="middle" font-size="14" fill="#f87171">⚽</text>`;
  } else {
    goalPulse = `
      <circle cx="${gx}" cy="${gy}" r="11" fill="none" stroke="#ff5f56" stroke-width="2"/>
      <text x="${gx}" y="${gy+5}" text-anchor="middle" font-size="13" fill="#ff5f56" font-weight="700">✗</text>`;
  }

  // Better-angle dashed arrow to an open corner (misses only)
  let betterArrow = '';
  if (better) {
    const [bx, by] = ZONE_COORDS[better.from_zone] || [390, 160];
    const cornerY = better.corner === 'top' ? 146 : 174;
    betterArrow = `
      <line x1="${bx}" y1="${by}" x2="${gx}" y2="${cornerY}" stroke="#00e676" stroke-width="2.2"
        stroke-dasharray="5 4" marker-end="url(#arr-better)" opacity="0.95"/>
      <circle cx="${gx}" cy="${cornerY}" r="3" fill="#00e676"/>
      <text x="${(bx+gx)/2}" y="${(by+cornerY)/2 - 6}" text-anchor="middle" font-size="8"
        fill="#00e676" font-family="sans-serif" font-weight="700">${escHtml(better.label || 'better angle')}</text>`;
  }

  // Legend
  const legendItems = [...new Set(sequence.map(s => s.action))];
  const legend = legendItems.map((action, i) => {
    const col = ACTION_COLOURS[action] || ACTION_COLOURS.default;
    return `<g transform="translate(${15 + i*80},318)">
      <line x1="0" y1="6" x2="18" y2="6" stroke="${col}" stroke-width="2"/>
      <text x="22" y="10" font-size="9" fill="rgba(255,255,255,0.7)" font-family="sans-serif">${action}</text>
    </g>`;
  }).join('');

  // Step labels below pitch
  const stepList = sequence.map(s =>
    `<div style="font-size:10px;padding:3px 0;border-bottom:1px solid rgba(255,255,255,0.08);display:flex;gap:6px;align-items:center;">
      <span style="color:${ACTION_COLOURS[s.action]||'#00ff85'};font-weight:700;min-width:16px;">${s.step}.</span>
      <span style="color:rgba(255,255,255,0.7);min-width:60px;">${escHtml(s.player||'')}</span>
      <span style="color:rgba(255,255,255,0.45);font-style:italic;">${escHtml(s.label||s.action)}</span>
    </div>`
  ).join('');

  return `
    <svg viewBox="0 0 500 330" style="width:100%;border-radius:4px;display:block;">
      <defs>${defs}</defs>
      ${pitch}${arrows}${dots}${labels}${playerLabels}${betterArrow}${goalPulse}
      <g>${legend}</g>
    </svg>
    <div style="padding:8px 0 0;">${stepList}</div>`;
}

async function requestGoalBuildup(goalEvent) {
  const goalId = `goal-${goalEvent.minute}-${(goalEvent.player || '').replace(/\s+/g, '_')}`;
  const bodyEl = document.getElementById(`${goalId}-body`);
  if (bodyEl) bodyEl.innerHTML = '<div class="spinner"></div> Generating…';

  const res = await fetch(`${API}/api/goal/buildup`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ goal_event: goalEvent }),
  });
  if (!res.ok) return;
  const data = await res.json();
  renderGoalBuildup(data);
}

// ── Goal buildup step navigation ────────────────────────────────
function _updateNavButtons(goalId, step, total) {
  const prev  = document.getElementById(`${goalId}-prev`);
  const next  = document.getElementById(`${goalId}-next`);
  const label = document.getElementById(`${goalId}-step-label`);
  if (prev)  prev.disabled  = step <= 1;
  if (next)  next.disabled  = step >= total;
  if (label) label.textContent = `Step ${step} of ${total}`;
}

function stepGoalBuildup(goalId, dir) {
  const seq  = _goalSequences.get(goalId);
  if (!seq || seq.length === 0) return;
  const total   = seq.length;
  const current = _goalCurrentStep.get(goalId) || total;
  const next    = Math.max(1, Math.min(total, current + dir));
  _goalCurrentStep.set(goalId, next);

  const pitchEl = document.getElementById(`${goalId}-pitch`);
  if (pitchEl) pitchEl.innerHTML = buildPitchSVG(seq, { maxStep: next, animated: false });
  _updateNavButtons(goalId, next, total);
}

function replayGoalBuildup(goalId) {
  const seq = _goalSequences.get(goalId);
  if (!seq || seq.length === 0) return;
  const total   = seq.length;
  _goalCurrentStep.set(goalId, total);

  const pitchEl = document.getElementById(`${goalId}-pitch`);
  if (pitchEl) {
    // Force re-render by replacing content — CSS animations restart on insert
    pitchEl.innerHTML = buildPitchSVG(seq, { animated: true });
  }
  _updateNavButtons(goalId, total, total);
}

// ── Live / Replay Mode ──────────────────────────────────────────
let _currentMode = 'simulation';

function setMode(mode) {
  _currentMode = mode;
  document.getElementById('simControls').style.display  = mode === 'simulation' ? 'flex' : 'none';
  document.getElementById('simControls').style.flexDirection = 'column';
  document.getElementById('liveControls').style.display = mode === 'live'       ? 'flex' : 'none';
  document.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
  document.getElementById(mode === 'simulation' ? 'modeSimBtn' : 'modeLiveBtn').classList.add('active');

  if (mode === 'simulation') {
    // Restore simulator fixture in the header
    document.getElementById('homeTeam').textContent = 'Manchester City';
    document.getElementById('awayTeam').textContent = 'Arsenal';
    setTeamLogos('Manchester City', 'Arsenal');
    updateScore({ home: 0, away: 0 });
    updateClock(0);
    setStatus('READY');
    loadSquads();           // hard-coded squads
  } else {
    loadFixtures('recent'); // populate fixture dropdown
  }
}

async function loadFixtures(mode) {
  const sel = document.getElementById('fixtureSelect');
  const status = document.getElementById('liveStatus');
  sel.innerHTML = '<option value="">Loading...</option>';
  status.textContent = `Fetching ${mode} fixtures...`;

  try {
    const res = await fetch(`${API}/api/live/fixtures?mode=${mode}`);
    const data = await res.json();

    if (data.error) {
      sel.innerHTML = '<option value="">Error loading fixtures</option>';
      status.textContent = data.error;
      return;
    }

    const fixtures = data.fixtures || [];
    if (fixtures.length === 0) {
      sel.innerHTML = `<option value="">No ${mode} fixtures found</option>`;
      status.textContent = '';
      return;
    }

    sel.innerHTML = fixtures.map(f => {
      const score = (f.home_score != null && f.away_score != null)
        ? ` ${f.home_score}-${f.away_score}` : '';
      const min = f.minute ? ` (${f.minute}')` : '';
      return `<option value="${f.id}"
        data-home="${escHtml(f.home_team)}" data-away="${escHtml(f.away_team)}"
        data-home-logo="${escHtml(f.home_logo||'')}" data-away-logo="${escHtml(f.away_logo||'')}">
        ${f.date} · ${f.home_team} vs ${f.away_team}${score}${min}</option>`;
    }).join('');

    // Preview logos for first fixture
    if (fixtures.length) updateLogoFromSelect();

    status.textContent = `${fixtures.length} fixtures loaded`;
  } catch (e) {
    sel.innerHTML = '<option value="">Failed — check API key</option>';
    status.textContent = String(e);
  }
}

function updateLogoFromSelect() {
  const sel = document.getElementById('fixtureSelect');
  const opt = sel.options[sel.selectedIndex];
  if (!opt || !opt.value) return;
  setTeamLogos(
    opt.dataset.home || '', opt.dataset.away || '',
    opt.dataset.homeLogo || '', opt.dataset.awayLogo || ''
  );
  document.getElementById('homeTeam').textContent = opt.dataset.home || '';
  document.getElementById('awayTeam').textContent = opt.dataset.away || '';
}

async function startReplay() {
  const fixtureId = document.getElementById('fixtureSelect').value;
  if (!fixtureId) { showToast('Select a fixture first'); return; }
  const status = document.getElementById('liveStatus');
  status.textContent = 'Starting replay...';

  // Load lineups for this fixture immediately
  loadSquads(fixtureId);

  const speedVal = parseFloat(document.getElementById('speedSelect').value) || 1.5;
  const res = await fetch(`${API}/api/live/replay`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ fixture_id: parseInt(fixtureId), speed: speedVal }),
  });
  const data = await res.json();
  status.textContent = data.error ? `Error: ${data.error}` : 'Replay running — events will stream in';
}

async function startLive() {
  const fixtureId = document.getElementById('fixtureSelect').value;
  if (!fixtureId) { showToast('Select a fixture first'); return; }
  const status = document.getElementById('liveStatus');
  status.textContent = 'Connecting to live match...';

  // Load lineups for this fixture immediately
  loadSquads(fixtureId);

  const res = await fetch(`${API}/api/live/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ fixture_id: parseInt(fixtureId), poll_interval: 60 }),
  });
  const data = await res.json();
  status.textContent = data.error ? `Error: ${data.error}` : 'Polling live match every 60s';
}

// ── Helpers ─────────────────────────────────────────────────────
function showToast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 3000);
}

function escHtml(str) {
  return String(str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
