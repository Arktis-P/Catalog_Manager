import { createContext, useCallback, useContext, useRef, useState } from "react";

interface WikiPanelContextValue {
  wikiUrl: string | null;
  wikiHistory: string[];
  wikiCursor: number;
  openWiki: (url: string) => void;
  closeWiki: () => void;
  wikiBack: () => void;
  wikiForward: () => void;
}

const WikiPanelContext = createContext<WikiPanelContextValue>({
  wikiUrl: null,
  wikiHistory: [],
  wikiCursor: -1,
  openWiki: () => {},
  closeWiki: () => {},
  wikiBack: () => {},
  wikiForward: () => {},
});

export function WikiPanelProvider({ children }: { children: React.ReactNode }) {
  const [wikiHistory, setWikiHistory] = useState<string[]>([]);
  const [wikiCursor, setWikiCursor] = useState(-1);
  const cursorRef = useRef(-1);
  const historyRef = useRef<string[]>([]);

  const openWiki = useCallback((url: string) => {
    const newHistory = historyRef.current.slice(0, cursorRef.current + 1).concat(url);
    historyRef.current = newHistory;
    cursorRef.current = newHistory.length - 1;
    setWikiHistory(newHistory);
    setWikiCursor(cursorRef.current);
  }, []);

  const closeWiki = useCallback(() => {
    historyRef.current = [];
    cursorRef.current = -1;
    setWikiHistory([]);
    setWikiCursor(-1);
  }, []);

  const wikiBack = useCallback(() => {
    if (cursorRef.current > 0) {
      cursorRef.current -= 1;
      setWikiCursor(cursorRef.current);
    }
  }, []);

  const wikiForward = useCallback(() => {
    if (cursorRef.current < historyRef.current.length - 1) {
      cursorRef.current += 1;
      setWikiCursor(cursorRef.current);
    }
  }, []);

  const wikiUrl = wikiCursor >= 0 ? wikiHistory[wikiCursor] ?? null : null;

  return (
    <WikiPanelContext.Provider
      value={{ wikiUrl, wikiHistory, wikiCursor, openWiki, closeWiki, wikiBack, wikiForward }}
    >
      {children}
    </WikiPanelContext.Provider>
  );
}

export function useWikiPanel() {
  return useContext(WikiPanelContext);
}
