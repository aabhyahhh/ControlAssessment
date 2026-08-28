import { apiFetch } from "./api";
import type { User } from "../types";

interface TokenResponse {
  access_token: string;
  token_type: string;
}

export function login(email: string, password: string) {
  return apiFetch<TokenResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export function register(email: string, password: string, name?: string) {
  return apiFetch<TokenResponse>("/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password, name }),
  });
}

export function me() {
  return apiFetch<User>("/auth/me");
}
