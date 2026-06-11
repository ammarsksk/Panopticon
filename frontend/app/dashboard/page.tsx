"use client";

import { DashboardExperience } from "../DashboardExperience";
import { ProtectedClientPage } from "../ProtectedClientPage";
import { getDashboardData } from "@/lib/api";

export default function DashboardPage() {
  return (
    <ProtectedClientPage load={getDashboardData} title="Opening dashboard">
      {(data) => <DashboardExperience data={data} />}
    </ProtectedClientPage>
  );
}
