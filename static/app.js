document.addEventListener('DOMContentLoaded', () => {
    const fetchBtn = document.getElementById('fetchMatchesBtn');
    const runBtn = document.getElementById('runCouncilBtn');
    const matchesList = document.getElementById('matchesList');

    const statResponse = document.getElementById('statResponse');
    const expertResponse = document.getElementById('expertResponse');
    const pessimistResponse = document.getElementById('pessimistResponse');
    const trendResponse = document.getElementById('trendResponse');

    const bookieDebate = document.getElementById('bookieDebate');
    const totalOddsValue = document.getElementById('totalOddsValue');
    const finalTicketList = document.getElementById('finalTicketList');
    const placeBetBtn = document.getElementById('placeBetBtn');

    // UI Toggle
    const togglePersonasBtn = document.getElementById('togglePersonasBtn');
    const personasGrid = document.getElementById('personasGrid');

    let personasVisible = true;
    togglePersonasBtn.addEventListener('click', () => {
        personasVisible = !personasVisible;
        if (personasVisible) {
            personasGrid.style.display = 'grid';
            togglePersonasBtn.innerText = '👁️ Masquer les avis';
        } else {
            personasGrid.style.display = 'none';
            togglePersonasBtn.innerText = '👁️ Afficher les avis';
        }
    });

    // Security Overlay
    const securityOverlay = document.getElementById('securityOverlay');
    const passphraseInput = document.getElementById('passphraseInput');
    const unlockBtn = document.getElementById('unlockBtn');
    const securityError = document.getElementById('securityError');

    function formatMarkdown(text) {
        if (!text) return "";
        let formatted = text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
        formatted = formatted.replace(/- (.*?)(?=\n|$)/g, '<li>$1</li>');
        if (formatted.includes('<li>')) {
            formatted = formatted.replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>');
        }
        return formatted.replace(/\n/g, '<br/>');
    }

    unlockBtn.addEventListener('click', () => {
        if (passphraseInput.value.toLowerCase() === 'parions') {
            securityOverlay.style.display = 'none';
        } else {
            securityError.style.display = 'block';
        }
    });

    let currentMatches = [];
    let currentFilter = 'all';

    // Category Filters Logic
    const filterBtns = document.querySelectorAll('.filter-btn');
    filterBtns.forEach(btn => {
        btn.addEventListener('click', (e) => {
            filterBtns.forEach(b => b.classList.remove('active'));
            e.target.classList.add('active');
            currentFilter = e.target.dataset.sport;
            renderMatches(currentMatches);
        });
    });

    // Auto-load matches if already cached on server
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
    }
    initMatches();

    // 1. Fetch Matches from Backend
    fetchBtn.addEventListener('click', async () => {
        fetchBtn.disabled = true;
        fetchBtn.innerText = '⏳ Récupération en cours...';

        try {
            const response = await fetch('/api/matches?force_refresh=true');
            const data = await response.json();
            currentMatches = data.matches;

            renderMatches(currentMatches);

            fetchBtn.innerText = '✅ Matchs Récupérés';
            runBtn.disabled = false; // Enable step 2

        } catch (error) {
            console.error("Error fetching matches:", error);
            fetchBtn.innerText = '❌ Erreur de récupération';
            fetchBtn.disabled = false;
        }
    });

    // 2. Run AI Council Debate
    runBtn.addEventListener('click', async () => {
        runBtn.disabled = true;
        runBtn.innerText = '🧠 Le Conseil délibère...';

        // Add shimmer effect while loading
        statResponse.classList.add('shimmer');
        expertResponse.classList.add('shimmer');
        pessimistResponse.classList.add('shimmer');
        trendResponse.classList.add('shimmer');
        statResponse.innerText = '';
        expertResponse.innerText = '';
        pessimistResponse.innerText = '';
        trendResponse.innerText = '';

        try {
            // Trigger parallel fetches with safe fallbacks
            const safeFetch = (url) => fetch(url)
                .then(r => r.ok ? r.json() : { text: "❌ Serveur surchargé (Erreur 500)" })
                .catch(() => ({ text: "❌ Erreur de connexion" }));

            const statPromise = safeFetch('/api/council/statistician');
            const expertPromise = safeFetch('/api/council/expert');
            const pessimistPromise = safeFetch('/api/council/pessimist');
            const trendPromise = safeFetch('/api/council/trend');

            let statText = "⏳ Analyse en cours...", expertText = "⏳ Analyse en cours...", pessimistText = "⏳ Analyse en cours...", trendText = "⏳ Analyse en cours...";

            const updateChat = () => {
                chatDialogue.innerHTML = `
                    <div style="background: rgba(30, 41, 59, 0.8); padding: 1rem; border-radius: 12px; border-left: 4px solid var(--stat-color);">
                        <strong>📊 Le Statisticien :</strong><br><span style="color:#cbd5e1">${statText}</span>
                    </div>
                    <div style="background: rgba(30, 41, 59, 0.8); padding: 1rem; border-radius: 12px; border-left: 4px solid var(--expert-color);">
                        <strong>🧠 L'Expert Terrain :</strong><br><span style="color:#cbd5e1">${expertText}</span>
                    </div>
                    <div style="background: rgba(30, 41, 59, 0.8); padding: 1rem; border-radius: 12px; border-left: 4px solid #ef4444;">
                        <strong>👿 L'Avocat du Diable :</strong><br><span style="color:#cbd5e1">${pessimistText}</span>
                    </div>
                    <div style="background: rgba(30, 41, 59, 0.8); padding: 1rem; border-radius: 12px; border-left: 4px solid #a855f7;">
                        <strong>📈 Le Réseauteur :</strong><br><span style="color:#cbd5e1">${trendText}</span>
                    </div>
                `;
            };

            updateChat(); // Initial Render

            statPromise.then(data => {
                statResponse.classList.remove('shimmer');
                statText = data?.text || "❌ Analyse indisponible";
                statResponse.innerHTML = formatMarkdown(statText);
                updateChat();
            }).catch(() => { statText = "Erreur"; updateChat(); });

            expertPromise.then(data => {
                expertResponse.classList.remove('shimmer');
                expertText = data?.text || "❌ Analyse indisponible";
                expertResponse.innerHTML = formatMarkdown(expertText);
                updateChat();
            }).catch(() => { expertText = "Erreur"; updateChat(); });

            pessimistPromise.then(data => {
                pessimistResponse.classList.remove('shimmer');
                pessimistText = data?.text || "❌ Analyse indisponible";
                pessimistResponse.innerHTML = formatMarkdown(pessimistText);
                updateChat();
            }).catch(() => { pessimistText = "Erreur"; updateChat(); });

            trendPromise.then(data => {
                trendResponse.classList.remove('shimmer');
                trendText = data?.text || "❌ Analyse indisponible";
                trendResponse.innerHTML = formatMarkdown(trendText);
                updateChat();
            }).catch(() => { trendText = "Erreur"; updateChat(); });

            // Wait for all 4 to finish before generating the final ticket
            await Promise.all([statPromise, expertPromise, pessimistPromise, trendPromise]);

            runBtn.innerText = '🎯 Création du Ticket Final...';

            const ticketResponse = await fetch('/api/council/ticket', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    stat_text: statText,
                    expert_text: expertText,
                    pessimist_text: pessimistText,
                    trend_text: trendText
                })
            });
            const ticketResult = await ticketResponse.json();

            // Render Final Ticket
            renderTicket(ticketResult.ticket);

            runBtn.innerText = '✅ Débat Terminé';
            placeBetBtn.disabled = false;

        } catch (error) {
            console.error("Error running council:", error);
            runBtn.innerText = '❌ Erreur de l\'IA';
            runBtn.disabled = false;
            statResponse.classList.remove('shimmer');
            expertResponse.classList.remove('shimmer');
            pessimistResponse.classList.remove('shimmer');
            trendResponse.classList.remove('shimmer');
        }
    });

    function renderMatches(matches) {
        matchesList.innerHTML = '';

        const filteredMatches = currentFilter === 'all'
            ? matches
            : matches.filter(m => {
                const s = m.sport.toLowerCase();
                if (currentFilter === 'other') return !['football', 'rugby', 'basket', 'nba', 'tennis'].some(k => s.includes(k));
                if (currentFilter === 'basket') return s.includes('basket') || s.includes('nba');
                return s.includes(currentFilter);
            });

        if (filteredMatches.length === 0) {
            matchesList.innerHTML = '<div class="empty-state">Aucun match trouvé pour cette catégorie.</div>';
            return;
        }

        filteredMatches.forEach(match => {
            const div = document.createElement('div');
            div.className = 'match-item';

            // Only show 1 N 2. For tennis there is no N.
            let oddsHtml = '';
            if (match.odds["1"]) oddsHtml += `<div class="odd-badge">1: ${match.odds["1"]}</div>`;
            if (match.odds["N"]) oddsHtml += `<div class="odd-badge">N: ${match.odds["N"]}</div>`;
            if (match.odds["2"]) oddsHtml += `<div class="odd-badge">2: ${match.odds["2"]}</div>`;

            if (match.specialMarket && match.specialOdd) {
                oddsHtml += `<div class="odd-badge special">⭐ ${match.specialMarket}: ${match.specialOdd}</div>`;
            }

            div.innerHTML = `
                <div class="match-header">
                    <span class="sport-badge">${match.sport}</span>
                    <span>${match.competition}</span>
                    <span>${match.date}</span>
                </div>
                <div class="match-teams">${match.homeTeam} vs ${match.awayTeam}</div>
                <div class="odds-container">
                    ${oddsHtml}
                </div>
            `;
            matchesList.appendChild(div);
        });
    }

    function renderTicket(ticket) {
        bookieDebate.innerHTML = formatMarkdown(ticket.debate); // Applied formatMarkdown
        totalOddsValue.innerText = `x ${ticket.total_odds}`;

        finalTicketList.innerHTML = '';
        ticket.selections.forEach(item => {
            const div = document.createElement('div');
            div.className = 'ticket-item';
            div.innerHTML = `
                <div class="ticket-match">
                    <div class="ticket-match-name">${item.match_name}</div>
                    <div class="ticket-prediction">Pari : ${item.prediction}</div>
                </div>
                <div class="ticket-odd">${item.odds}</div>
            `;
            finalTicketList.appendChild(div);
        });
    }

    // Redirect to Parions Sport
    placeBetBtn.addEventListener('click', () => {
        window.open('https://www.enligne.parionssport.fdj.fr/', '_blank');
    });

    // 3. Live In-Play Betting Tracker
    const liveMatchBtn = document.getElementById('liveMatchBtn');
    const liveMatchesList = document.getElementById('liveMatchesList');
    const liveAdvice = document.getElementById('liveAdvice');

    liveMatchBtn.addEventListener('click', async () => {
        liveMatchBtn.disabled = true;
        liveMatchBtn.innerText = '⏳ Recherche de paris Live avec Gemini...';
        liveMatchesList.innerHTML = '';
        liveAdvice.style.display = 'none';

        try {
            const response = await fetch('/api/live-council');
            const data = await response.json();

            const liveMatches = data.matches || [];
            if (liveMatches.length === 0) {
                liveMatchesList.innerHTML = '<div class="empty-state">Aucun match Live intéressant trouvé actuellement.</div>';
            } else {
                liveMatches.forEach(match => {
                    const div = document.createElement('div');
                    div.className = 'match-item';
                    div.style.borderColor = "#ef4444";
                    div.innerHTML = `
                        <div class="match-header">
                            <span class="sport-badge" style="background: rgba(239, 68, 68, 0.2); color: #fca5a5;">${match.sport} - ${match.time}</span>
                            <span style="color: #ef4444; font-weight: bold; animation: pulse 2s infinite;">${match.score}</span>
                        </div>
                        <div class="match-teams">${match.homeTeam} vs ${match.awayTeam}</div>
                        <div style="font-size: 0.85rem; color: #cbd5e1; margin-top: 0.5rem; margin-bottom: 0.5rem;">${match.live_context}</div>
                        <div class="odd-badge special" style="background: rgba(239, 68, 68, 0.1); color: #f87171;">⭐ Suggéré: ${match.suggested_bet} @ ${match.estimated_odd}</div>
                    `;
                    liveMatchesList.appendChild(div);
                });

                liveAdvice.style.display = 'block';
                liveAdvice.innerText = "🗣️ AI Live Analyst: " + data.advice;
            }

            liveMatchBtn.innerText = '✅ Valeurs Direct Récupérées';
            setTimeout(() => { liveMatchBtn.disabled = false; liveMatchBtn.innerText = '🔄 Rafraîchir le Direct'; }, 5000);

        } catch (error) {
            console.error("Error fetching live council:", error);
            liveMatchBtn.innerText = '❌ Erreur Live';
            liveMatchBtn.disabled = false;
        }
    });

});

