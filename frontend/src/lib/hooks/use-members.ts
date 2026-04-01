"use client";

import { useState, useEffect } from "react";
import { collection, onSnapshot } from "firebase/firestore";
import { getFirestoreDb } from "@/lib/firebase";
import { useAuth } from "@/lib/auth-context";

export interface Member {
  id: string;
  email: string;
  role: string;
  joinedAt?: string;
}

export function useMembers() {
  const { session } = useAuth();
  const [members, setMembers] = useState<Member[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!session?.orgId) return;

    const db = getFirestoreDb();
    if (!db) {
      setLoading(false);
      return;
    }

    const membersRef = collection(db, "organizations", session.orgId, "members");
    const unsubscribe = onSnapshot(membersRef, (snapshot) => {
      setMembers(
        snapshot.docs.map((doc) => ({ id: doc.id, ...doc.data() }) as Member),
      );
      setLoading(false);
    });

    return () => unsubscribe();
  }, [session?.orgId]);

  return { members, loading };
}
