import { createContext, useContext, useMemo, useState } from "react";

const AdminContext = createContext(null);

export function AdminProvider({ children }) {
  const [token, setToken] = useState("");
  const [clientId, setClientId] = useState("");
  const [revealedKeys, setRevealedKeys] = useState({});

  const value = useMemo(
    () => ({
      token,
      setToken,
      clientId,
      setClientId,
      revealedKeys,
      setRevealedKey(client, key) {
        setRevealedKeys((prev) => ({ ...prev, [client]: key }));
      },
      clearRevealedKey(client) {
        setRevealedKeys((prev) => {
          const next = { ...prev };
          delete next[client];
          return next;
        });
      },
      disconnect() {
        setToken("");
        setClientId("");
        setRevealedKeys({});
      },
    }),
    [token, clientId, revealedKeys],
  );

  return <AdminContext.Provider value={value}>{children}</AdminContext.Provider>;
}

export function useAdmin() {
  const ctx = useContext(AdminContext);
  if (!ctx) throw new Error("useAdmin must be used within AdminProvider");
  return ctx;
}
