document.addEventListener('DOMContentLoaded', () => {
    // DOM Elements
    const fetchBtn = document.getElementById('fetchMatchesBtn');
    const runBtn = document.getElementById('runCouncilBtn');
    const matchesList = document.getElementById('matchesList');
    const statResponse = document.getElementById('statResponse');
    const expertResponse = document.getElementById('expertResponse');
    const pessimistResponse = document.getElementById('pessimistResponse');
    const trendResponse = document.getElementById('trendResponse');
    const bookieDebate = document.getElementById('bookieDebate');
    const finalTicketList = document.getElementById('finalTicketList');
    const totalOddsValue = document.getElementById('totalOddsValue');
    const placeBetBtn = document.getElementById('placeBetBtn');
    const togglePersonasBtn = document.getElementById('togglePersonasBtn');
    const personasGrid = document.getElementById('personasGrid');
    const chatDialogue = document.getElementById('chatDialogue');
    const categoryFilters = document.querySelectorAll('.filter-btn');

    // Bankroll UI
    const bankrollValue = document.getElementById('bankroll-value');
    const roiValue = document.getElementById('roi-value');
    const historyList = document.getElementById('historyList');
    const configBankrollBtn = document.getElementById('config-bankroll-btn');
    const bankrollModal = document.getElementById('bankrollModal');
    const bankrollInput = document.getElementById('bankrollInput');
    const saveBankrollBtn = document.getElementById('saveBankrollBtn');
    const closeBankrollBtn = document.getElementById('closeBankrollBtn');

    let currentMatches = [];
    let currentFilter = 'all';

    // 0. Security Logic
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

    // Auto-load matches
    async function initMatches() {
        try {
            const response = await fetch('/api/matches');
            const data = await response.json();
            if (data.matches && data.matches.length > 0) {
                currentMatches = data.matches;
                renderMatches(currentMatches);
                runBtn.disabled = false;
            } else {
                runBtn.disabled = true;
            }
        } catch (e) {
            console.error("Auto-load failed", e);
            matchesList.innerHTML = '<div class="empty-state">⚠️ Échec auto-chargement. Cliquez sur "Importer".</div>';
        }

        // Wait for matches to load before requesting brief to avoid concurrent Gemini calls 
        // hitting the 1 Request Per Second limit on a cold start.
        await loadBankroll();
        await loadDailyBrief();
    }
    initMatches();

    async function loadDailyBrief() {
        const briefContent = document.getElementById('dailyBriefContent');
        try {
            const res = await fetch('/api/journal/brief');
            const data = await res.json();
            if (data.error) {
                briefContent.innerHTML = `<span style="color: #ef4444;">⚠️ Erreur Journal : ${data.error}</span>`;
            } else if (data.text) {
                briefContent.innerHTML = formatMarkdown(data.text);
                briefContent.classList.remove('empty-state');
                briefContent.style.fontStyle = 'normal';
                briefContent.style.textAlign = 'left';
            }
        } catch (e) {
            console.error("Daily brief load fail", e);
            briefContent.innerHTML = "Aucun briefing disponible.";
        }
    }

    // Bankroll Logic
    async function loadBankroll() {
        try {
            const res = await fetch('/api/bankroll');
            const db = await res.json();
            updateBankrollUI(db);
        } catch (e) { console.error("Load bankroll failed", e); }
    }

    function updateBankrollUI(db) {
        const { balance, initial_balance } = db.bankroll;
        bankrollValue.innerText = `${balance.toFixed(2)} €`;

        // Calculate ROI (protect against div by 0 and ensure initial_balance exists)
        const initial = initial_balance || balance;
        const diff = balance - initial;
        const roi = initial > 0 ? (diff / initial) * 100 : 0;

        roiValue.innerText = `${roi > 0 ? '+' : ''}${roi.toFixed(1)} %`;
        roiValue.style.color = roi >= 0 ? '#10b981' : '#ef4444';

        renderHistory(db.history);
    }

    function renderHistory(history) {
        if (!history || history.length === 0) {
            historyList.innerHTML = '<div class="empty-state">Aucun historique disponible.</div>';
            return;
        }
        historyList.innerHTML = '';
        history.forEach(t => {
            const div = document.createElement('div');
            div.className = `glass-panel history-item status-${t.status}`;
            div.style.padding = '1rem';
            div.style.borderLeft = `4px solid ${t.status === 'won' ? '#10b981' : (t.status === 'lost' ? '#ef4444' : '#64748b')}`;

            let actionHtml = '';
            if (t.status === 'pending') {
                actionHtml = `
                    <div style="display: flex; gap: 0.5rem; margin-top: 1rem;">
                        <button class="btn won-btn" style="background: #10b981; padding: 0.3rem 0.6rem; font-size: 0.7rem;" onclick="handleTicketAction('${t.id}', 'won')">Gagné</button>
                        <button class="btn lost-btn" style="background: #ef4444; padding: 0.3rem 0.6rem; font-size: 0.7rem;" onclick="handleTicketAction('${t.id}', 'lost')">Perdu</button>
                        <button class="btn" style="background: #334155; padding: 0.3rem 0.6rem; font-size: 0.7rem;" onclick="handleTicketAction('${t.id}', 'delete')">🗑️</button>
                    </div>
                `;
            } else {
                actionHtml = `<button class="btn" style="background: transparent; border: 1px solid #334155; padding: 0.3rem 0.6rem; font-size: 0.7rem; margin-top: 1rem;" onclick="handleTicketAction('${t.id}', 'delete')">Supprimer</button>`;
            }

            div.innerHTML = `
                <div style="font-size: 0.75rem; color: #94a3b8; margin-bottom: 0.5rem;">Ticket du ${new Date(t.created_at).toLocaleDateString()} - Stake: ${t.suggested_stake_value || 0} €</div>
                <div style="font-weight: bold; font-size: 0.9rem;">Cote Totale: x${t.total_odds}</div>
                <div style="font-size: 0.85rem; margin-top: 0.5rem;">${t.selections.map(s => `• ${s.match_name}: ${s.prediction}`).join('<br>')}</div>
                ${actionHtml}
            `;
            historyList.appendChild(div);
        });
    }

    window.handleTicketAction = async (id, action) => {
        try {
            const res = await fetch('/api/ticket/action', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ticket_id: id, action })
            });
            const db = await res.json();
            updateBankrollUI(db);
        } catch (e) { console.error("Ticket action failed", e); }
    };

    configBankrollBtn.addEventListener('click', () => {
        bankrollModal.style.display = 'flex';
    });

    closeBankrollBtn.addEventListener('click', () => {
        bankrollModal.style.display = 'none';
    });

    saveBankrollBtn.addEventListener('click', async () => {
        const val = parseFloat(bankrollInput.value);
        if (isNaN(val)) return;
        try {
            const res = await fetch('/api/bankroll/update', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ new_balance: val })
            });
            const db = await res.json();
            updateBankrollUI(db);
            bankrollModal.style.display = 'none';
        } catch (e) { console.error("Save bankroll failed", e); }
    });

    // 1. Fetch Matches
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
        } catch (error) {
            console.error(error);
            fetchBtn.innerText = '❌ Erreur';
            fetchBtn.disabled = false;
        }
    });

    // 2. Run Analysis
    runBtn.addEventListener('click', async () => {
        runBtn.disabled = true;
        runBtn.innerText = '🧠 Analyse en cours...';

        statResponse.innerHTML = 'Analyse statistique...';
        expertResponse.innerHTML = 'Recherche web...';
        pessimistResponse.innerHTML = 'Contre-arguments...';
        trendResponse.innerHTML = 'Tendances...';
        chatDialogue.innerHTML = '';

        try {
            // One single call for the entire council analysis (Phase 50)
            const response = await fetch('/api/council/full');
            const data = await response.json();

            if (data.error) {
                if (data.error === "QUOTA_EXHAUSTED" || data.error.includes("429")) {
                    throw new Error("QUOTA_EXHAUSTED");
                } else {
                    throw new Error(data.error);
                }
            }

            // Update all expert boxes at once
            const statText = data.statistician || "❌ Indisponible";
            statResponse.innerHTML = formatMarkdown(statText);
            addChatBubble("📊 Statisticien", statText);

            const expertText = data.expert || "❌ Indisponible";
            expertResponse.innerHTML = formatMarkdown(expertText);
            addChatBubble("🧠 Expert", expertText);

            const pessimistText = data.pessimist || "❌ Indisponible";
            pessimistResponse.innerHTML = formatMarkdown(pessimistText);
            addChatBubble("👿 Avocat du Diable", pessimistText);

            const trendText = data.trend || "❌ Indisponible";
            trendResponse.innerHTML = formatMarkdown(trendText);
            addChatBubble("📈 Réseauteur", trendText);

            // Update Ticket
            if (data.ticket) {
                renderTicket(data.ticket);
                runBtn.innerText = '✅ Analyse Terminée';
            } else {
                bookieDebate.innerHTML = "L'IA n'a pas pu générer de ticket exploitable.";
                runBtn.innerText = '⚠️ Terminée avec erreurs';
            }
            runBtn.disabled = false;

        } catch (error) {
            console.error("Analysis failed:", error);
            const isQuota = error.message === "QUOTA_EXHAUSTED";

            if (isQuota) {
                let timeLeft = 60;
                runBtn.disabled = true;
                const timer = setInterval(() => {
                    runBtn.innerText = `⏳ Quota IA. Attente : ${timeLeft}s`;
                    timeLeft -= 1;
                    if (timeLeft < 0) {
                        clearInterval(timer);
                        runBtn.innerText = '🔄 Relancer l\'Analyse';
                        runBtn.disabled = false;
                    }
                }, 1000);
                bookieDebate.innerHTML = '<div style="color: #ef4444; padding: 1rem; border: 1px dashed #ef4444; border-radius: 8px;">🛑 <strong>Quota Google Dépassé (429)</strong><br>Le moteur d\'analyse est saturé. Veuillez patienter 60 secondes environ avant de relancer l\'analyse.</div>';
            } else {
                runBtn.disabled = false;
                if (error.message && error.message.includes("Erreur IA")) {
                    runBtn.innerText = '❌ Clé API Invalide ou Erreur';
                    bookieDebate.innerHTML = `<div style="color: #ef4444; padding: 1rem; border: 1px dashed #ef4444; border-radius: 8px;">🛑 <strong>Erreur API Google</strong><br>${error.message}</div>`;
                } else {
                    runBtn.innerText = '🔄 Réessayer l\'Analyse';
                    bookieDebate.innerHTML = `<div style="color: #ef4444; padding: 1rem; border: 1px dashed #ef4444; border-radius: 8px;">❌ <strong>Erreur Technique</strong><br>${error.message || "Une erreur est survenue lors de l'analyse."}</div>`;
                }
            }
        }
    });

    function renderMatches(matches) {
        matchesList.innerHTML = '';
        const filtered = currentFilter === 'all'
            ? matches
            : matches.filter(m => {
                const s = m.sport.toLowerCase();
                const c = (m.competition || '').toLowerCase();
                if (currentFilter === 'football') return s.includes('football') || s.includes('soccer') || c.includes('champions league') || c.includes('uefa');
                if (currentFilter === 'rugby') return s.includes('rugby');
                if (currentFilter === 'basket') return s.includes('basket') || s.includes('nba');
                if (currentFilter === 'tennis') return s.includes('tennis');
                if (currentFilter === 'hockey') return s.includes('hockey');
                if (currentFilter === 'f1') return s.includes('f1') || s.includes('ski') || s.includes('biathlon') || s.includes('tour de france');
                if (currentFilter === 'other') return !['football', 'soccer', 'rugby', 'basket', 'nba', 'tennis', 'hockey', 'f1', 'ski'].some(str => s.includes(str));
                return s.includes(currentFilter);
            });

        if (filtered.length === 0) {
            matchesList.innerHTML = '<div class="empty-state">Aucun match trouvé.</div>';
            return;
        }

        filtered.forEach(match => {
            const div = document.createElement('div');
            div.className = 'match-item';

            let oddsHtml = '';
            if (match.odds["1"] && match.odds["1"] !== "-") oddsHtml += `<div class="odd-btn">1: ${match.odds["1"]}</div>`;
            if (match.odds["N"] && match.odds["N"] !== "-") oddsHtml += `<div class="odd-btn">N: ${match.odds["N"]}</div>`;
            if (match.odds["2"] && match.odds["2"] !== "-") oddsHtml += `<div class="odd-btn">2: ${match.odds["2"]}</div>`;

            let advHtml = '';
            if (match.odds["btts"] && match.odds["btts"] !== "-") advHtml += `<span class="adv-badge">BTTS: ${match.odds["btts"]}</span>`;
            if (match.odds["over25"] && match.odds["over25"] !== "-") advHtml += `<span class="adv-badge">+2.5: ${match.odds["over25"]}</span>`;

            div.innerHTML = `
                <div class="match-header">
                    <span class="sport-badge">${match.sport}</span>
                    ${match.isSurebet ? '<span class="surebet-badge">🔥 SUREBET</span>' : ''}
                    <span class="best-odds-badge">✨ Meilleure Cote</span>
                    <span>${match.competition}</span>
                    <span>${formatDate(match.date)}</span>
                </div>
                <div class="match-teams">${match.homeTeam} vs ${match.awayTeam}</div>
                <div class="match-odds">${oddsHtml}</div>
                <div class="match-advanced" style="margin-top: 0.5rem; display: flex; gap: 0.5rem; font-size: 0.8rem; color: #94a3b8;">${advHtml}</div>
            `;
            matchesList.appendChild(div);
        });
    }

    function renderTicket(data) {
        // The data now contains { main_ticket, safe_ticket, debate }
        const main = data.main_ticket;
        const safe = data.safe_ticket;
        const debate = data.debate;

        bookieDebate.innerHTML = formatMarkdown(debate);

        // Render Main Ticket
        totalOddsValue.innerText = `x ${main.total_odds}`;
        finalTicketList.innerHTML = '';

        if (main.suggested_stake_percent) {
            const stakeDiv = document.createElement('div');
            stakeDiv.style = "background: rgba(16, 185, 129, 0.1); border: 1px dashed #10b981; padding: 0.8rem; border-radius: 8px; margin-bottom: 1rem; color: #10b981; font-weight: bold; text-align: center;";
            stakeDiv.innerHTML = `💰 Mise suggérée : ${main.suggested_stake_percent} (${main.suggested_stake_value} €)`;
            finalTicketList.appendChild(stakeDiv);
        }

        renderSelections(main.selections, finalTicketList);

        // Render Safe Ticket
        const safeContainer = document.getElementById('safeTicketContainer');
        const safeList = document.getElementById('safeTicketList');
        const safeTotal = document.getElementById('safeTotalOdds');

        if (safe && safe.selections && safe.selections.length > 0) {
            safeContainer.style.display = 'block';
            safeTotal.innerText = `x ${safe.total_odds}`;
            safeList.innerHTML = '';
            renderSelections(safe.selections, safeList);
        } else {
            safeContainer.style.display = 'none';
        }

        // Save to history (main ticket is usually the priority for history)
        saveTicketToHistory(main);
        placeBetBtn.disabled = false;
    }

    function renderSelections(selections, container) {
        selections.forEach(item => {
            const div = document.createElement('div');
            div.className = 'ticket-item';
            div.innerHTML = `
                <div class="ticket-match">
                    <div class="ticket-match-name">
                        ${item.match_name} 
                        ${item.is_niche ? '<span class="niche-badge">NICHE</span>' : ''}
                    </div>
                    <div class="ticket-prediction">Pari : ${item.prediction} ${item.confidence ? `<span class="conf-pill">${item.confidence}</span>` : ''}</div>
                </div>
                <div class="ticket-odd">${item.odds}</div>
            `;
            container.appendChild(div);
        });
    }

    async function saveTicketToHistory(ticket) {
        try {
            await fetch('/api/ticket/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(ticket)
            });
            loadBankroll(); // Refresh history
        } catch (e) { console.error("Save ticket failed", e); }
    }

    function addChatBubble(name, text) {
        const bubble = document.createElement('div');
        bubble.style.padding = '0.75rem';
        bubble.style.background = 'rgba(255,255,255,0.05)';
        bubble.style.borderRadius = '8px';
        bubble.innerHTML = `<strong>${name} :</strong> ${text}`;
        chatDialogue.appendChild(bubble);
    }

    function formatMarkdown(text) {
        if (!text) return "";
        let html = text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
        html = html.replace(/^\* (.*$)/gm, '<li>$1</li>');
        html = html.replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>');
        return html;
    }

    function formatDate(dateStr) {
        if (!dateStr) return "";
        const date = new Date(dateStr);
        return date.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
    }

    placeBetBtn.addEventListener('click', () => {
        window.open('https://www.enligne.parionssport.fdj.fr/', '_blank');
    });
});
