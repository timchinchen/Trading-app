import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import type {
  Account,
  AgentAccountCache,
  AgentRun,
  AgentSignal,
  AgentStatus,
  AgentTrade,
  AgentTweetAnalysis,
  ChatMessage,
  ChatResponse,
  LLMInfo,
  LLMModels,
  Mode,
  Order,
  Position,
  Quote,
  WatchlistItem,
} from './types'

export const useMode = () =>
  useQuery({
    queryKey: ['mode'],
    queryFn: async () => (await api.get<Mode>('/mode')).data,
    staleTime: Infinity,
  })

export const useAccount = () =>
  useQuery({
    queryKey: ['account'],
    queryFn: async () => (await api.get<Account>('/account')).data,
    refetchInterval: 15000,
  })

export const usePositions = () =>
  useQuery({
    queryKey: ['positions'],
    queryFn: async () => (await api.get<Position[]>('/positions')).data,
    refetchInterval: 15000,
  })

export const useOrders = () =>
  useQuery({
    queryKey: ['orders'],
    queryFn: async () => (await api.get<Order[]>('/orders')).data,
    refetchInterval: 5000,
  })

export const useWatchlist = () =>
  useQuery({
    queryKey: ['watchlist'],
    queryFn: async () => (await api.get<WatchlistItem[]>('/watchlist')).data,
  })

export const useAddWatch = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: { symbol: string; feed: 'ws' | 'poll' }) =>
      (await api.post<WatchlistItem>('/watchlist', body)).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['watchlist'] }),
  })
}

export const useUpdateFeed = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ symbol, feed }: { symbol: string; feed: 'ws' | 'poll' }) =>
      (await api.patch<WatchlistItem>(`/watchlist/${symbol}`, { symbol, feed })).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['watchlist'] }),
  })
}

export const useRemoveWatch = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (symbol: string) => (await api.delete(`/watchlist/${symbol}`)).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['watchlist'] }),
  })
}

export const useQuote = (symbol: string) =>
  useQuery({
    queryKey: ['quote', symbol],
    queryFn: async () => (await api.get<Quote>(`/quotes/${symbol}`)).data,
    enabled: !!symbol,
  })

export const usePlaceOrder = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: {
      symbol: string
      qty: number
      side: 'buy' | 'sell'
      type: 'market' | 'limit'
      limit_price?: number
    }) => (await api.post<Order>('/orders', body)).data,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['orders'] })
      qc.invalidateQueries({ queryKey: ['account'] })
      qc.invalidateQueries({ queryKey: ['positions'] })
    },
  })
}

export const useCancelOrder = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: number) => (await api.delete(`/orders/${id}`)).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['orders'] }),
  })
}

export const useAgentStatus = () =>
  useQuery({
    queryKey: ['agent', 'status'],
    queryFn: async () => (await api.get<AgentStatus>('/agent/status')).data,
    refetchInterval: 10000,
  })

export const useAgentRuns = () =>
  useQuery({
    queryKey: ['agent', 'runs'],
    queryFn: async () => (await api.get<AgentRun[]>('/agent/runs')).data,
    refetchInterval: 10000,
  })

export const useAgentRunSignals = (runId: number | null) =>
  useQuery({
    queryKey: ['agent', 'runs', runId, 'signals'],
    queryFn: async () =>
      (await api.get<AgentSignal[]>(`/agent/runs/${runId}/signals`)).data,
    enabled: !!runId,
  })

export const useAgentRunTrades = (runId: number | null) =>
  useQuery({
    queryKey: ['agent', 'runs', runId, 'trades'],
    queryFn: async () =>
      (await api.get<AgentTrade[]>(`/agent/runs/${runId}/trades`)).data,
    enabled: !!runId,
  })

export const useAgentRunNow = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async () => (await api.post<AgentRun>('/agent/run-now')).data,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['agent'] })
      qc.invalidateQueries({ queryKey: ['orders'] })
      qc.invalidateQueries({ queryKey: ['positions'] })
    },
  })
}

export const useAgentAccountsCache = () =>
  useQuery({
    queryKey: ['agent', 'accounts-cache'],
    queryFn: async () =>
      (await api.get<AgentAccountCache[]>('/agent/accounts-cache')).data,
    refetchInterval: 30000,
  })

export const useAgentRunTweets = (runId: number | null) =>
  useQuery({
    queryKey: ['agent', 'runs', runId, 'tweets'],
    queryFn: async () =>
      (await api.get<AgentTweetAnalysis[]>(`/agent/runs/${runId}/tweets`)).data,
    enabled: !!runId,
  })

export const useAgentRunDetail = (runId: number | null) =>
  useQuery({
    queryKey: ['agent', 'runs', 'detail', runId],
    queryFn: async () =>
      (await api.get<AgentRun[]>(`/agent/runs`)).data.find((r) => r.id === runId) ??
      null,
    enabled: !!runId,
  })

export const useLLMInfo = () =>
  useQuery({
    queryKey: ['llm', 'info'],
    queryFn: async () => (await api.get<LLMInfo>('/llm/info')).data,
    staleTime: Infinity,
  })

export const useLLMModels = () =>
  useQuery({
    queryKey: ['llm', 'models'],
    queryFn: async () => (await api.get<LLMModels>('/llm/models')).data,
  })

export const useChat = () =>
  useMutation({
    mutationFn: async (body: {
      messages: ChatMessage[]
      system?: string
      model?: string
      temperature?: number
    }) =>
      (
        await api.post<ChatResponse>('/llm/chat', body, {
          // Local Ollama can take 30–180s for first token on a cold model.
          timeout: 300_000,
        })
      ).data,
  })
