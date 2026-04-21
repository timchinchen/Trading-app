import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from './App'
import './index.css'

// Pause all `refetchInterval` polling while the tab/window is hidden. React
// Query keeps intervals firing in the background by default, which burns
// laptop battery and (more importantly) Alpaca API quota for no user benefit
// when the dashboard isn't actually being looked at. This flips the default
// for every useQuery; individual queries can still override it.
const qc = new QueryClient({
  defaultOptions: {
    queries: {
      refetchIntervalInBackground: false,
      refetchOnWindowFocus: true,
    },
  },
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
)
