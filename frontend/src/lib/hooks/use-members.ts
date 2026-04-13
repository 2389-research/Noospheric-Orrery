"use client";

import { useState } from "react";

export interface Member {
  id: string;
  email: string;
  role: string;
  joinedAt?: string;
}

export function useMembers() {
  // Local mode — single dev user, no member management
  const [members] = useState<Member[]>([
    { id: "dev-user", email: "dev@localhost", role: "admin" },
  ]);
  const [loading] = useState(false);

  return { members, loading };
}
