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
        bankrollValue.innerText = `${stats.balance.toFixed(2)}€`;
        roiBadge.innerText = `ROI: ${stats.roi >= 0 ? '+' : ''}${stats.roi}%`;
        roiBadge.style.color = stats.roi >= 0 ? '#10b981' : '#ef4444';
        
        statTotalBets.innerText = stats.total_bets;
        statWinRate.innerText = `${stats.win_rate}%`;
        statTotalStaked.innerText = `${stats.total_staked.toFixed(2)}€`;
        statNetProfit.innerText = `${stats.net_profit.toFixed(2)}€`;
        statNetProfit.style.color = stats.net_profit >= 0 ? '#10b981' : '#ef4444';
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
                    <div style="display: flex; gap: 0.5rem;">
                        <button class="btn cta btn-result" onclick="settleBet('${bet.id}', 'WON')" style="padding: 0.3rem 0.6rem; font-size: 0.7rem;">Gagné</button>
                        <button class="btn primary btn-result" onclick="settleBet('${bet.id}', 'LOST')" style="padding: 0.3rem 0.6rem; font-size: 0.7rem; background: #ef4444;">Perdu</button>
                    </div>
                `;
            }

            return `
                <div class="history-item">
                    <div class="history-main">
                        <span class="history-date">${date}</span>
                        <span class="history-type" style="color: ${bet.type === 'safe' ? '#10b981' : bet.type === 'balanced' ? '#3b82f6' : '#f59e0b'}">${bet.type.toUpperCase()} (${bet.total_odds.toFixed(2)})</span>
                        <span style="font-size: 0.8rem; opacity: 0.7;">${bet.selections.length} sélections • Stake: ${bet.stake.toFixed(2)}€</span>
                    </div>
                    <div style="display: flex; flex-direction: column; align-items: flex-end; gap: 0.5rem;">
                        <span class="history-profit ${sClass}">${bet.status === 'WON' ? '+' + bet.potential_gain.toFixed(2) : bet.status === 'LOST' ? '-' + bet.stake.toFixed(2) : bet.status}</span>
                        ${actionHtml}
                    </div>
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
                    <div class="ai-advice-bubble" style="margin-top: 1rem; padding: 0.8rem; background: rgba(139, 92, 246, 0.1); border-left: 3px solid #8b5cf6; border-radius: 4px; font-size: 0.85rem;">
                        <div style="font-weight: bold; color: #a78bfa; display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.3rem;">
                            🧠 Conseil IA : ${pred.bet} 
                            <span class="badge" style="background: #8b5cf6; font-size: 0.7rem;">${pred.confidence}%</span>
                        </div>
                        <div style="opacity: 0.8; font-style: italic;">"${pred.reason}"</div>
                    </div>
                `;
            }

            div.innerHTML = `
                <div class="match-header">
                    <span>${match.sport} • ${match.competition}</span>
                    <span>${formatDate(match.date)}</span>
                </div>
                <div class="match-teams">${match.homeTeam} vs ${match.awayTeam}</div>
                <div class="match-odds">${oddsHtml}</div>
                ${predictionHtml}
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

            addChatBubble("📊 Statisticien", data.statistician);
            addChatBubble("🧠 Expert", data.expert);
            addChatBubble("👿 Avocat", data.pessimist);
            addChatBubble("📈 Réseauteur", data.trend);

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

    initMatches();
});
