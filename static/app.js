document.addEventListener('DOMContentLoaded', () => {
    // Hidden Debug: Triple-click logo to clear Cloud Cache
    let logoCount = 0;
    const logoEl = document.querySelector('.logo');
    if (logoEl) {
        logoEl.addEventListener('click', async () => {
            logoCount++;
            if (logoCount >= 3) {
                logoCount = 0;
                if (confirm("Vider le Cache Cloud pour forcer une nouvelle analyse ?")) {
                    await fetch('/api/matches?force_refresh=true');
                    window.location.reload();
                }
            }
            setTimeout(() => { logoCount = 0; }, 2000);
        });
    }

    // DOM Elements
    const fetchBtn = document.getElementById('fetchMatchesBtn');
    const runBtn = document.getElementById('runCouncilBtn');
    const matchesList = document.getElementById('matchesList');
    const statResponse = document.getElementById('statResponse');
    const expertResponse = document.getElementById('expertResponse');
    const pessimistResponse = document.getElementById('pessimistResponse');
    const trendResponse = document.getElementById('trendResponse');
    const bookieDebate = document.getElementById('bookieDebate');
    const togglePersonasBtn = document.getElementById('togglePersonasBtn');
    const personasGrid = document.getElementById('personasGrid');
    const chatDialogue = document.getElementById('chatDialogue');
    const categoryFilters = document.querySelectorAll('.filter-btn');

    // Bankroll & Stats UI
    const bankrollValue = document.getElementById('bankroll-value');
    const roiBadge = document.getElementById('roi-badge');
    const statTotalBets = document.getElementById('stat-total-bets');
    const statWinRate = document.getElementById('stat-win-rate');
    const statTotalStaked = document.getElementById('stat-total-staked');
    const statNetProfit = document.getElementById('stat-net-profit');
    const historyList = document.getElementById('history-list');

    // Bankroll Modal
    const bankrollModal = document.getElementById('bankrollModal');
    const configBtn = document.getElementById('config-bankroll-btn');
    const saveBankrollBtn = document.getElementById('saveBankrollBtn');
    const closeBankrollBtn = document.getElementById('closeBankrollBtn');
    const bankrollInput = document.getElementById('bankrollInput');

    // Security
    const overlay = document.getElementById('securityOverlay');
    const passInput = document.getElementById('passphraseInput');
    const unlockBtn = document.getElementById('unlockBtn');
    const secError = document.getElementById('securityError');

    unlockBtn.addEventListener('click', () => {
        if (passInput.value.toLowerCase() === 'parions') {
            overlay.style.display = 'none';
        } else {
            secError.style.display = 'block';
        }
    });

    let currentMatches = [];
    let currentFilter = 'all';
    let aiPredictions = {};

    // Toggle analysis visibility
    togglePersonasBtn.addEventListener('click', () => {
        if (personasGrid.style.display === 'none') {
            personasGrid.style.display = 'grid';
            togglePersonasBtn.innerText = '👁️ Masquer l\'analyse';
        } else {
            personasGrid.style.display = 'none';
            togglePersonasBtn.innerText = '👁️ Afficher l\'analyse';
        }
    });

    // Filter Logic
    categoryFilters.forEach(btn => {
        btn.addEventListener('click', () => {
            if (!btn.dataset.sport) return;
            categoryFilters.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentFilter = btn.dataset.sport;
            renderMatches(currentMatches);
        });
    });

    // --- Core Logic ---

    async function initMatches() {
        try {
            const response = await fetch('/api/matches');
            const data = await response.json();
            if (data.matches && data.matches.length > 0) {
                currentMatches = data.matches;
                renderMatches(currentMatches);
                runBtn.disabled = false;
            }
        } catch (e) { console.error("Auto-load failed", e); }
        
        loadBankrollStats();
        loadDailyBrief();
    }

    async function loadDailyBrief() {
        const briefContent = document.getElementById('dailyBriefContent');
        try {
            const res = await fetch('/api/journal/brief');
            const data = await res.json();
            if (data.text) {
                briefContent.innerHTML = formatMarkdown(data.text);
                briefContent.classList.remove('empty-state');
            }
        } catch (e) { console.error("Daily brief load fail", e); }
    }

    // --- Triple Ticket Strategy ---

    function renderTripleTickets(tickets) {
        const categories = ['safe', 'balanced', 'risky'];
        categories.forEach(cat => {
            const ticket = tickets[cat];
            const listEl = document.getElementById(`${cat}-list`);
            const oddsEl = document.getElementById(`${cat}-odds`);
            const stakeEl = document.getElementById(`${cat}-stake`);
            const btn = document.getElementById(`btn-play-${cat}`);

            if (!ticket || !ticket.selections) {
                listEl.innerHTML = '<div style="opacity: 0.5;">Analyses insuffisantes.</div>';
                return;
            }

            oddsEl.innerText = `x ${ticket.total_odds.toFixed(2)}`;
            stakeEl.innerText = `${ticket.suggested_stake.toFixed(2)}€`;
            
            listEl.innerHTML = ticket.selections.map(sel => `
                <div class="mini-selection">
                    <span class="m-name">${sel.match || sel.match_name}</span>
                    <span class="m-bet">${sel.bet || sel.prediction}</span>
                    <span class="m-odd">@ ${sel.odds.toFixed(2)}</span>
                </div>
            `).join('');

            btn.disabled = false;
            btn.onclick = () => playBet(cat, ticket);
        });
    }

    async function playBet(type, ticket) {
        if (!confirm(`Confirmer le placement du ticket ${type.toUpperCase()} pour ${ticket.suggested_stake.toFixed(2)}€ ?`)) return;
        try {
            const response = await fetch('/api/bet/play', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    type: type,
                    selections: ticket.selections,
                    total_odds: ticket.total_odds,
                    stake: ticket.suggested_stake
                })
            });

            if (!response.ok) {
                const errData = await response.json().catch(() => ({ detail: "Réponse non-JSON du serveur (Possible 404)" }));
                alert(`❌ Erreur ${response.status}: ${errData.detail || response.statusText}`);
                return;
            }

            const res = await response.json();
            if (res.status === 'success') {
                alert("✅ Pari enregistré !");
                updateStatsUI(res.stats);
                loadHistory();
            }
        } catch (e) {
            console.error("Bet placement error:", e);
            alert(`Erreur technique : ${e.message}\nAssurez-vous que main.py et persistence.py sont à jour sur GitHub.`);
        }
    }

    // --- Bankroll & Stats ---

    async function loadBankrollStats() {
        try {
            const res = await fetch('/api/bankroll/stats');
            const stats = await res.json();
            updateStatsUI(stats);
            loadHistory();
        } catch (e) { console.error("Stats load failed", e); }
    }

    function updateStatsUI(stats) {
        if (!stats) return;
        const bal = typeof stats.balance === 'number' ? stats.balance : (typeof stats.current_balance === 'number' ? stats.current_balance : 0);
        const roi = typeof stats.roi === 'number' ? stats.roi : 0;
        const profit = typeof stats.net_profit === 'number' ? stats.net_profit : 0;
        const staked = typeof stats.total_staked === 'number' ? stats.total_staked : 0;

        bankrollValue.innerText = `${bal.toFixed(2)}€`;
        roiBadge.innerText = `ROI: ${roi >= 0 ? '+' : ''}${roi}%`;
        roiBadge.style.color = roi >= 0 ? '#10b981' : '#ef4444';
        
        statTotalBets.innerText = stats.total_bets || 0;
        statWinRate.innerText = `${stats.win_rate || 0}%`;
        statTotalStaked.innerText = `${staked.toFixed(2)}€`;
        statNetProfit.innerText = `${profit.toFixed(2)}€`;
        statNetProfit.style.color = profit >= 0 ? '#10b981' : '#ef4444';

        // Update strategy stats if they exist
        if (stats.by_strategy) {
            if (document.getElementById('stat-safe-roi')) document.getElementById('stat-safe-roi').innerText = `ROI: ${stats.by_strategy.safe?.profit >= 0 ? '+' : ''}${stats.by_strategy.safe?.profit.toFixed(2)}€`;
            if (document.getElementById('stat-balanced-roi')) document.getElementById('stat-balanced-roi').innerText = `ROI: ${stats.by_strategy.balanced?.profit >= 0 ? '+' : ''}${stats.by_strategy.balanced?.profit.toFixed(2)}€`;
            if (document.getElementById('stat-risky-roi')) document.getElementById('stat-risky-roi').innerText = `ROI: ${stats.by_strategy.risky?.profit >= 0 ? '+' : ''}${stats.by_strategy.risky?.profit.toFixed(2)}€`;
        }
    }

    async function loadHistory() {
        try {
            const res = await fetch('/api/bankroll');
            const db = await res.json();
            renderHistory(db.history || []);
        } catch (e) { console.error("History load failed", e); }
    }

    function renderHistory(history) {
        if (!history || history.length === 0) {
            historyList.innerHTML = '<div style="text-align: center; color: #94a3b8; padding: 2rem;">Aucun pari enregistré.</div>';
            return;
        }

        historyList.innerHTML = history.slice().reverse().map(bet => {
            const date = new Date(bet.timestamp * 1000).toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
            const sClass = `status-${bet.status.toLowerCase()}`;
            
            let actionHtml = '';
            if (bet.status === 'PENDING') {
                actionHtml = `
                    <div style="display: flex; gap: 0.5rem; margin-top: 0.5rem;">
                        <button class="btn cta btn-result" onclick="event.stopPropagation(); settleBet('${bet.id}', 'WON')" style="padding: 0.3rem 0.6rem; font-size: 0.7rem;">Gagné</button>
                        <button class="btn primary btn-result" onclick="event.stopPropagation(); settleBet('${bet.id}', 'LOST')" style="padding: 0.3rem 0.6rem; font-size: 0.7rem; background: #ef4444;">Perdu</button>
                    </div>
                `;
            }

            const selectionsHtml = (bet.selections || []).map(sel => `
                <div style="padding: 0.4rem; border-bottom: 1px solid rgba(255,255,255,0.05); font-size: 0.8rem;">
                    <div style="font-weight: bold; color: #e2e8f0;">${sel.match || sel.match_name}</div>
                    <div style="display: flex; justify-content: space-between; opacity: 0.8;">
                        <span>Pari: ${sel.bet || sel.prediction}</span>
                        <span>@ ${sel.odds?.toFixed(2) || '1.00'}</span>
                    </div>
                </div>
            `).join('');

            return `
                <div class="history-item" onclick="this.classList.toggle('expanded')" style="cursor: pointer; display: block; padding-bottom: 0.5rem;">
                    <div style="display: flex; justify-content: space-between; align-items: flex-start; width: 100%;">
                        <div class="history-main">
                            <span class="history-date">${date}</span>
                            <span class="history-type" style="color: ${bet.type === 'safe' ? '#10b981' : bet.type === 'balanced' ? '#3b82f6' : '#f59e0b'}">${bet.type.toUpperCase()} (${bet.total_odds.toFixed(2)})</span>
                            <span style="font-size: 0.8rem; opacity: 0.7; display: block;">${bet.selections.length} sélections • Stake: ${bet.stake.toFixed(2)}€</span>
                        </div>
                        <div style="display: flex; flex-direction: column; align-items: flex-end; gap: 0.2rem;">
                            <span class="history-profit ${sClass}">${bet.status === 'WON' ? '+' + bet.potential_gain.toFixed(2) + '€' : bet.status === 'LOST' ? '-' + bet.stake.toFixed(2) + '€' : bet.status}</span>
                            ${actionHtml}
                        </div>
                    </div>
                    <div class="history-details" style="display: none; margin-top: 1rem; background: rgba(0,0,0,0.2); border-radius: 8px; border: 1px solid rgba(255,255,255,0.05); overflow: hidden;">
                        <div style="padding: 0.5rem; background: rgba(255,255,255,0.05); font-size: 0.7rem; font-weight: bold; text-transform: uppercase; color: #94a3b8;">Détails de la Sélection</div>
                        ${selectionsHtml}
                    </div>
                    <div class="expand-hint" style="text-align: center; font-size: 0.6rem; opacity: 0.3; margin-top: 0.4rem;">Cliquez pour voir les matchs ⌄</div>
                </div>
            `;
        }).join('');
    }

    window.settleBet = async (betId, result) => {
        try {
            const response = await fetch('/api/bet/result', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ bet_id: betId, result: result })
            });
            if (response.ok) loadBankrollStats();
        } catch (e) { alert("Erreur lors de la validation."); }
    };

    // --- Match Rendering ---

    function renderMatches(matches) {
        matchesList.innerHTML = '';
        const filtered = currentFilter === 'all' ? matches : matches.filter(m => {
            const s = m.sport.toLowerCase();
            const c = (m.competition || '').toLowerCase();
            if (currentFilter === 'football') return s.includes('football') || s.includes('soccer');
            if (currentFilter === 'rugby') return s.includes('rugby');
            if (currentFilter === 'basket') return s.includes('basket') || s.includes('nba');
            if (currentFilter === 'tennis') return s.includes('tennis');
            if (currentFilter === 'hockey') return s.includes('hockey');
            if (currentFilter === 'f1') return s.includes('f1') || s.includes('biathlon');
            return false;
        });

        if (filtered.length === 0) {
            matchesList.innerHTML = '<div class="empty-state">Aucun match trouvé.</div>';
            return;
        }

        filtered.forEach(match => {
            const div = document.createElement('div');
            div.className = 'match-item';
            let oddsHtml = '';
            ['1', 'N', '2'].forEach(k => {
                if (match.odds[k] && match.odds[k] !== "-") oddsHtml += `<div class="odd-btn">${k}: ${match.odds[k]}</div>`;
            });

            let predictionHtml = '';
            if (aiPredictions[match.id]) {
                const pred = aiPredictions[match.id];
                predictionHtml = `
                    <div class="ai-advice-bubble" style="margin-top: 0.8rem; padding: 0.8rem; background: rgba(139, 92, 246, 0.1); border-left: 4px solid #8b5cf6; border-radius: 8px;">
                        <div class="advice-header" style="font-weight: 800; color: #a78bfa; font-size: 0.75rem; margin-bottom: 0.3rem; text-transform: uppercase;">
                            🧠 Conseil IA : ${pred.bet} 
                            <span class="badge" style="background: #8b5cf6; padding: 2px 5px; border-radius: 4px; color: white; margin-left: 5px;">${pred.confidence}%</span>
                        </div>
                        <div class="advice-reason" style="font-style: italic; color: #cbd5e1; font-size: 0.85rem; line-height: 1.4;">
                            "${pred.reason}"
                        </div>
                    </div>
                `;
            }

            div.innerHTML = `
                <div class="match-card-content">
                    <div class="match-header">
                        <span class="m-comp">${match.sport} • ${match.competition}</span>
                        <span class="m-date">${formatDate(match.date)}</span>
                    </div>
                    <div class="match-teams">${match.homeTeam} vs ${match.awayTeam}</div>
                    <div class="match-odds">${oddsHtml}</div>
                    ${predictionHtml}
                </div>
            `;
            matchesList.appendChild(div);
        });
    }

    // --- Support ---

    function formatMarkdown(text) {
        if (!text) return "";
        return text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
                   .replace(/^\* (.*$)/gm, '<li>$1</li>')
                   .replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>');
    }

    function formatDate(dateStr) {
        if (!dateStr) return "";
        const d = new Date(dateStr);
        if (isNaN(d.getTime())) return dateStr; // Si invalide, on renvoie la string brute (ex: "Ce soir")
        return d.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
    }

    function addChatBubble(name, text) {
        const bubble = document.createElement('div');
        bubble.style.padding = '0.75rem';
        bubble.style.background = 'rgba(255,255,255,0.05)';
        bubble.style.borderRadius = '8px';
        bubble.innerHTML = `<strong>${name} :</strong> ${text}`;
        chatDialogue.appendChild(bubble);
    }

    // --- Event Listeners ---

    fetchBtn.addEventListener('click', async () => {
        fetchBtn.disabled = true;
        fetchBtn.innerText = '⏳ Récupération...';
        try {
            const response = await fetch('/api/matches?force_refresh=true');
            const data = await response.json();
            currentMatches = data.matches;
            renderMatches(currentMatches);
            fetchBtn.innerText = '✅ Matchs Récupérés';
            runBtn.disabled = false;
        } catch (error) { fetchBtn.innerText = '❌ Erreur'; fetchBtn.disabled = false; }
    });

    runBtn.addEventListener('click', async () => {
        runBtn.disabled = true;
        runBtn.innerText = '🧠 Analyse en cours...';
        chatDialogue.innerHTML = '';
        try {
            const response = await fetch('/api/council/full');
            const data = await response.json();
            if (data.error) throw new Error(data.error);

            statResponse.innerHTML = formatMarkdown(data.statistician);
            expertResponse.innerHTML = formatMarkdown(data.expert);
            pessimistResponse.innerHTML = formatMarkdown(data.pessimist);
            trendResponse.innerHTML = formatMarkdown(data.trend);

            if (data.predictions) {
                aiPredictions = data.predictions;
                renderMatches(currentMatches); // Update match items with advice
            }

            if (data.tickets) renderTripleTickets(data.tickets);
            runBtn.innerText = '✅ Analyses Complétées';
            runBtn.disabled = false;
        } catch (error) {
            runBtn.innerText = '🔄 Réessayer';
            runBtn.disabled = false;
            bookieDebate.innerHTML = `<div style="color: #ef4444;">❌ Erreur: ${error.message}</div>`;
        }
    });

    // Bankroll Config
    configBtn.addEventListener('click', () => {
        bankrollModal.style.display = 'flex';
    });
    closeBankrollBtn.addEventListener('click', () => {
        bankrollModal.style.display = 'none';
    });
    saveBankrollBtn.addEventListener('click', async () => {
        const amount = parseFloat(bankrollInput.value);
        if (isNaN(amount) || amount <= 0) return alert("Veuillez entrer un montant valide.");
        
        try {
            const res = await fetch('/api/bankroll/update', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ new_balance: amount })
            });
            if (res.ok) {
                alert("Capital mis à jour !");
                bankrollModal.style.display = 'none';
                loadBankrollStats();
            }
        } catch (e) { alert("Erreur lors de la mise à jour."); }
    });

    initMatches();
});
