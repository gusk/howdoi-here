export interface User {
  id: number;
  email: string;
}

export function loadUsers(rows: Array<Record<string, string>>): User[] {
  return rows.map((r) => ({ id: Number(r.id), email: r.email.toLowerCase() }));
}

export const activeEmails = (users: User[]): string[] =>
  users.filter((u) => u.email.endsWith("@acme.com")).map((u) => u.email);

export function indexById(users: User[]): Record<number, User> {
  return Object.fromEntries(users.map((u) => [u.id, u]));
}
