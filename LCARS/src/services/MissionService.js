import axios from 'axios'

// Sends the Django admin session cookie, so a logged-in captain can decide gates
const http = axios.create({
  baseURL: 'http://localhost:8000',
  withCredentials: true,
  headers: { 'Content-type': 'application/json' }
})

let csrfToken = ''

class MissionService {
  async session() {
    const { data } = await http.get('/api/missions/session/')
    csrfToken = data.csrf_token
    return data
  }

  async list() {
    const { data } = await http.get('/api/missions/')
    return data.missions
  }

  async detail(id, since = 0) {
    const { data } = await http.get(`/api/missions/${id}/`, { params: { since } })
    return data
  }

  async decide(gateId, decision, note) {
    const { data } = await http.post(`/api/gates/${gateId}/decide/`, { decision, note }, {
      headers: { 'X-CSRFToken': csrfToken }
    })
    return data.gate
  }

  async crewStatus() {
    const { data } = await http.get('/api/crew/status/')
    return data
  }

  async launch(mission) {
    const { data } = await http.post('/api/missions/launch/', mission, {
      headers: { 'X-CSRFToken': csrfToken }
    })
    return data.mission
  }

  async startModel(model) {
    const { data } = await http.post('/api/crew/model/start/', { model }, {
      headers: { 'X-CSRFToken': csrfToken }
    })
    return data.model_server
  }

  async stopModel() {
    const { data } = await http.post('/api/crew/model/stop/', {}, {
      headers: { 'X-CSRFToken': csrfToken }
    })
    return data.model_server
  }

  async fetchData() {
    const { data } = await http.post('/api/crew/fetch/', {}, {
      headers: { 'X-CSRFToken': csrfToken }
    })
    return data
  }

  loginUrl() {
    return `${http.defaults.baseURL}/admin/login/?next=/admin/`
  }
}

export default new MissionService()
