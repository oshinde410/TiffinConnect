import { useCallback, useEffect, useMemo, useState } from 'react'
import './App.css'

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api'

const initialForm = {
  name: '',
  email: 'arjun@student.tiffin',
  password: 'student123',
  role: 'student',
  hostel: 'Boys Hostel - Block A',
  budget: '1800',
  veg_preference: 'vegetarian',
  favorite_meal: 'Paneer Bowl',
}

function App() {
  const [authMode, setAuthMode] = useState('login')
  const [form, setForm] = useState(initialForm)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [token, setToken] = useState(localStorage.getItem('tiffin-token') || '')
  const [user, setUser] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem('tiffin-user') || 'null')
    } catch {
      localStorage.removeItem('tiffin-user')
      return null
    }
  })
  const [meals, setMeals] = useState([])
  const [dashboard, setDashboard] = useState(null)
  const [statusMessage, setStatusMessage] = useState('')
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState(
    user?.role === 'student' && user.veg_preference === 'vegetarian' ? 'veg' : '',
  )
  const [planType, setPlanType] = useState('daily')
  const [quantities, setQuantities] = useState({})
  const [reviewMeal, setReviewMeal] = useState(null)
  const [reviews, setReviews] = useState([])
  const [reviewRating, setReviewRating] = useState(5)
  const [reviewComment, setReviewComment] = useState('')
  const [mealDraft, setMealDraft] = useState({
    name: '',
    description: '',
    price: '',
    category: 'veg',
    stock: 20,
    prep_time: '25 mins',
    image_url: '',
  })
  const [editingMealId, setEditingMealId] = useState(null)
  const [isSavingMeal, setIsSavingMeal] = useState(false)

  const roleLabel = useMemo(() => {
    if (!user) return 'Guest'
    return user.role.charAt(0).toUpperCase() + user.role.slice(1)
  }, [user])

  const persistentAuth = async (response) => {
    const authToken = response.token
    const authUser = response.user
    localStorage.setItem('tiffin-token', authToken)
    localStorage.setItem('tiffin-user', JSON.stringify(authUser))
    setToken(authToken)
    setUser(authUser)
    setCategory(
      authUser.role === 'student' && authUser.veg_preference === 'vegetarian' ? 'veg' : '',
    )
  }

  const fetchJson = useCallback(async (url, options = {}) => {
    const headers = {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    }

    if (token) {
      headers.Authorization = `Bearer ${token}`
    }

    const response = await fetch(url, { ...options, headers })
    const data = await response.json().catch(() => ({}))

    if (!response.ok) {
      if (response.status === 401) {
        localStorage.removeItem('tiffin-token')
        localStorage.removeItem('tiffin-user')
        setToken('')
        setUser(null)
        setDashboard(null)
      }
      throw new Error(data.detail || 'Request failed')
    }

    return data
  }, [token])

  const fetchMeals = useCallback(async () => {
    try {
      const params = new URLSearchParams()
      if (search.trim()) params.set('search', search.trim())
      if (category) params.set('category', category)
      const data = await fetchJson(`${API_BASE}/meals?${params}`)
      setMeals(data.meals || [])
    } catch (err) {
      setError(err.message)
    }
  }, [category, fetchJson, search])

  const fetchDashboard = useCallback(async () => {
    if (!token || !user) return

    let endpoint = `${API_BASE}/student/dashboard`
    if (user.role === 'cook') endpoint = `${API_BASE}/cook/dashboard`
    if (user.role === 'admin') endpoint = `${API_BASE}/admin/dashboard`

    try {
      const data = await fetchJson(endpoint)
      setDashboard(data)
    } catch (err) {
      setError(err.message)
    }
  }, [fetchJson, token, user])

  useEffect(() => {
    const params = new URLSearchParams()
    if (search.trim()) params.set('search', search.trim())
    if (category) params.set('category', category)
    const controller = new AbortController()
    // These effects intentionally synchronize the remote catalog and dashboard into UI state.
    // oxlint-disable-next-line react/set-state-in-effect
    fetchJson(`${API_BASE}/meals?${params}`, { signal: controller.signal })
      .then((data) => setMeals(data.meals || []))
      .catch((err) => {
        if (err.name !== 'AbortError') setError(err.message)
      })
    return () => controller.abort()
  }, [category, fetchJson, search])

  useEffect(() => {
    if (!token || !user) return undefined
    let endpoint = `${API_BASE}/student/dashboard`
    if (user.role === 'cook') endpoint = `${API_BASE}/cook/dashboard`
    if (user.role === 'admin') endpoint = `${API_BASE}/admin/dashboard`
    const controller = new AbortController()
    // oxlint-disable-next-line react/set-state-in-effect
    fetchJson(endpoint, { signal: controller.signal })
      .then(setDashboard)
      .catch((err) => {
        if (err.name !== 'AbortError') setError(err.message)
      })
    return () => controller.abort()
  }, [fetchJson, token, user])

  const handleSubmit = async (event) => {
    event.preventDefault()
    setIsSubmitting(true)
    setError('')
    setStatusMessage('')

    try {
      const endpoint = authMode === 'login' ? '/auth/login' : '/auth/register'
      const payload = authMode === 'login'
        ? { email: form.email, password: form.password }
        : {
            name: form.name,
            email: form.email,
            password: form.password,
            role: form.role,
            hostel: form.hostel,
            budget: Number(form.budget || 1800),
            veg_preference: form.veg_preference,
            favorite_meal: form.favorite_meal,
          }

      const response = await fetchJson(`${API_BASE}${endpoint}`, {
        method: 'POST',
        body: JSON.stringify(payload),
      })

      await persistentAuth(response)
      setStatusMessage(authMode === 'login' ? 'Welcome back!' : 'Account created successfully!')
      setForm(initialForm)
    } catch (err) {
      setError(err.message)
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleOrder = async (mealId) => {
    if (!token) {
      setError('Please log in to place an order.')
      return
    }

    try {
      const response = await fetchJson(`${API_BASE}/orders`, {
        method: 'POST',
        body: JSON.stringify({
          meal_id: mealId,
          quantity: Number(quantities[mealId] || 1),
          plan_type: planType,
        }),
      })
      setStatusMessage(response.message)
      await fetchDashboard()
      await fetchMeals()
    } catch (err) {
      setError(err.message)
    }
  }

  const openReviews = async (meal) => {
    setReviewMeal(meal)
    setReviewComment('')
    setReviewRating(5)
    setError('')
    try {
      const data = await fetchJson(`${API_BASE}/meals/${meal.id}/reviews`)
      setReviews(data.reviews || [])
    } catch (err) {
      setError(err.message)
    }
  }

  const submitReview = async (event) => {
    event.preventDefault()
    if (!reviewMeal) return
    try {
      const data = await fetchJson(`${API_BASE}/reviews`, {
        method: 'POST',
        body: JSON.stringify({
          meal_id: reviewMeal.id,
          rating: Number(reviewRating),
          comment: reviewComment,
        }),
      })
      setStatusMessage(data.message)
      setReviewMeal(null)
      await fetchDashboard()
      await fetchMeals()
    } catch (err) {
      setError(err.message)
    }
  }

  const createMeal = async (event) => {
    event.preventDefault()
    setIsSavingMeal(true)
    setError('')
    try {
      await fetchJson(
        editingMealId ? `${API_BASE}/meals/${editingMealId}` : `${API_BASE}/meals`,
        {
        method: editingMealId ? 'PUT' : 'POST',
        body: JSON.stringify({
          ...mealDraft,
          price: Number(mealDraft.price),
          stock: Number(mealDraft.stock),
          image_url: mealDraft.image_url || undefined,
        }),
        },
      )
      setMealDraft({
        name: '',
        description: '',
        price: '',
        category: 'veg',
        stock: 20,
        prep_time: '25 mins',
        image_url: '',
      })
      setEditingMealId(null)
      setStatusMessage(editingMealId ? 'Menu item updated.' : 'Meal added to your menu.')
      await fetchDashboard()
      await fetchMeals()
    } catch (err) {
      setError(err.message)
    } finally {
      setIsSavingMeal(false)
    }
  }

  const editMeal = (meal) => {
    setEditingMealId(meal.id)
    setMealDraft({
      name: meal.name,
      description: meal.description,
      price: String(meal.price),
      category: meal.category,
      stock: meal.stock,
      prep_time: meal.prep_time,
      image_url: meal.image_url || '',
    })
    document.getElementById('menu-editor')?.scrollIntoView({ behavior: 'smooth' })
  }

  const removeMeal = async (mealId) => {
    try {
      await fetchJson(`${API_BASE}/meals/${mealId}`, { method: 'DELETE' })
      setStatusMessage('Meal removed from your menu.')
      await fetchDashboard()
      await fetchMeals()
    } catch (err) {
      setError(err.message)
    }
  }

  const changeOrderStatus = async (orderId, nextStatus) => {
    try {
      await fetchJson(`${API_BASE}/orders/${orderId}/status`, {
        method: 'PATCH',
        body: JSON.stringify({ status: nextStatus }),
      })
      setStatusMessage(`Order #${orderId} updated.`)
      await fetchDashboard()
    } catch (err) {
      setError(err.message)
    }
  }

  const logout = () => {
    localStorage.removeItem('tiffin-token')
    localStorage.removeItem('tiffin-user')
    setToken('')
    setUser(null)
    setDashboard(null)
    setMeals([])
    setCategory('')
    setStatusMessage('Logged out successfully.')
  }

  return (
    <div className="app-shell" id="top">
      <header className="topbar">
        <div className="brand-block">
          <div className="brand-mark">TC</div>
          <div>
            <div className="brand-name">TiffinConnect</div>
            <small>Hostel meal marketplace</small>
          </div>
        </div>

        <nav className="main-nav">
          <a href="#top">Home</a>
          <a href="#catalog">Meals</a>
          {user?.role === 'cook' && <a href="#forecast">Forecast</a>}
          {user && <a href="#orders">Orders</a>}
        </nav>

        {user ? (
          <div className="user-chip">
            <span>{user.name}</span>
            <button type="button" onClick={logout}>Logout</button>
          </div>
        ) : (
          <div className="user-chip muted">Demo ready</div>
        )}
      </header>

      {!user ? (
        <>
          <section className="hero-section">
            <div className="hero-copy">
              <span className="eyebrow">Fresh • Affordable • Community-led</span>
              <h1>Home-cooked meals that feel like home.</h1>
              <p>
                Connect hostel students with local cooks, manage subscriptions, and use
                predictive demand insights to keep kitchens stocked and students happy.
              </p>

              <div className="hero-stats">
                <div>
                  <strong>1200+</strong>
                  <span>monthly orders</span>
                </div>
                <div>
                  <strong>25</strong>
                  <span>verified cooks</span>
                </div>
                <div>
                  <strong>4.8/5</strong>
                  <span>avg. student rating</span>
                </div>
              </div>
            </div>

            <form className="auth-panel" onSubmit={handleSubmit}>
              <div className="auth-toggle">
                <button
                  type="button"
                  className={authMode === 'login' ? 'active' : ''}
                  onClick={() => setAuthMode('login')}
                >
                  Login
                </button>
                <button
                  type="button"
                  className={authMode === 'register' ? 'active' : ''}
                  onClick={() => setAuthMode('register')}
                >
                  Register
                </button>
              </div>

              {authMode === 'register' && (
                <label>
                  Name
                  <input
                    value={form.name}
                    onChange={(event) => setForm({ ...form, name: event.target.value })}
                    placeholder="Your name"
                  />
                </label>
              )}

              <label>
                Email
                <input
                  type="email"
                  value={form.email}
                  onChange={(event) => setForm({ ...form, email: event.target.value })}
                  placeholder="you@example.com"
                />
              </label>

              <label>
                Password
                <input
                  type="password"
                  value={form.password}
                  onChange={(event) => setForm({ ...form, password: event.target.value })}
                  placeholder="••••••••"
                />
              </label>

              {authMode === 'register' && (
                <>
                  <label>
                    Role
                    <select
                      value={form.role}
                      onChange={(event) => setForm({ ...form, role: event.target.value })}
                    >
                      <option value="student">Student</option>
                      <option value="cook">Cook</option>
                    </select>
                  </label>

                  <label>
                    Hostel / kitchen location
                    <input
                      value={form.hostel}
                      onChange={(event) => setForm({ ...form, hostel: event.target.value })}
                    />
                  </label>
                  {form.role === 'student' && (
                    <>
                      <label>
                        Monthly meal budget (₹)
                        <input
                          type="number"
                          min="1"
                          value={form.budget}
                          onChange={(event) => setForm({ ...form, budget: event.target.value })}
                        />
                      </label>
                      <label>
                        Food preference
                        <select
                          value={form.veg_preference}
                          onChange={(event) => setForm({ ...form, veg_preference: event.target.value })}
                        >
                          <option value="vegetarian">Vegetarian</option>
                          <option value="non_vegetarian">Non-vegetarian</option>
                        </select>
                      </label>
                    </>
                  )}
                </>
              )}

              {error && <div className="alert error">{error}</div>}
              {statusMessage && <div className="alert success">{statusMessage}</div>}

              <button className="primary-button" type="submit" disabled={isSubmitting}>
                {isSubmitting ? 'Please wait...' : authMode === 'login' ? 'Login' : 'Create account'}
              </button>

              <div className="demo-credentials">
                Demo login: <strong>arjun@student.tiffin</strong> / <strong>student123</strong>
              </div>
            </form>
          </section>

          <section className="catalog-section" id="catalog">
            <div className="section-header">
              <div>
                <span className="eyebrow">Popular meals</span>
                <h2>Student favorites this week</h2>
              </div>
            </div>

            <div className="catalog-tools">
              <input
                type="search"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search meals or ingredients"
                aria-label="Search meals"
              />
              <select
                value={category}
                onChange={(event) => setCategory(event.target.value)}
                aria-label="Filter by meal type"
              >
                <option value="">All meals</option>
                <option value="veg">Vegetarian</option>
                <option value="non_veg">Non-vegetarian</option>
              </select>
            </div>

            <div className="meal-grid preview-grid">
              {meals.slice(0, 4).map((meal) => (
                <article key={meal.id} className="meal-card">
                  <img src={meal.image_url} alt={meal.name} />
                  <div className="meal-info">
                    <div className="meal-topline">
                      <span className="pill">{meal.category}</span>
                      <strong>₹{meal.price}</strong>
                    </div>
                    <h3>{meal.name}</h3>
                    <p>{meal.description}</p>
                    <div className="meta-row">
                      <span>⭐ {meal.rating}</span>
                      <span>{meal.prep_time}</span>
                    </div>
                  </div>
                </article>
              ))}
            </div>
          </section>
        </>
      ) : (
        <main className="dashboard-shell">
          <section className="summary-grid">
            {dashboard?.summary ? (
              Object.entries(dashboard.summary).map(([key, value]) => (
                <div key={key} className="summary-card">
                  <span>{key.replace(/([A-Z])/g, ' $1').replace(/^./, (c) => c.toUpperCase())}</span>
                  <strong>{value}</strong>
                </div>
              ))
            ) : (
              <div className="summary-card wide-card">Loading dashboard…</div>
            )}
          </section>

          {error && <div className="alert error">{error}</div>}
          {statusMessage && <div className="alert success">{statusMessage}</div>}

          <section className="content-grid" id="catalog">
            <div className="panel main-panel">
              <div className="section-header compact">
                <div>
                  <span className="eyebrow">Available meals</span>
                  <h2>{roleLabel} catalog</h2>
                </div>
              </div>

              <div className="catalog-tools">
                <input
                  type="search"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="Search meals or ingredients"
                  aria-label="Search meals"
                />
                <select
                  value={category}
                  onChange={(event) => setCategory(event.target.value)}
                  aria-label="Filter by meal type"
                >
                  <option value="">All meals</option>
                  <option value="veg">Vegetarian</option>
                  <option value="non_veg">Non-vegetarian</option>
                </select>
                {user.role === 'student' && (
                  <select value={planType} onChange={(event) => setPlanType(event.target.value)} aria-label="Order plan">
                    <option value="daily">One-time order</option>
                    <option value="weekly">Weekly plan</option>
                    <option value="monthly">Monthly plan</option>
                  </select>
                )}
              </div>

              <div className="meal-grid">
                {meals.map((meal) => (
                  <article key={meal.id} className="meal-card">
                    <img src={meal.image_url} alt={meal.name} onError={(event) => { event.currentTarget.style.visibility = 'hidden' }} />
                    <div className="meal-info">
                      <div className="meal-topline">
                        <span className="pill">{meal.category}</span>
                        <strong>₹{meal.price}</strong>
                      </div>
                      <h3>{meal.name}</h3>
                      <p>{meal.description}</p>
                      <div className="meta-row">
                        <span>⭐ {Number(meal.rating).toFixed(1)} · {meal.cook_name}</span>
                        <span>{meal.prep_time}</span>
                      </div>

                      {user.role === 'student' && (
                        <div className="meal-actions">
                          <label>
                            Portions
                            <input
                              type="number"
                              min="1"
                              max={Math.min(20, meal.stock)}
                              value={quantities[meal.id] || 1}
                              onChange={(event) => setQuantities({
                                ...quantities,
                                [meal.id]: Math.max(1, Math.min(20, Number(event.target.value))),
                              })}
                            />
                          </label>
                          <button
                            type="button"
                            className="primary-button card-button"
                            onClick={() => handleOrder(meal.id)}
                            disabled={meal.stock < 1}
                          >
                            {meal.stock > 0 ? `Order · ₹${meal.price * Number(quantities[meal.id] || 1)}` : 'Sold out'}
                          </button>
                          <button type="button" className="text-button" onClick={() => openReviews(meal)}>
                            Reviews ({meal.review_count || 0})
                          </button>
                        </div>
                      )}
                      {user.role === 'cook' && <div className="meta-row">Available portions: {meal.stock}</div>}
                    </div>
                  </article>
                ))}
              </div>
              {meals.length === 0 && <p className="empty-state">No meals match those filters yet.</p>}
            </div>

            <aside className="panel side-panel">
              {user.role === 'student' && (
                <>
                  <div className="section-header compact">
                    <div>
                      <span className="eyebrow">Smart picks</span>
                      <h2>Recommended meals</h2>
                    </div>
                  </div>

                  <div className="list-stack">
                    {(dashboard?.recommendations || []).map((meal) => (
                      <div key={meal.id} className="list-item">
                        <div>
                          <strong>{meal.name}</strong>
                          <small>{meal.cook_name}</small>
                        </div>
                        <div className="recommendation-actions">
                          <span>{meal.match_score ? `${Math.round(meal.match_score * 100)}% match` : 'Top pick'}</span>
                          <button type="button" className="text-button" onClick={() => handleOrder(meal.id)}>
                            Order
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                </>
              )}

              {user.role === 'cook' && dashboard?.demand && (
                <>
                  <div className="section-header compact" id="forecast">
                    <div>
                      <span className="eyebrow">Forecast</span>
                      <h2>Demand prediction</h2>
                    </div>
                  </div>

                  <div className="forecast-box">
                    {dashboard.demand.enabled === false ? (
                      <strong>Forecast unavailable</strong>
                    ) : (
                      <>
                        <strong>{dashboard.demand.suggested_preparation} bowls</strong>
                        <span>Suggested prep for upcoming week</span>
                        <div className="forecast-days">
                          {(dashboard.demand.forecast || []).map((day) => (
                            <div key={day.day}>
                              <span>{day.day}</span>
                              <strong>{day.predicted_orders}</strong>
                            </div>
                          ))}
                        </div>
                        <small>7-day holdout MAE: {dashboard.demand.holdout_mae} orders</small>
                      </>
                    )}
                    <p>{dashboard.demand.explanation}</p>
                  </div>
                </>
              )}

              {user.role === 'admin' && (
                <>
                  <div className="section-header compact">
                    <div>
                      <span className="eyebrow">Platform</span>
                      <h2>Recent orders</h2>
                    </div>
                  </div>

                  <div className="list-stack">
                    {(dashboard?.recent_orders || []).map((order) => (
                      <div key={order.id} className="list-item">
                        <div>
                          <strong>{order.meal_name}</strong>
                          <small>{order.student_name}</small>
                        </div>
                        <span>{order.status}</span>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </aside>
          </section>

          {user.role === 'cook' && (
            <section className="panel order-panel" id="menu-editor">
              <div className="section-header compact">
                <div>
                  <span className="eyebrow">Kitchen manager</span>
                  <h2>{editingMealId ? 'Edit menu item' : 'Add a meal to your menu'}</h2>
                </div>
              </div>
              <form className="meal-editor" onSubmit={createMeal}>
                <label>
                  Meal name
                  <input
                    required
                    minLength="2"
                    maxLength="120"
                    value={mealDraft.name}
                    onChange={(event) => setMealDraft({ ...mealDraft, name: event.target.value })}
                  />
                </label>
                <label>
                  Price (₹)
                  <input
                    required
                    type="number"
                    min="1"
                    step="0.01"
                    value={mealDraft.price}
                    onChange={(event) => setMealDraft({ ...mealDraft, price: event.target.value })}
                  />
                </label>
                <label>
                  Category
                  <select
                    value={mealDraft.category}
                    onChange={(event) => setMealDraft({ ...mealDraft, category: event.target.value })}
                  >
                    <option value="veg">Vegetarian</option>
                    <option value="non_veg">Non-vegetarian</option>
                  </select>
                </label>
                <label>
                  Portions available
                  <input
                    required
                    type="number"
                    min="0"
                    max="1000"
                    value={mealDraft.stock}
                    onChange={(event) => setMealDraft({ ...mealDraft, stock: event.target.value })}
                  />
                </label>
                <label className="editor-wide">
                  Description
                  <textarea
                    required
                    minLength="5"
                    maxLength="500"
                    value={mealDraft.description}
                    onChange={(event) => setMealDraft({ ...mealDraft, description: event.target.value })}
                  />
                </label>
                <label>
                  Preparation time
                  <input
                    maxLength="25"
                    value={mealDraft.prep_time}
                    onChange={(event) => setMealDraft({ ...mealDraft, prep_time: event.target.value })}
                  />
                </label>
                <label>
                  Image URL (optional)
                  <input
                    type="url"
                    value={mealDraft.image_url}
                    onChange={(event) => setMealDraft({ ...mealDraft, image_url: event.target.value })}
                  />
                </label>
                <div className="editor-actions editor-wide">
                  {editingMealId && (
                    <button
                      type="button"
                      className="secondary-button"
                      onClick={() => {
                        setEditingMealId(null)
                        setMealDraft({
                          name: '',
                          description: '',
                          price: '',
                          category: 'veg',
                          stock: 20,
                          prep_time: '25 mins',
                          image_url: '',
                        })
                      }}
                    >
                      Cancel edit
                    </button>
                  )}
                  <button className="primary-button" type="submit" disabled={isSavingMeal}>
                    {isSavingMeal ? 'Saving…' : editingMealId ? 'Save changes' : 'Add meal'}
                  </button>
                </div>
              </form>

              <div className="owned-menu">
                {(dashboard?.meals || []).map((meal) => (
                  <div className="list-item" key={meal.id}>
                    <div>
                      <strong>{meal.name}</strong>
                      <small>₹{meal.price} · {meal.stock} portions available</small>
                    </div>
                    <div className="editor-actions">
                      <button type="button" className="secondary-button" onClick={() => editMeal(meal)}>Edit</button>
                      <button type="button" className="danger-button" onClick={() => removeMeal(meal.id)}>Remove</button>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}

          {(user.role === 'student' || user.role === 'cook' || user.role === 'admin') && (
            <section className="panel order-panel" id="orders">
              <div className="section-header compact">
                <div>
                  <span className="eyebrow">History</span>
                  <h2>{user.role === 'student' ? 'Recent orders' : 'Active orders'}</h2>
                </div>
              </div>

              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Item</th>
                      <th>{user.role === 'student' ? 'Cook' : 'Student'}</th>
                      <th>Plan</th>
                      <th>Status</th>
                      <th>Amount</th>
                      {(user.role === 'cook' || user.role === 'student') && <th>Action</th>}
                    </tr>
                  </thead>
                  <tbody>
                    {((user.role === 'student' ? dashboard?.orders : dashboard?.orders || dashboard?.recent_orders || []) || []).map((order) => (
                      <tr key={order.id}>
                        <td>{order.meal_name}</td>
                        <td>{user.role === 'student' ? order.cook_name : order.student_name}</td>
                        <td>{order.plan_type}</td>
                        <td><span className="status-pill">{order.status.replace('_', ' ')}</span></td>
                        <td>₹{order.total_price}</td>
                        {(user.role === 'cook' || user.role === 'student') && (
                          <td>
                            {user.role === 'cook' && !['delivered', 'cancelled'].includes(order.status) && (
                              <select
                                aria-label={`Update order ${order.id} status`}
                                value={order.status}
                                onChange={(event) => changeOrderStatus(order.id, event.target.value)}
                              >
                                <option value="confirmed">Confirmed</option>
                                <option value="in_transit">In transit</option>
                                <option value="delivered">Delivered</option>
                                <option value="cancelled">Cancel order</option>
                              </select>
                            )}
                            {user.role === 'student' && order.status === 'delivered' && (
                              <button
                                type="button"
                                className="text-button"
                                onClick={() => openReviews({ id: order.meal_id, name: order.meal_name })}
                              >
                                Rate meal
                              </button>
                            )}
                          </td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {reviewMeal && (
            <div className="modal-backdrop" role="presentation" onClick={() => setReviewMeal(null)}>
              <section className="review-modal" role="dialog" aria-modal="true" aria-labelledby="review-title" onClick={(event) => event.stopPropagation()}>
                <button type="button" className="modal-close" aria-label="Close reviews" onClick={() => setReviewMeal(null)}>×</button>
                <span className="eyebrow">Student feedback</span>
                <h2 id="review-title">{reviewMeal.name} reviews</h2>
                <div className="review-list">
                  {reviews.length ? reviews.map((review) => (
                    <article key={review.id} className="review-item">
                      <div><strong>{review.student_name}</strong><span>⭐ {review.rating}/5</span></div>
                      <p>{review.comment || 'No written comment.'}</p>
                    </article>
                  )) : <p className="empty-state">No reviews yet.</p>}
                </div>
                {dashboard?.orders?.some((order) => order.meal_id === reviewMeal.id && order.status === 'delivered') && (
                  <form className="review-form" onSubmit={submitReview}>
                    <label>
                      Your rating
                      <select value={reviewRating} onChange={(event) => setReviewRating(event.target.value)}>
                        {[5, 4, 3, 2, 1].map((rating) => <option value={rating} key={rating}>{rating} stars</option>)}
                      </select>
                    </label>
                    <label>
                      Comment
                      <textarea
                        maxLength="255"
                        value={reviewComment}
                        onChange={(event) => setReviewComment(event.target.value)}
                        placeholder="Share what you liked about this meal"
                      />
                    </label>
                    <button className="primary-button" type="submit">Submit review</button>
                  </form>
                )}
              </section>
            </div>
          )}
        </main>
      )}
    </div>
  )
}

export default App
