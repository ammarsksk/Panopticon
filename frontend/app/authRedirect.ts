import { redirect } from "next/navigation";
import { isUnauthorized } from "@/lib/api";

export function redirectIfUnauthorized(error: unknown): never {
  if (isUnauthorized(error)) {
    redirect("/login");
  }
  throw error;
}
