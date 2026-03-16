document.addEventListener('alpine:init', () => {
  Alpine.data('dashboard', () => ({
    selectedPartyIds: [],
    selectedCandidateIds: [],
    focusedCandidateId: null,

    parties: [],
    candidates: [],
    partyDetail: null,
    candidateDetail: null,
    candidateFeed: [],
    feed: [],

    lastSynced: null,
    districtsReported: null,
    districtsTotal: null,
    syncing: false,  // true during just_synced refresh — drives pulsing header

    async init() {
      await this._fetchAll()
      setInterval(() => this._poll(), 10000)
    },

    async _fetchAll() {
      await Promise.all([this._fetchStatus(), this._fetchParties(), this._fetchFeed()])
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
      if (data.just_synced) {
        this.syncing = true
        await this._fetchAll()
        this.syncing = false
        return
      }
      await Promise.all([this._fetchParties(), this._fetchFeed()])
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
    },

    async _fetchParties() {
      const resp = await fetch('/api/parties').catch(() => null)
      if (!resp) return
      this.parties = await resp.json()
    },

    async _fetchFeed() {
      const resp = await fetch('/api/feed?limit=50').catch(() => null)
      if (!resp) return
      this.feed = await resp.json()
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

    toggleCandidateCheck(candidateId) {
      if (this.selectedCandidateIds.includes(candidateId)) {
        this.selectedCandidateIds = this.selectedCandidateIds.filter(id => id !== candidateId)
      } else {
        this.selectedCandidateIds = [...this.selectedCandidateIds, candidateId]
      }
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
      return isoStr.slice(11, 16)
    },
  }))
})
