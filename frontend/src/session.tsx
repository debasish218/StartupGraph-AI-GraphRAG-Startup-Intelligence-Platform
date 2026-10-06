import { createContext, useContext, useState, type Dispatch, type ReactNode, type SetStateAction } from 'react';
import type { QueryResponse } from './api';

export interface HistoryItem {
  id: number;
  question: string;
  at: Date;
  response: QueryResponse | null;
  error: string | null;
}

interface AskSession {
  history: HistoryItem[];
  setHistory: Dispatch<SetStateAction<HistoryItem[]>>;
  currentId: number | null;
  setCurrentId: (id: number | null) => void;
  pendingId: number | null;
  setPendingId: (id: number | null) => void;
}

const Ctx = createContext<AskSession | null>(null);

/** Keeps Ask-page history in memory across route changes (not persisted). */
export function AskSessionProvider({ children }: { children: ReactNode }) {
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [currentId, setCurrentId] = useState<number | null>(null);
  const [pendingId, setPendingId] = useState<number | null>(null);
  return <Ctx.Provider value={{ history, setHistory, currentId, setCurrentId, pendingId, setPendingId }}>{children}</Ctx.Provider>;
}

export function useAskSession(): AskSession {
  const v = useContext(Ctx);
  if (!v) throw new Error('useAskSession must be used inside AskSessionProvider');
  return v;
}
