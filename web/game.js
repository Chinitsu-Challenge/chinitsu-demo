// === Chinitsu Showdown Frontend ===

// === State ===
let ws = null;
let myId = '';
let roomName = '';
let oppId = '';

let gameState = {
  phase: 'lobby',     // lobby | waiting | playing | ended
  myHand: [],
  myIsOya: false,
  myPoints: 150000,
  oppPoints: 150000,
  myRiichi: false,
  oppRiichi: false,
  myKawa: [],          // [{card, isRiichi}]
  oppKawa: [],
  myFuuro: [],         // [["1s","1s","1s","1s"], ...]
  oppFuuro: [],
  currentPlayer: null,
  turnStage: null,     // 'before_draw' | 'after_draw' | 'after_discard'
  selectedIdx: null,
  wallCount: 36,
  kyoutaku: 0,
};

// === DOM refs ===
const $ = (id) => document.getElementById(id);

// === Lobby ===
$('btn-connect').addEventListener('click', connect);
$('input-room').addEventListener('keydown', (e) => { if (e.key === 'Enter') connect(); });
$('input-player').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') $('input-room').focus();
});

function connect() {
  myId = $('input-player').value.trim();
  roomName = $('input-room').value.trim();
  if (!myId || !roomName) {
    $('lobby-status').textContent = 'Please enter both fields.';
    return;
  }

  $('lobby-status').textContent = 'Connecting...';
  $('btn-connect').disabled = true;

  const host = window.location.hostname || '127.0.0.1';
  const port = window.location.port || '8000';
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${protocol}://${host}:${port}/ws/${roomName}/${myId}`);

  ws.onopen = () => {
    $('lobby').style.display = 'none';
    $('game').style.display = 'flex';
    $('my-name').textContent = myId;
    gameState.phase = 'waiting';
    logMsg('Connected to room: ' + roomName, 'broadcast');
    updateUI();
  };

  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    handleMessage(data);
  };

  ws.onclose = (event) => {
    if (event.code === 1003) {
      const reason = event.reason === 'room_full'
        ? 'Room is full!'
        : event.reason === 'duplicate_id'
        ? 'Name already taken in this room.'
        : 'Connection refused.';
      $('lobby-status').textContent = reason;
      $('btn-connect').disabled = false;
      $('lobby').style.display = '';
      $('game').style.display = 'none';
    } else {
      logMsg('Disconnected from server.', 'error');
    }
  };

  ws.onerror = () => {
    $('lobby-status').textContent = 'Connection failed.';
    $('btn-connect').disabled = false;
  };
}

// === Message handling ===
function handleMessage(data) {
  if (data.broadcast) {
    logMsg(data.message, 'broadcast');
    // Detect opponent name from join message
    const joinMatch = data.message.match(/^(\S+) joins/);
    const hostMatch = data.message.match(/Host is (\S+)/);
    if (joinMatch && joinMatch[1] !== myId) oppId = joinMatch[1];
    if (hostMatch && hostMatch[1] !== myId) oppId = hostMatch[1];
    if (oppId) $('opp-name').textContent = oppId;
    return;
  }

  const action = data.action;
  const actorId = data.player_id;

  // Update kawa/fuuro from public info
  if (data.kawa) {
    for (const [pid, kawa] of Object.entries(data.kawa)) {
      const parsed = kawa.map(([card, isRiichi]) => ({ card, isRiichi }));
      if (pid === myId) gameState.myKawa = parsed;
      else { gameState.oppKawa = parsed; oppId = pid; }
    }
  }
  if (data.fuuro) {
    for (const [pid, fuuro] of Object.entries(data.fuuro)) {
      if (pid === myId) gameState.myFuuro = fuuro;
      else { gameState.oppFuuro = fuuro; oppId = pid; }
    }
  }

  // Update hand if provided
  if (data.hand) {
    gameState.myHand = data.hand;
  }

  // Update oya
  if (data.is_oya !== undefined) {
    gameState.myIsOya = data.is_oya;
  }

  // Error messages
  if (data.message && data.message !== 'ok') {
    logMsg(`[${action}] ${data.message}`, 'error');
  }

  // Process actions
  if (action === 'start' || action === 'start_new') {
    gameState.phase = 'playing';
    gameState.myRiichi = false;
    gameState.oppRiichi = false;
    gameState.selectedIdx = null;
    gameState.wallCount = 36 - 27; // 36 total - 13 - 14 dealt

    // Oya starts in after_draw (has 14 cards)
    if (gameState.myIsOya) {
      gameState.currentPlayer = myId;
      gameState.turnStage = 'after_draw';
    } else {
      gameState.currentPlayer = oppId;
      gameState.turnStage = 'after_draw';
    }
    logMsg('Game started!', 'broadcast');
  }

  if (action === 'draw') {
    gameState.turnStage = 'after_draw';
    gameState.currentPlayer = actorId;
    gameState.wallCount--;
    gameState.selectedIdx = null;
  }

  if (action === 'discard') {
    gameState.selectedIdx = null;
    if (actorId === myId) {
      // I discarded, opponent's turn to ron/skip
      gameState.turnStage = 'after_discard';
      gameState.currentPlayer = oppId;
    } else {
      // Opponent discarded, my turn to ron/skip
      gameState.turnStage = 'after_discard';
      gameState.currentPlayer = myId;
    }
  }

  if (action === 'riichi') {
    gameState.selectedIdx = null;
    if (actorId === myId) {
      gameState.myRiichi = true;
      gameState.turnStage = 'after_discard';
      gameState.currentPlayer = oppId;
    } else {
      gameState.oppRiichi = true;
      gameState.turnStage = 'after_discard';
      gameState.currentPlayer = myId;
    }
  }

  if (action === 'kan') {
    // After kan, same player draws rinshan and stays in after_draw
    gameState.turnStage = 'after_draw';
    gameState.currentPlayer = actorId;
    gameState.wallCount--;
    gameState.selectedIdx = null;
  }

  if (action === 'skip_ron') {
    // Move to next player's before_draw
    if (actorId === myId) {
      gameState.currentPlayer = myId;
      gameState.turnStage = 'before_draw';
    } else {
      gameState.currentPlayer = oppId;
      gameState.turnStage = 'before_draw';
    }
    // Handle riichi kyoutaku
    if (data.kawa) {
      // Already updated above
    }
  }

  // Agari result
  if (data.agari !== undefined) {
    gameState.phase = 'ended';
    showAgariResult(data, actorId);
  }

  if (oppId) $('opp-name').textContent = oppId;
  updateUI();
}

// === Actions ===
function sendAction(action, cardIdx) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  ws.send(JSON.stringify({
    action: action,
    card_idx: cardIdx !== undefined && cardIdx !== null ? String(cardIdx) : '',
  }));
}

$('btn-start').addEventListener('click', () => sendAction('start'));
$('btn-draw').addEventListener('click', () => sendAction('draw'));
$('btn-tsumo').addEventListener('click', () => sendAction('tsumo'));
$('btn-ron').addEventListener('click', () => sendAction('ron'));
$('btn-skip').addEventListener('click', () => sendAction('skip_ron'));

$('btn-riichi').addEventListener('click', () => {
  if (gameState.selectedIdx !== null) {
    sendAction('riichi', gameState.selectedIdx);
    gameState.selectedIdx = null;
  }
});

$('btn-kan').addEventListener('click', () => {
  if (gameState.selectedIdx !== null) {
    sendAction('kan', gameState.selectedIdx);
    gameState.selectedIdx = null;
  }
});

$('btn-new-game').addEventListener('click', () => {
  $('agari-overlay').style.display = 'none';
  sendAction('start_new');
});

// Log toggle
$('log-toggle').addEventListener('click', () => {
  $('log-content').classList.toggle('open');
  $('log-toggle').textContent = $('log-content').classList.contains('open') ? 'Log ▼' : 'Log ▲';
});

// === Tile creation ===
// rotation: 0=normal, 1=left90 (chii/kan/pon), 2=flip180 (opp reveal), 3=right90 (opp meld)
function createTile(card, opts = {}) {
  const tile = document.createElement('div');
  tile.className = 'tile';

  const img = document.createElement('img');
  img.draggable = false;

  if (opts.back) {
    const backSuffix = opts.rotation || 0;
    img.src = `/assets/back_${backSuffix}.png`;
    img.alt = 'back';
    tile.classList.add('tile-back');
  } else {
    const suffix = opts.rotation || 0;
    img.src = `/assets/${card}_${suffix}.png`;
    img.alt = card;
  }
  tile.appendChild(img);

  if (opts.riichi) tile.classList.add('riichi-discard');
  if (opts.tsumo) tile.classList.add('tsumo-tile');

  if (opts.clickable) {
    tile.addEventListener('click', () => {
      if (opts.onSelect) opts.onSelect(opts.idx);
    });
  }

  if (opts.selected) tile.classList.add('selected');

  return tile;
}

// === UI Update ===
function updateUI() {
  const s = gameState;
  const isMyTurn = s.currentPlayer === myId;

  // Points
  $('my-points').textContent = s.myPoints.toLocaleString();
  $('opp-points').textContent = s.oppPoints.toLocaleString();

  // Oya badges
  $('my-oya-badge').style.display = s.phase === 'playing' && s.myIsOya ? '' : 'none';
  $('opp-oya-badge').style.display = s.phase === 'playing' && !s.myIsOya ? '' : 'none';

  // Riichi badges
  $('my-riichi-badge').style.display = s.myRiichi ? '' : 'none';
  $('opp-riichi-badge').style.display = s.oppRiichi ? '' : 'none';

  // My hand
  const myHandEl = $('my-hand');
  myHandEl.innerHTML = '';
  s.myHand.forEach((card, idx) => {
    const isTsumo = idx === s.myHand.length - 1 && s.myHand.length % 3 === 2
      && s.turnStage === 'after_draw' && isMyTurn;
    const canClick = s.phase === 'playing' && isMyTurn && s.turnStage === 'after_draw';
    const tile = createTile(card, {
      idx,
      tsumo: isTsumo,
      clickable: canClick,
      selected: s.selectedIdx === idx,
      onSelect: (i) => {
        if (s.selectedIdx === i) {
          // Double click = discard
          sendAction('discard', i);
          s.selectedIdx = null;
        } else {
          s.selectedIdx = i;
          updateUI();
        }
      },
    });
    myHandEl.appendChild(tile);
  });

  // Opponent hand (face down)
  const oppHandEl = $('opp-hand');
  oppHandEl.innerHTML = '';
  // Estimate opponent hand size
  const oppHandSize = estimateOppHandSize();
  for (let i = 0; i < oppHandSize; i++) {
    oppHandEl.appendChild(createTile(null, { back: true }));
  }

  // My kawa
  renderKawa($('my-kawa'), s.myKawa);
  renderKawa($('opp-kawa'), s.oppKawa);

  // Fuuro
  renderFuuro($('my-fuuro'), s.myFuuro);
  renderFuuro($('opp-fuuro'), s.oppFuuro);

  // Center info
  $('wall-count').textContent = `Wall: ${s.wallCount}`;
  $('kyoutaku-info').textContent = s.kyoutaku > 0 ? `Riichi sticks: ${s.kyoutaku}` : '';

  // Turn indicator
  if (s.phase === 'waiting') {
    $('turn-indicator').textContent = 'Waiting for opponent...';
  } else if (s.phase === 'playing') {
    if (isMyTurn) {
      if (s.turnStage === 'before_draw') $('turn-indicator').textContent = 'Your turn — Draw a tile';
      else if (s.turnStage === 'after_draw') $('turn-indicator').textContent = 'Your turn — Select & discard';
      else if (s.turnStage === 'after_discard') $('turn-indicator').textContent = 'Opponent discarded — Ron or Skip?';
    } else {
      $('turn-indicator').textContent = "Opponent's turn...";
    }
  } else if (s.phase === 'ended') {
    $('turn-indicator').textContent = 'Round ended';
  }

  // Action buttons
  updateActionButtons();
}

function updateActionButtons() {
  const s = gameState;
  const isMyTurn = s.currentPlayer === myId;

  // Hide all first
  $('btn-start').style.display = 'none';
  $('btn-draw').style.display = 'none';
  $('btn-riichi').style.display = 'none';
  $('btn-tsumo').style.display = 'none';
  $('btn-ron').style.display = 'none';
  $('btn-skip').style.display = 'none';
  $('btn-kan').style.display = 'none';

  if (s.phase === 'waiting' || s.phase === 'ended') {
    $('btn-start').style.display = '';
    return;
  }

  if (s.phase !== 'playing') return;

  if (isMyTurn && s.turnStage === 'before_draw') {
    $('btn-draw').style.display = '';
  }

  if (isMyTurn && s.turnStage === 'after_draw') {
    $('btn-tsumo').style.display = '';
    if (!s.myRiichi) {
      $('btn-riichi').style.display = '';
      $('btn-kan').style.display = '';
    }
    // When riichi, only tsumo or auto-discard (tsumo tile)
  }

  if (isMyTurn && s.turnStage === 'after_discard') {
    $('btn-ron').style.display = '';
    $('btn-skip').style.display = '';
  }
}

function estimateOppHandSize() {
  const s = gameState;
  if (s.phase !== 'playing' && s.phase !== 'ended') return 0;
  // Base: 13 cards - kan*3 melds removed + possible tsumo card
  const oppKanCount = s.oppFuuro.length;
  let base = 13 - oppKanCount * 3;
  // If it's opponent's turn and after_draw, they have +1
  if (s.currentPlayer === oppId && s.turnStage === 'after_draw') base++;
  return Math.max(0, base);
}

function renderKawa(el, kawa) {
  el.innerHTML = '';
  kawa.forEach(({ card, isRiichi }) => {
    el.appendChild(createTile(card, { riichi: isRiichi }));
  });
}

function renderFuuro(el, fuuro) {
  el.innerHTML = '';
  fuuro.forEach((meld) => {
    const group = document.createElement('div');
    group.className = 'meld-group';
    meld.forEach((card) => {
      group.appendChild(createTile(card));
    });
    el.appendChild(group);
  });
}

// === Agari overlay ===
function showAgariResult(data, actorId) {
  const overlay = $('agari-overlay');
  const title = $('agari-title');
  const details = $('agari-details');

  overlay.style.display = 'flex';

  if (data.agari) {
    const isMe = actorId === myId;
    const action = data.action;
    const winType = action === 'tsumo' ? 'Tsumo' : 'Ron';

    title.innerHTML = isMe
      ? `<span class="agari-win">${winType}! You Win!</span>`
      : `<span class="agari-lose">${winType} — You Lose</span>`;

    const yakuHtml = data.yaku
      ? data.yaku.map(y => `<span class="yaku-list">${y}</span>`).join(', ')
      : '';

    // Show the winner's hand if it's the opponent
    let handHtml = '';
    if (!isMe && data.hand) {
      handHtml = '<div class="agari-hand">' +
        data.hand.map(c => `<img class="agari-tile" src="/assets/${c}_2.png" alt="${c}">`).join('') +
        '</div>';
    } else if (isMe) {
      handHtml = '<div class="agari-hand">' +
        gameState.myHand.map(c => `<img class="agari-tile" src="/assets/${c}_0.png" alt="${c}">`).join('') +
        '</div>';
    }

    details.innerHTML = `
      ${handHtml}
      <div>${data.han} Han / ${data.fu} Fu</div>
      <div class="point-val">${data.point.toLocaleString()} pts</div>
      <div>${yakuHtml}</div>
    `;

    // Update points
    if (isMe) {
      gameState.myPoints += data.point;
      gameState.oppPoints -= data.point;
    } else {
      gameState.oppPoints += data.point;
      gameState.myPoints -= data.point;
    }
  } else {
    // Failed agari (no yaku or invalid)
    const isMe = actorId === myId;
    title.innerHTML = `<span class="agari-fail">No Agari</span>`;
    details.innerHTML = `
      <div>${isMe ? 'You' : 'Opponent'} declared but had no valid hand.</div>
      <div class="point-val" style="color:var(--danger)">${Math.abs(data.point).toLocaleString()} pts penalty</div>
    `;
    if (isMe) {
      gameState.myPoints += data.point; // negative
      gameState.oppPoints -= data.point;
    } else {
      gameState.oppPoints += data.point;
      gameState.myPoints -= data.point;
    }
  }

  // Update displayed points
  $('my-points').textContent = gameState.myPoints.toLocaleString();
  $('opp-points').textContent = gameState.oppPoints.toLocaleString();
}

// === Logging ===
function logMsg(text, type = '') {
  const el = document.createElement('div');
  el.className = 'log-entry ' + type;
  el.textContent = text;
  $('log-content').appendChild(el);
  $('log-content').scrollTop = $('log-content').scrollHeight;
}

// === Auto-discard for riichi ===
// When in riichi and it's after_draw, auto-discard the drawn tile (last card)
// Actually, the player should still click tsumo or discard. But in riichi,
// they can only discard the drawn tile (last card). Let's handle that:
// We let the player click the tsumo tile or press tsumo/discard.

// === Keyboard shortcuts ===
document.addEventListener('keydown', (e) => {
  if (gameState.phase !== 'playing') return;
  const isMyTurn = gameState.currentPlayer === myId;

  if (e.key === 'd' && isMyTurn && gameState.turnStage === 'before_draw') {
    sendAction('draw');
  }
  if (e.key === 't' && isMyTurn && gameState.turnStage === 'after_draw') {
    sendAction('tsumo');
  }
  if (e.key === 'r' && isMyTurn && gameState.turnStage === 'after_discard') {
    sendAction('ron');
  }
  if (e.key === 's' && isMyTurn && gameState.turnStage === 'after_discard') {
    sendAction('skip_ron');
  }
  if (e.key === 'Escape') {
    gameState.selectedIdx = null;
    updateUI();
  }
});
