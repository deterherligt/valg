document.addEventListener('alpine:init', () => {
  Alpine.data('dashboard', () => ({
    selectedPartyIds: [],
    focusedCandidateId: null,

    parties: [],
    candidates: [],
    partyDetail: null,
    candidateDetail: null,
    candidateFeed: [],
    feedItems: [],
    selectedPlaceId: null,
    placeDetail: null,
    activeTab: 'detail',  // 'detail' | 'sted'
    feedPanelHeight: 120,
    _feedResizing: false,
    _feedResizeStartY: 0,
    _feedResizeStartH: 0,
    colWidths: {parties: 220, candidates: 220},

    lastSynced: null,
    districtsReported: null,
    districtsTotal: null,
    preliminaryPlaces: null,
    finalPlaces: null,
    totalPlaces: null,
    syncing: false,  // true during just_synced refresh — drives pulsing header
    demo: { enabled: false, state: 'idle', scenario: '', scenarios: [], speed: 1 },
    showAbout: false,

    async init() {
      const savedH = localStorage.getItem('valg_feed_height')
      if (savedH) this.feedPanelHeight = parseInt(savedH, 10)
      const savedCols = localStorage.getItem('valg_col_widths')
      if (savedCols) {
        try {
          const w = JSON.parse(savedCols)
          if (w && typeof w.parties === 'number' && typeof w.candidates === 'number') {
            this.colWidths = w
          }
        } catch (_) {}
      }
      await this._fetchAll()
      await this._fetchDemoState()
      setInterval(() => this._poll(), 10000)
      setInterval(() => this._fetchDemoState(), 5000)
    },

    async _fetchAll() {
      await Promise.all([this._fetchStatus(), this._fetchParties(), this._fetchFeedPlaces()])
      if (this.selectedPartyIds.length) {
        await Promise.all([this._fetchCandidates(), this._fetchPartyDetail()])
      }
      if (this.focusedCandidateId) {
        await Promise.all([this._fetchCandidateDetail(), this._fetchCandidateFeed()])
      }
    },

    async _poll() {
      const resp = await fetch('/api/status').catch(() => null)
      if (!resp) return
      const data = await resp.json()
      this.lastSynced = data.last_sync
      this.districtsReported = data.districts_reported
      this.districtsTotal = data.districts_total
      this.preliminaryPlaces = data.preliminary_places
      this.finalPlaces = data.final_places
      this.totalPlaces = data.total_places
      if (data.just_synced) {
        this.syncing = true
        await this._fetchAll()
        this.syncing = false
        return
      }
      await Promise.all([this._fetchParties(), this._fetchFeedPlaces()])
      if (this.selectedPartyIds.length) {
        await Promise.all([this._fetchCandidates(), this._fetchPartyDetail()])
      }
      if (this.focusedCandidateId) {
        await Promise.all([this._fetchCandidateDetail(), this._fetchCandidateFeed()])
      }
    },

    async _fetchStatus() {
      const resp = await fetch('/api/status').catch(() => null)
      if (!resp) return
      const data = await resp.json()
      this.lastSynced = data.last_sync
      this.districtsReported = data.districts_reported
      this.districtsTotal = data.districts_total
      this.preliminaryPlaces = data.preliminary_places
      this.finalPlaces = data.final_places
      this.totalPlaces = data.total_places
    },

    async _fetchParties() {
      const resp = await fetch('/api/parties').catch(() => null)
      if (!resp) return
      this.parties = await resp.json()
    },

    async _fetchFeedPlaces() {
      const resp = await fetch('/api/feed/places').catch(() => null)
      if (!resp) return
      this.feedItems = await resp.json()
    },

    async selectPlace(item) {
      this.selectedPlaceId = String(item.event_id)
      this.activeTab = 'sted'
      const resp = await fetch('/api/place/' + item.place_id).catch(() => null)
      if (!resp) return
      this.placeDetail = await resp.json()
    },

    startFeedResize(e) {
      this._feedResizing = true
      this._feedResizeStartY = e.clientY
      this._feedResizeStartH = this.feedPanelHeight
      const onMove = (ev) => {
        if (!this._feedResizing) return
        const delta = this._feedResizeStartY - ev.clientY
        this.feedPanelHeight = Math.max(52, this._feedResizeStartH + delta)
      }
      const onUp = () => {
        this._feedResizing = false
        localStorage.setItem('valg_feed_height', this.feedPanelHeight)
        document.removeEventListener('mousemove', onMove)
        document.removeEventListener('mouseup', onUp)
      }
      document.addEventListener('mousemove', onMove)
      document.addEventListener('mouseup', onUp)
    },

    startColResize(e, col) {
      const startX = e.clientX
      const startW = this.colWidths[col]
      const onMove = (ev) => {
        const delta = ev.clientX - startX
        this.colWidths[col] = Math.max(120, startW + delta)
      }
      const onUp = () => {
        localStorage.setItem('valg_col_widths', JSON.stringify(this.colWidths))
        document.removeEventListener('mousemove', onMove)
        document.removeEventListener('mouseup', onUp)
      }
      document.addEventListener('mousemove', onMove)
      document.addEventListener('mouseup', onUp)
    },

    async _fetchCandidates() {
      if (!this.selectedPartyIds.length) { this.candidates = []; return }
      const params = new URLSearchParams({ party_ids: this.selectedPartyIds.join(',') })
      const resp = await fetch('/api/candidates?' + params).catch(() => null)
      if (!resp) return
      this.candidates = await resp.json()
    },

    async _fetchPartyDetail() {
      if (!this.selectedPartyIds.length) { this.partyDetail = null; return }
      const params = new URLSearchParams({ party_ids: this.selectedPartyIds.join(',') })
      const resp = await fetch('/api/party-detail?' + params).catch(() => null)
      if (!resp) return
      this.partyDetail = await resp.json()
    },

    async _fetchCandidateDetail() {
      if (!this.focusedCandidateId) return
      const resp = await fetch('/api/candidate/' + this.focusedCandidateId).catch(() => null)
      if (!resp) return
      this.candidateDetail = await resp.json()
    },

    async _fetchCandidateFeed() {
      if (!this.focusedCandidateId) return
      const resp = await fetch('/api/candidate-feed/' + this.focusedCandidateId + '?limit=20').catch(() => null)
      if (!resp) return
      this.candidateFeed = await resp.json()
    },

    toggleParty(partyId) {
      if (this.selectedPartyIds.includes(partyId)) {
        this.selectedPartyIds = this.selectedPartyIds.filter(id => id !== partyId)
        // Clear focused candidate if their party was deselected
        if (this.focusedCandidateId) {
          const fc = this.candidates.find(c => c.id === this.focusedCandidateId)
          if (fc && fc.party_id === partyId) {
            this.focusedCandidateId = null
            this.candidateDetail = null
            this.candidateFeed = []
          }
        }
      } else {
        this.selectedPartyIds = [...this.selectedPartyIds, partyId]
      }
      Promise.all([this._fetchCandidates(), this._fetchPartyDetail()])
    },

    focusCandidate(candidateId) {
      if (this.focusedCandidateId === candidateId) {
        this.focusedCandidateId = null
        this.candidateDetail = null
        this.candidateFeed = []
      } else {
        this.focusedCandidateId = candidateId
        Promise.all([this._fetchCandidateDetail(), this._fetchCandidateFeed()])
      }
    },

    get candidatesByParty() {
      const groups = {}
      for (const c of this.candidates) {
        if (!groups[c.party_id]) {
          groups[c.party_id] = { party_id: c.party_id, letter: c.party_letter, candidates: [] }
        }
        groups[c.party_id].candidates.push(c)
      }
      return Object.values(groups)
    },

    get selectedPartyLetters() {
      return this.parties
        .filter(p => this.selectedPartyIds.includes(p.id))
        .map(p => p.letter || p.id)
        .join(', ')
    },

    formatNum(n) {
      if (n == null) return '—'
      return n.toLocaleString('da-DK')
    },

    formatTime(isoStr) {
      if (!isoStr) return ''
      return new Date(isoStr).toLocaleTimeString('da-DK', {
        hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Copenhagen'
      })
    },

    async _fetchDemoState() {
      const resp = await fetch('/demo/state').catch(() => null)
      if (!resp || !resp.ok) return
      this.demo = await resp.json()
    },

    async demoControl(action, extra = {}) {
      await fetch('/demo/control', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({action, ...extra}),
      }).catch(() => null)
      await this._fetchDemoState()
    },

    async demoSetScenario(name) {
      await this.demoControl('set_scenario', {scenario: name})
      await this.demoControl('restart')
    },

    async demoSetSpeed(speed) {
      await this.demoControl('set_speed', {speed: parseFloat(speed)})
    },
  }))
})
