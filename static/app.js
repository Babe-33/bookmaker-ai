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
            }
        } catch (e) { console.error("Auto-load failed", e); }
    }
    initMatches();

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
            // Simultaneous individual calls for better UX
            const statPromise = fetch('/api/council/statistician').then(r => r.json());
            const expertPromise = fetch('/api/council/expert').then(r => r.json());
            const pessimistPromise = fetch('/api/council/pessimist').then(r => r.json());
            const trendPromise = fetch('/api/council/trend').then(r => r.json());

            statPromise.then(data => {
                const text = data?.text || "❌ Indisponible";
                statResponse.innerHTML = formatMarkdown(text);
                addChatBubble("📊 Statisticien", text);
            });
            expertPromise.then(data => {
                const text = data?.text || "❌ Indisponible";
                expertResponse.innerHTML = formatMarkdown(text);
                addChatBubble("🧠 Expert", text);
            });
            pessimistPromise.then(data => {
                const text = data?.text || "❌ Indisponible";
                pessimistResponse.innerHTML = formatMarkdown(text);
                addChatBubble("👿 Avocat du Diable", text);
            });
            trendPromise.then(data => {
                const text = data?.text || "❌ Indisponible";
                trendResponse.innerHTML = formatMarkdown(text);
                addChatBubble("📈 Réseauteur", text);
            });

            const [s, e, p, t] = await Promise.all([statPromise, expertPromise, pessimistPromise, trendPromise]);

            const ticketResponse = await fetch('/api/council/ticket', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    stat_text: s.text,
                    expert_text: e.text,
                    pessimist_text: p.text,
                    trend_text: t.text
                })
            });
            const ticketData = await ticketResponse.json();
            renderTicket(ticketData.ticket);

            runBtn.innerText = '✅ Analyse Terminée';
        } catch (error) {
            console.error(error);
            runBtn.innerText = '❌ Erreur IA';
            runBtn.disabled = false;
        }
    });

    function renderMatches(matches) {
        matchesList.innerHTML = '';
        const filtered = currentFilter === 'all'
            ? matches
            : matches.filter(m => {
                const s = m.sport.toLowerCase();
                if (currentFilter === 'other') return !['football', 'rugby', 'basket', 'hockey', 'f1', 'biathlon', 'tennis'].some(k => s.includes(k));
                if (currentFilter === 'basket') return s.includes('basket') || s.includes('nba');
                if (currentFilter === 'hockey') return s.includes('hockey') || s.includes('nhl');
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

            div.innerHTML = `
                <div class="match-header">
                    <span class="sport-badge">${match.sport}</span>
                    <span>${match.competition}</span>
                    <span>${formatDate(match.date)}</span>
                </div>
                <div class="match-teams">${match.homeTeam} vs ${match.awayTeam}</div>
                <div class="match-odds">${oddsHtml}</div>
            `;
            matchesList.appendChild(div);
        });
    }

    function renderTicket(ticket) {
        bookieDebate.innerHTML = formatMarkdown(ticket.debate);
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
        placeBetBtn.disabled = false;
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
